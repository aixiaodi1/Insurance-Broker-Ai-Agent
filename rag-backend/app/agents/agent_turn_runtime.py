from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.services.agent_tools import (
    github_file_read,
    github_repo_tree,
    local_search,
    run_cli,
    web_fetch,
    web_search,
)
from app.services.command_permissions import approval_request
from app.services.conversation_memory import ConversationMemoryStore
from app.services.system_prompt_assembler import SystemPromptAssembler


class AnswerGenerator(Protocol):
    def generate(self, prompt: str, system_prompt: str | None = None) -> dict: ...


class WorkflowRunner(Protocol):
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict: ...


SUPPORTED_ACTIONS = {"final", "tool_call", "workflow_call", "clarify"}

PUBLIC_PLANNING_SCHEMA: dict[str, Any] = {
    "intent_anchor": {
        "user_goal": "What outcome the user is really asking for.",
        "real_blocker": "The execution obstacle or missing capability behind the literal words.",
        "scope_direction": "expand | narrow | hold | execute",
        "needs_execution": True,
        "confidence": 0.0,
    },
    "task_decomposition": {
        "knowledge_gaps": ["Facts needed before a reliable answer or action is possible."],
        "hypotheses": [
            {
                "id": "H1",
                "claim": "A falsifiable claim to check.",
                "falsifiable_by": "What observation would disprove it.",
            }
        ],
        "verification_paths": [{"hypothesis_id": "H1", "path": "file:line, URL, command, or data source"}],
        "dependency_graph": ["H1 -> H2"],
        "ordered_tasks": [{"id": "T1", "description": "Next public task", "depends_on": [], "status": "pending"}],
    },
    "execution_mode": "plan_only | execute",
    "next_action": "What the agent should do next.",
}


def parse_react_decision(text: str) -> dict[str, Any]:
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        malformed_final = _extract_malformed_final_answer(text)
        if malformed_final:
            return {"action": "final", "answer": malformed_final}
        return {"action": "final", "answer": text.strip()}
    action = parsed.get("action")
    if action not in SUPPORTED_ACTIONS:
        return {"action": "final", "answer": str(parsed.get("answer") or text).strip()}
    if action == "final" and isinstance(parsed.get("answer"), str):
        nested = _extract_json_object(str(parsed.get("answer") or ""))
        if isinstance(nested, dict) and nested.get("action") == "final" and nested.get("answer"):
            return {"action": "final", "answer": str(nested.get("answer") or "").strip()}
    return parsed


class AgentTurnRuntime:
    def __init__(
        self,
        generator: AnswerGenerator,
        insurance_workflow: WorkflowRunner,
        memory_store: ConversationMemoryStore | None = None,
        prompt_assembler: SystemPromptAssembler | None = None,
        project_root: Path | None = None,
        local_source_root: Path | None = None,
        max_steps: int = 4,
    ) -> None:
        self._generator = generator
        self._insurance_workflow = insurance_workflow
        self._memory_store = memory_store
        self._project_root = project_root or Path(".")
        self._local_source_root = local_source_root or self._project_root
        self._prompt_assembler = prompt_assembler or SystemPromptAssembler(project_root=self._project_root)
        self._max_steps = max_steps
        if self._memory_store is not None:
            self._memory_store.initialize()

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        return self.run_transparent(
            prompt=prompt,
            collection=collection,
            agent_id=agent_id,
            thread_id=thread_id,
            user_id=user_id,
            collected_vars=collected_vars,
        )

    def run_transparent(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        stream_events: list[dict[str, Any]] = []

        def emit(event_type: str, **payload: Any) -> dict[str, Any]:
            event = {
                "type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                **payload,
            }
            stream_events.append(_public_stream_event(event))
            return event

        emit("run_started", summary="Received request; preparing the agent runtime.")
        emit(
            "context_loaded",
            summary="Loaded bootstrap context, tools, skills, providers, memory, and current time.",
            context=self._public_context_summary(),
        )
        planning = (
            _fallback_public_planning(prompt)
            if (collected_vars or {}).get("commandApproved")
            else self._plan_public_process(prompt=prompt, user_id=user_id, thread_id=thread_id)
        )
        intent = planning.get("intent_anchor") if isinstance(planning.get("intent_anchor"), dict) else {}
        decomposition = (
            planning.get("task_decomposition") if isinstance(planning.get("task_decomposition"), dict) else {}
        )
        emit(
            "intent_anchor",
            summary=str(intent.get("user_goal") or "Anchored the user's goal."),
            intent=intent,
        )
        emit(
            "task_decomposition",
            summary=f"{len(decomposition.get('ordered_tasks') or [])} tasks planned.",
            taskDecomposition=decomposition,
        )
        run = self._run_react_core(
            prompt=prompt,
            collection=collection,
            agent_id=agent_id,
            thread_id=thread_id,
            user_id=user_id,
            collected_vars=collected_vars,
        )
        for step in (run.get("responseJson") or {}).get("reactSteps") or []:
            emit("react_decision", summary=_decision_summary(step), step=step)
        for tool_call in run.get("toolCalls") or []:
            emit(
                "tool_started",
                summary=f"正在执行工具：{tool_call.get('name')}",
                toolCall=tool_call,
            )
            emit(
                "tool_finished",
                summary=str(tool_call.get("resultPreview") or tool_call.get("status") or ""),
                toolCall=tool_call,
            )
            emit(
                "observation",
                summary=str(tool_call.get("resultPreview") or tool_call.get("status") or ""),
                observation={
                    "tool": tool_call.get("name"),
                    "status": tool_call.get("status"),
                    "resultPreview": tool_call.get("resultPreview"),
                },
            )
        workflow = (run.get("responseJson") or {}).get("workflow")
        if isinstance(workflow, dict):
            emit("workflow_started", summary=f"进入 workflow：{workflow.get('name')}", workflow=workflow)
            emit("workflow_finished", summary=f"workflow 完成：{workflow.get('status')}", workflow=workflow)
        if run.get("approvalRequest"):
            emit(
                "approval_required",
                summary="这个操作需要你确认后才会执行。",
                approvalRequest=run["approvalRequest"],
            )
        if run.get("finalAnswer"):
            emit("final_answer", summary="Final answer generated.", finalAnswer=run.get("finalAnswer"))
        response_json = run.get("responseJson") if isinstance(run.get("responseJson"), dict) else {}
        run = {
            **run,
            "responseJson": {
                **response_json,
                "publicPlanning": planning,
                "streamEvents": [],
            },
        }
        emit("run_finished", summary="本轮处理完成。", run=run)
        run["responseJson"]["streamEvents"] = [*stream_events]
        return run

    def _run_react_core(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        approved_command_response = self._run_approved_command_if_present(
            prompt, collection, agent_id, thread_id, user_id, collected_vars or {}
        )
        if approved_command_response is not None:
            return approved_command_response

        effective_thread_id = thread_id or f"{user_id}:{uuid4().hex}"
        vars_payload = collected_vars or {}
        remembered_context = self._recall_memory(user_id, effective_thread_id, prompt)
        session_id = self._create_memory_session(user_id, effective_thread_id, prompt)
        system_prompt = self._prompt_assembler.build(remembered_context)
        react_steps: list[dict[str, Any]] = []
        nodes: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        run_id = f"run_{uuid4().hex}"
        started_at = datetime.now(UTC).isoformat()

        model_prompt = _render_turn_prompt(prompt, react_steps)
        for index in range(self._max_steps):
            decision = parse_react_decision(
                str(self._generator.generate(model_prompt, system_prompt=system_prompt).get("answer") or "")
            )
            react_step = {"index": index + 1, **_public_decision(decision)}
            react_steps.append(react_step)

            action = decision.get("action")
            if action == "final":
                answer = str(decision.get("answer") or "")
                response = self._build_response(
                    run_id,
                    prompt,
                    collection,
                    agent_id,
                    effective_thread_id,
                    user_id,
                    answer,
                    started_at,
                    nodes,
                    events,
                    tool_calls,
                    react_steps,
                )
                self._save_memory(session_id, user_id, effective_thread_id, prompt, answer)
                return response

            if action == "clarify":
                answer = str(decision.get("question") or decision.get("answer") or "")
                response = self._build_response(
                    run_id,
                    prompt,
                    collection,
                    agent_id,
                    effective_thread_id,
                    user_id,
                    answer,
                    started_at,
                    nodes,
                    events,
                    tool_calls,
                    react_steps,
                )
                self._save_memory(session_id, user_id, effective_thread_id, prompt, answer)
                return response

            if action == "workflow_call":
                workflow_response = self._run_workflow(
                    decision,
                    prompt,
                    collection,
                    agent_id,
                    effective_thread_id,
                    user_id,
                    vars_payload,
                )
                response = _merge_workflow_response(
                    workflow_response,
                    run_id=run_id,
                    prompt=prompt,
                    started_at=started_at,
                    react_steps=react_steps,
                )
                self._save_memory(session_id, user_id, effective_thread_id, prompt, str(response.get("finalAnswer") or ""))
                return response

            if action == "tool_call":
                tool_name = str(decision.get("tool") or "")
                tool_args = _normalize_tool_arguments(tool_name, decision.get("arguments"), react_steps)
                react_steps[-1]["arguments"] = tool_args
                tool_result = self._run_tool(tool_name, tool_args, vars_payload)
                node, event, tool_call = _tool_trace(run_id, tool_name, tool_result, tool_args)
                nodes.append(node)
                events.append(event)
                tool_calls.append(tool_call)
                react_steps[-1]["toolResult"] = _preview_tool_result(tool_result)
                if tool_result.get("error") == "human_approval_required":
                    approval_request = (tool_result.get("data") or {}).get("approvalRequest")
                    return self._build_response(
                        run_id,
                        prompt,
                        collection,
                        agent_id,
                        effective_thread_id,
                        user_id,
                        "这个操作需要你确认后才会执行。",
                        started_at,
                        nodes,
                        events,
                        tool_calls,
                        react_steps,
                        status="awaiting_approval",
                        approval_request=approval_request,
                    )
                if not tool_result.get("ok"):
                    if _is_recoverable_tool_failure(tool_name):
                        model_prompt = _render_turn_prompt(prompt, react_steps)
                        continue
                    return self._build_response(
                        run_id,
                        prompt,
                        collection,
                        agent_id,
                        effective_thread_id,
                        user_id,
                        f"工具没有执行成功：{tool_result.get('error')}",
                        started_at,
                        nodes,
                        events,
                        tool_calls,
                        react_steps,
                        status="failed",
                    )
                model_prompt = _render_turn_prompt(prompt, react_steps)
                continue

        fallback_answer = "I reached the maximum ReAct steps for this turn without a final answer. Please narrow the task or let me continue with another turn."
        response = self._build_response(
            run_id,
            prompt,
            collection,
            agent_id,
            effective_thread_id,
            user_id,
            fallback_answer,
            started_at,
            nodes,
            events,
            tool_calls,
            react_steps,
            status="failed",
        )
        self._save_memory(session_id, user_id, effective_thread_id, prompt, fallback_answer)
        return response

    def stream(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ):
        run = self.run_transparent(
            prompt=prompt,
            collection=collection,
            agent_id=agent_id,
            thread_id=thread_id,
            user_id=user_id,
            collected_vars=collected_vars,
        )
        for event in (run.get("responseJson") or {}).get("streamEvents") or []:
            if event.get("type") == "run_finished":
                yield {**event, "run": run}
            else:
                yield event

    def _public_context_summary(self) -> dict[str, Any]:
        return {
            "projectRoot": str(self._project_root),
            "localSourceRoot": str(self._local_source_root),
            "tools": [
                "local_search",
                "web_search",
                "web.fetch",
                "github.repo_tree",
                "github.file_read",
                "shell.exec",
            ],
            "subAgents": ["insurance_research", "claim_analysis", "document_review"],
            "provider": type(self._generator).__name__,
            "currentDatetime": datetime.now(UTC).isoformat(),
        }

    def _plan_public_process(self, prompt: str, user_id: str, thread_id: str | None) -> dict[str, Any]:
        effective_thread_id = thread_id or f"{user_id}:stream"
        remembered_context = self._recall_memory(user_id, effective_thread_id, prompt)
        system_prompt = "\n".join(
            [
                "You write public planning summaries for a ReAct agent.",
                "Do not reveal hidden chain-of-thought. Do reveal concise, user-safe process notes.",
                "Do not force fixed categories such as identity, chat, clarification, official evidence, or insurance.",
                "Return JSON only.",
            ]
        )
        planning_prompt = "\n\n".join(
            [
                "Create hypothesis-driven decomposition for the user message.",
                f"Schema:\n{json.dumps(PUBLIC_PLANNING_SCHEMA, ensure_ascii=False)}",
                f"Context summary:\n{json.dumps(self._public_context_summary(), ensure_ascii=False, default=str)}",
                f"Remembered context:\n{json.dumps(remembered_context, ensure_ascii=False, default=str)[:8000]}",
                f"User message:\n{prompt}",
            ]
        )
        response = self._generator.generate(planning_prompt, system_prompt=system_prompt)
        parsed = _extract_json_object(str(response.get("answer") or ""))
        if not isinstance(parsed, dict):
            return _fallback_public_planning(prompt)
        return _normalize_public_planning(parsed, prompt)

    def _run_approved_command_if_present(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str,
        collected_vars: dict,
    ) -> dict | None:
        if not collected_vars.get("commandApproved") or not collected_vars.get("approvedCommand"):
            return None
        command = str(collected_vars.get("approvedCommand") or "")
        mode = str(collected_vars.get("commandMode") or "plan")
        expected = approval_request(command, mode)
        if collected_vars.get("approvalId") != expected["id"]:
            timestamp = datetime.now(UTC).isoformat()
            return _simple_failed_response(prompt, "approval_mismatch: 批准 ID 与命令不匹配，已拒绝执行。", started_at=timestamp)

        effective_thread_id = thread_id or f"{user_id}:{uuid4().hex}"
        run_id = f"run_{uuid4().hex}"
        started_at = datetime.now(UTC).isoformat()
        result = self._run_tool(
            "shell.exec",
            {"command": command},
            {**collected_vars, "commandApproved": True},
        )
        node, event, tool_call = _tool_trace(run_id, "shell.exec", result, {"command": command})
        answer = _tool_final_answer("shell.exec", result) if result.get("ok") else f"工具没有执行成功：{result.get('error')}"
        return self._build_response(
            run_id,
            prompt,
            collection,
            agent_id,
            effective_thread_id,
            user_id,
            answer,
            started_at,
            [node],
            [event],
            [tool_call],
            [
                {
                    "index": 1,
                    "action": "tool_call",
                    "tool": "shell.exec",
                    "arguments": {"command": command},
                    "decisionSource": "approved_command",
                    "toolResult": _preview_tool_result(result),
                }
            ],
            status="succeeded" if result.get("ok") else "failed",
        )

    def _run_workflow(
        self,
        decision: dict[str, Any],
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str,
        user_id: str,
        collected_vars: dict,
    ) -> dict:
        workflow = str(decision.get("workflow") or "")
        if workflow not in {"insurance_research", "claim_analysis", "document_review"}:
            return _simple_failed_response(prompt, f"未知 workflow：{workflow}")
        arguments = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
        workflow_prompt = str(arguments.get("prompt") or prompt)
        return self._insurance_workflow.run(
            prompt=workflow_prompt,
            collection=collection,
            agent_id=agent_id,
            thread_id=thread_id,
            user_id=user_id,
            collected_vars=collected_vars,
        )

    def _run_tool(
        self,
        tool_name: str,
        arguments: Any,
        collected_vars: dict,
    ) -> dict[str, Any]:
        args = arguments if isinstance(arguments, dict) else {}
        if tool_name in {"local_search", "filesystem.grep", "filesystem.read"}:
            return local_search(str(args.get("query") or ""), self._local_source_root)
        if tool_name in {"web_search", "web.search"}:
            query = str(args.get("query") or "")
            return web_search(query)
        if tool_name in {"web_fetch", "web.fetch"}:
            return web_fetch(str(args.get("url") or ""))
        if tool_name in {"github.repo_tree", "github_repo_tree"}:
            return github_repo_tree(str(args.get("url") or args.get("repoUrl") or ""))
        if tool_name in {"github.file_read", "github_file_read"}:
            return github_file_read(str(args.get("repoUrl") or args.get("url") or ""), str(args.get("path") or ""))
        if tool_name in {"shell.exec", "run_cli"}:
            return run_cli(
                str(args.get("command") or ""),
                self._local_source_root,
                mode=str(collected_vars.get("commandMode") or "plan"),
                approved=bool(collected_vars.get("commandApproved")),
            )
        return {"ok": False, "source": tool_name, "data": {"arguments": args}, "error": "unknown_tool"}

    def _recall_memory(self, user_id: str, thread_id: str, prompt: str) -> dict[str, Any]:
        if self._memory_store is None:
            return {}
        return self._memory_store.recall_memory(user_id=user_id, thread_id=thread_id, query=prompt)

    def _create_memory_session(self, user_id: str, thread_id: str, prompt: str) -> str | None:
        if self._memory_store is None:
            return None
        session_id = self._memory_store.create_session(
            user_id=user_id,
            thread_id=thread_id,
            title=prompt[:40] or "conversation",
            task_type="agent_turn",
        )
        self._memory_store.add_message(session_id=session_id, role="user", content=prompt)
        return session_id

    def _save_memory(self, session_id: str | None, user_id: str, thread_id: str, prompt: str, answer: str) -> None:
        if self._memory_store is None or session_id is None or not answer:
            return
        self._memory_store.add_message(session_id=session_id, role="assistant", content=answer)
        self._memory_store.upsert_thread_summary(
            user_id=user_id,
            thread_id=thread_id,
            summary=f"Latest question: {prompt[:500]}; latest answer: {answer[:500]}",
            latest_session_id=session_id,
            final_answer=answer,
        )

    def _build_response(
        self,
        run_id: str,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str,
        user_id: str,
        final_answer: str,
        started_at: str,
        nodes: list[dict[str, Any]],
        events: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        react_steps: list[dict[str, Any]],
        status: str = "succeeded",
        approval_request: dict[str, Any] | None = None,
    ) -> dict:
        finished_at = datetime.now(UTC).isoformat()
        latency_ms = _elapsed_ms(started_at, finished_at)
        entry_node = {
            "id": "agent_turn_runtime",
            "label": "Agent Turn Runtime",
            "status": status,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "durationMs": latency_ms,
            "stateSummary": f"ReAct steps: {len(react_steps)}",
        }
        entry_event = {
            "id": f"{run_id}_evt_agent_turn_runtime",
            "nodeId": "agent_turn_runtime",
            "type": "node_end",
            "timestamp": finished_at,
            "title": "Agent Turn Runtime",
            "detail": final_answer[:600],
            "payload": {"reactSteps": react_steps},
        }
        return {
            "id": run_id,
            "mode": "real",
            "prompt": prompt,
            "status": status,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "latencyMs": latency_ms,
            "nodes": [entry_node, *nodes],
            "events": [entry_event, *events],
            "toolCalls": tool_calls,
            "vectorMatches": [],
            "requestJson": {
                "prompt": prompt,
                "agentId": agent_id,
                "threadId": thread_id,
                "collection": collection,
                "userId": user_id,
            },
            "responseJson": {
                "agentRuntime": {
                    "entry": "agent_turn_runtime",
                    "maxSteps": self._max_steps,
                    "timings": {"totalMs": latency_ms},
                    "controlMode": "llm_react",
                    "mainlineConstraintsRemoved": [
                        "fixed_turn_context_router",
                        "explicit_command_shortcut",
                        "insurance_search_enhancement",
                        "evidence_fallback_answer",
                    ],
                },
                "reactSteps": react_steps,
            },
            "finalAnswer": final_answer,
            **({"approvalRequest": approval_request} if approval_request else {}),
        }


def _render_turn_prompt(prompt: str, react_steps: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            f"User input: {prompt}",
            "",
            "Use hypothesis-driven ReAct. Decide the next action from the user goal, current observations, and available tools.",
            "Do not rely on fixed intent categories or domain evidence gates. If a domain workflow is useful, choose it explicitly.",
            "If more work is needed, return one tool_call or workflow_call. If the answer is ready, return final.",
            f"Executed steps: {json.dumps(react_steps, ensure_ascii=False)}",
        ]
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```", r"(\{.*\})"]:
        match = re.search(pattern, stripped, re.DOTALL)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_malformed_final_answer(text: str) -> str:
    stripped = text.strip()
    match = re.match(r'\{\s*"action"\s*:\s*"final"\s*,\s*"answer"\s*:\s*"', stripped, re.DOTALL)
    if not match:
        return ""
    end = stripped.rfind('"}')
    if end <= match.end():
        end = stripped.rfind('"')
    if end <= match.end():
        return ""
    answer = stripped[match.end() : end]
    return answer.replace('\\"', '"').replace("\\n", "\n").strip()


def _normalize_public_planning(raw: dict[str, Any], prompt: str) -> dict[str, Any]:
    fallback = _fallback_public_planning(prompt)
    intent = raw.get("intent_anchor") if isinstance(raw.get("intent_anchor"), dict) else {}
    decomposition = raw.get("task_decomposition") if isinstance(raw.get("task_decomposition"), dict) else {}
    fallback_intent = fallback["intent_anchor"]
    fallback_decomposition = fallback["task_decomposition"]
    return {
        "intent_anchor": {
            "user_goal": str(intent.get("user_goal") or fallback_intent["user_goal"]),
            "real_blocker": str(intent.get("real_blocker") or fallback_intent["real_blocker"]),
            "scope_direction": str(intent.get("scope_direction") or fallback_intent["scope_direction"]),
            "needs_execution": bool(intent.get("needs_execution", fallback_intent["needs_execution"])),
            "confidence": intent.get("confidence", fallback_intent["confidence"]),
        },
        "task_decomposition": {
            "knowledge_gaps": _list_or_fallback(decomposition.get("knowledge_gaps"), fallback_decomposition["knowledge_gaps"]),
            "hypotheses": _list_or_fallback(decomposition.get("hypotheses"), fallback_decomposition["hypotheses"]),
            "verification_paths": _list_or_fallback(
                decomposition.get("verification_paths"),
                fallback_decomposition["verification_paths"],
            ),
            "dependency_graph": _list_or_fallback(decomposition.get("dependency_graph"), fallback_decomposition["dependency_graph"]),
            "ordered_tasks": _list_or_fallback(decomposition.get("ordered_tasks"), fallback_decomposition["ordered_tasks"]),
        },
        "execution_mode": str(raw.get("execution_mode") or "execute"),
        "next_action": str(raw.get("next_action") or fallback["next_action"]),
    }


def _fallback_public_planning(prompt: str) -> dict[str, Any]:
    return {
        "intent_anchor": {
            "user_goal": prompt[:240],
            "real_blocker": "The agent needs to inspect context and decide which tool or answer path is justified.",
            "scope_direction": "execute",
            "needs_execution": True,
            "confidence": 0.5,
        },
        "task_decomposition": {
            "knowledge_gaps": ["Which facts are missing", "Which tools can verify them", "When the answer is ready"],
            "hypotheses": [
                {
                    "id": "H1",
                    "claim": "The request can be advanced by one ReAct step.",
                    "falsifiable_by": "The next model decision returns no answer and no valid tool call.",
                }
            ],
            "verification_paths": [{"hypothesis_id": "H1", "path": "agent runtime decision and tool observations"}],
            "dependency_graph": ["H1"],
            "ordered_tasks": [
                {"id": "T1", "description": "Ask the model for the next ReAct decision.", "depends_on": [], "status": "pending"}
            ],
        },
        "execution_mode": "execute",
        "next_action": "Continue with the ReAct loop.",
    }


def _list_or_fallback(value: Any, fallback: list[Any]) -> list[Any]:
    return value if isinstance(value, list) and value else fallback


def _public_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in decision.items() if key != "answer"}


def _normalize_tool_arguments(
    tool_name: str,
    arguments: Any,
    react_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    args = dict(arguments) if isinstance(arguments, dict) else {}
    if tool_name in {"github.repo_tree", "github_repo_tree"} and not (args.get("url") or args.get("repoUrl")):
        repo_url = _latest_github_repo_url(react_steps)
        if repo_url:
            args["url"] = repo_url
    if tool_name in {"web.fetch", "web_fetch"} and not args.get("url"):
        source_url = _latest_web_result_url(react_steps)
        if source_url:
            args["url"] = source_url
    if tool_name in {"github.file_read", "github_file_read"}:
        if not (args.get("repoUrl") or args.get("url")):
            repo_url = _latest_github_repo_url(react_steps)
            if repo_url:
                args["repoUrl"] = repo_url
        if not args.get("path"):
            path = _first_github_candidate_path(react_steps)
            if path:
                args["path"] = path
    return args


def _is_recoverable_tool_failure(tool_name: str) -> bool:
    return tool_name in {
        "web_search",
        "web.search",
        "web_fetch",
        "web.fetch",
        "github.repo_tree",
        "github_repo_tree",
        "github.file_read",
        "github_file_read",
        "local_search",
        "filesystem.grep",
        "filesystem.read",
    }


def _latest_github_repo_url(react_steps: list[dict[str, Any]]) -> str:
    for step in reversed(react_steps):
        tool_result = step.get("toolResult")
        if not isinstance(tool_result, dict) or not tool_result.get("ok"):
            continue
        for item in tool_result.get("results") or []:
            if isinstance(item, dict):
                url = str(item.get("url") or "")
                if _is_github_repo_url(url):
                    return url
        url = str(tool_result.get("url") or tool_result.get("repoUrl") or "")
        if _is_github_repo_url(url):
            return url
    return ""


def _latest_web_result_url(react_steps: list[dict[str, Any]]) -> str:
    for step in reversed(react_steps):
        tool_result = step.get("toolResult")
        if not isinstance(tool_result, dict) or not tool_result.get("ok"):
            continue
        for item in tool_result.get("results") or []:
            if isinstance(item, dict):
                url = str(item.get("url") or "")
                if url:
                    return url
    return ""


def _first_github_candidate_path(react_steps: list[dict[str, Any]]) -> str:
    for step in reversed(react_steps):
        tool_result = step.get("toolResult")
        if not isinstance(tool_result, dict) or tool_result.get("source") != "github_repo_tree":
            continue
        for path in _github_research_paths({"data": {"files": tool_result.get("files") or []}}):
            return path
    return ""


def _decision_summary(step: dict[str, Any]) -> str:
    action = step.get("action")
    if action == "final":
        return "决定直接回答。"
    if action == "clarify":
        return "需要向用户追问补充信息。"
    if action == "tool_call":
        return f"决定调用工具：{step.get('tool')}"
    if action == "workflow_call":
        return f"决定进入 workflow：{step.get('workflow')}"
    return "完成一步运行决策。"


def _public_stream_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "run"}


def _elapsed_ms(started_at: str, finished_at: str) -> int:
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at)
        return max(1, int((finished - started).total_seconds() * 1000))
    except ValueError:
        return 1


def _tool_trace(run_id: str, tool_name: str, result: dict[str, Any], arguments: dict[str, Any]) -> tuple[dict, dict, dict]:
    timestamp = datetime.now(UTC).isoformat()
    status = "succeeded" if result.get("ok") else ("pending" if result.get("error") == "human_approval_required" else "failed")
    detail = _preview_text((result.get("data") or {}).get("stdout") or result.get("data") or result.get("error") or "")
    node = {
        "id": tool_name,
        "label": tool_name,
        "status": status,
        "startedAt": timestamp,
        "finishedAt": timestamp,
        "durationMs": 0,
        "stateSummary": detail,
    }
    event = {
        "id": f"{run_id}_evt_{tool_name}",
        "nodeId": tool_name,
        "type": "tool_call",
        "timestamp": timestamp,
        "title": tool_name,
        "detail": detail,
        "payload": result,
    }
    tool_call = {
        "id": f"{run_id}_tool_{tool_name}",
        "nodeId": tool_name,
        "name": tool_name,
        "status": status,
        "arguments": arguments,
        "durationMs": 0,
        "resultPreview": detail,
    }
    return node, event, tool_call


def _auto_tool_trace(
    run_id: str,
    tool_name: str,
    result: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict, dict, dict]:
    node, event, tool_call = _tool_trace(run_id, tool_name, result, arguments)
    step = {
        "index": 0,
        "action": "tool_call",
        "tool": tool_name,
        "arguments": arguments,
        "decisionSource": "runtime_auto_content_read",
        "toolResult": _preview_tool_result(result),
    }
    return step, node, event, tool_call


def _tool_final_answer(tool_name: str, result: dict[str, Any]) -> str:
    data = result.get("data") or {}
    if tool_name in {"local_search", "filesystem.grep", "filesystem.read"}:
        matches = list(data.get("matches") or [])
        if not matches:
            return "我检查了本地文件，暂时没有找到匹配内容。"
        lines = ["我检查了本地文件，找到这些线索："]
        for item in matches[:5]:
            lines.append(f"- {item.get('excerpt', '').strip()}（来源: {item.get('path')}）")
        return "\n".join(lines)
    if tool_name in {"shell.exec", "run_cli"}:
        output = str(data.get("stdout") or data.get("stderr") or "").strip()
        return f"命令执行结果：\n{output or '命令执行完成，但没有输出。'}"
    if tool_name in {"web_search", "web.search"}:
        results = list(data.get("results") or [])
        if not results:
            return "我搜索了网页，暂时没有找到可用结果。"
        return "\n".join(["我搜索到这些结果：", *[f"- {item.get('title')}（{item.get('url')}）" for item in results[:3]]])
    return "工具执行完成。"


def _preview_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    preview: dict[str, Any] = {"ok": result.get("ok"), "source": result.get("source"), "error": result.get("error")}
    source = result.get("source")
    if source == "web_search":
        preview["results"] = [
            {"title": item.get("title"), "url": item.get("url")}
            for item in list(data.get("results") or [])[:5]
            if isinstance(item, dict)
        ]
        preview["query"] = data.get("query")
    elif source == "web_fetch":
        preview["url"] = data.get("url")
        preview["text"] = str(data.get("text") or "")[:8000]
    elif source == "github_repo_tree":
        preview["repo"] = data.get("repo")
        preview["url"] = data.get("url")
        preview["status"] = data.get("status")
        preview["text"] = str(data.get("text") or "")[:1200]
        preview["files"] = [
            {"path": item.get("path"), "type": item.get("type")}
            for item in list(data.get("files") or [])[:80]
            if isinstance(item, dict)
        ]
    elif source == "github_file_read":
        preview["repoUrl"] = data.get("repoUrl")
        preview["path"] = data.get("path")
        preview["text"] = str(data.get("text") or "")[:2500]
    elif source == "local_search":
        preview["matches"] = [
            {"path": item.get("path"), "line": item.get("line"), "excerpt": item.get("excerpt")}
            for item in list(data.get("matches") or [])[:5]
            if isinstance(item, dict)
        ]
    elif source == "run_cli":
        preview["stdout"] = str(data.get("stdout") or "")[:1200]
        preview["stderr"] = str(data.get("stderr") or "")[:600]
        preview["returncode"] = data.get("returncode")
    return preview


def _is_github_repo_url(url: str) -> bool:
    match = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", url)
    return bool(match and match.group(1) not in {"search", "topics", "marketplace"})


def _github_research_paths(tree_result: dict[str, Any]) -> list[str]:
    files = list((tree_result.get("data") or {}).get("files") or [])
    paths = [str(item.get("path") or "") for item in files if isinstance(item, dict)]
    priority: list[str] = []
    for path in paths:
        lowered = path.lower()
        if not lowered.endswith((".md", ".json", ".yaml", ".yml", ".toml")):
            continue
        if (
            "skill" in lowered
            or "tools" in lowered
            or "plugins" in lowered
            or "agents" in lowered
            or "mcp" in lowered
            or lowered in {"readme.md", "package.json"}
        ):
            priority.append(path)
    return list(dict.fromkeys(priority))


def _merge_workflow_response(
    response: dict[str, Any],
    run_id: str,
    prompt: str,
    started_at: str,
    react_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    response_json = response.get("responseJson") if isinstance(response.get("responseJson"), dict) else {}
    nodes = response.get("nodes") if isinstance(response.get("nodes"), list) else []
    events = response.get("events") if isinstance(response.get("events"), list) else []
    entry = {
        "id": "agent_turn_runtime",
        "label": "Agent Turn Runtime",
        "status": response.get("status", "succeeded"),
        "startedAt": started_at,
        "finishedAt": response.get("finishedAt") or datetime.now(UTC).isoformat(),
        "durationMs": 0,
        "stateSummary": "Delegated to workflow.",
    }
    return {
        **response,
        "id": response.get("id") or run_id,
        "prompt": prompt,
        "nodes": [entry, *nodes],
        "events": [
            {
                "id": f"{run_id}_evt_agent_turn_runtime",
                "nodeId": "agent_turn_runtime",
                "type": "node_end",
                "timestamp": datetime.now(UTC).isoformat(),
                "title": "Agent Turn Runtime",
                "detail": "Delegated to workflow.",
                "payload": {"reactSteps": react_steps},
            },
            *events,
        ],
        "responseJson": {
            **response_json,
            "agentRuntime": {"entry": "agent_turn_runtime"},
            "reactSteps": react_steps,
            "workflow": {"name": react_steps[-1].get("workflow"), "status": response.get("status", "succeeded")},
        },
    }


def _simple_failed_response(prompt: str, answer: str, started_at: str | None = None) -> dict:
    started_at = started_at or datetime.now(UTC).isoformat()
    timestamp = datetime.now(UTC).isoformat()
    latency_ms = _elapsed_ms(started_at, timestamp)
    return {
        "id": f"run_{uuid4().hex}",
        "mode": "real",
        "prompt": prompt,
        "status": "failed",
        "startedAt": started_at,
        "finishedAt": timestamp,
        "latencyMs": latency_ms,
        "nodes": [],
        "events": [],
        "toolCalls": [],
        "vectorMatches": [],
        "requestJson": {"prompt": prompt},
        "responseJson": {},
        "finalAnswer": answer,
    }


def _preview_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:600]
    return json.dumps(value, ensure_ascii=False, default=str)[:600]
