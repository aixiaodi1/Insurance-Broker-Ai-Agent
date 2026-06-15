import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict
from uuid import uuid4

from app.services.conversation_memory import ConversationMemoryStore
from app.services.agent_tools import extract_cli_command, local_search, run_cli, web_search
from app.services.agent_runtime import AgentRuntime, load_agent_runtime
from app.services.prompt_registry import PromptRegistry, get_default_prompt_registry

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - dependency is declared for normal runtime.
    END = "__end__"
    StateGraph = None


class RagRunner(Protocol):
    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict: ...


class EvidenceRegistry(Protocol):
    def query(self, prompt: str) -> dict[str, Any]: ...


class PlannerGenerator(Protocol):
    def generate(self, prompt: str, system_prompt: str | None = None) -> dict: ...


class ResearchGraphState(TypedDict):
    prompt: str
    collection: str
    agent_id: str
    thread_id: str
    user_id: str
    collected_vars: dict
    resolved_prompt: NotRequired[str]
    session_id: NotRequired[str]
    messages: NotRequired[list[dict[str, Any]]]
    remembered_context: NotRequired[dict[str, Any]]
    memory_citations: NotRequired[list[dict[str, Any]]]
    route_plan: NotRequired[dict[str, Any]]
    evidence_registry_result: NotRequired[dict[str, Any]]
    response: NotRequired[dict[str, Any]]


class ResearchAgentGraph:
    def __init__(
        self,
        rag_query_service: RagRunner,
        evidence_source_registry: EvidenceRegistry | None = None,
        prompt_registry: PromptRegistry | None = None,
        planner_generator: PlannerGenerator | None = None,
        memory_store: ConversationMemoryStore | None = None,
        agent_runtime: AgentRuntime | None = None,
        local_source_root: Path | None = None,
        enable_web_search: bool = True,
    ) -> None:
        self._rag_query_service = rag_query_service
        self._evidence_source_registry = evidence_source_registry
        self._prompt_registry = prompt_registry or get_default_prompt_registry()
        self._planner_generator = planner_generator
        self._memory_store = memory_store
        self._agent_runtime = agent_runtime or load_agent_runtime()
        self._local_source_root = local_source_root or Path(".")
        self._enable_web_search = enable_web_search
        if self._memory_store is not None:
            self._memory_store.initialize()
        self._graph = self._build_graph()

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
        effective_thread_id = thread_id or f"{user_id}:{uuid4().hex}"
        state: ResearchGraphState = {
            "prompt": prompt,
            "collection": collection,
            "agent_id": agent_id,
            "thread_id": effective_thread_id,
            "user_id": user_id,
            "collected_vars": collected_vars or {},
            "resolved_prompt": prompt,
            "messages": [{"role": "user", "content": prompt}],
            "remembered_context": {},
            "memory_citations": [],
        }
        result = self._graph.invoke(state) if self._graph is not None else self._run_without_langgraph(state)
        return result["response"]

    def _build_graph(self):
        if StateGraph is None:
            return None
        graph = StateGraph(ResearchGraphState)
        graph.add_node("load_conversation_memory", self._load_conversation_memory)
        graph.add_node("entry_planner", self._entry_planner)
        graph.add_node("resolve_prompt_with_memory", self._resolve_prompt_with_memory)
        graph.add_node("direct_response", self._direct_response)
        graph.add_node("load_evidence_sources", self._load_evidence_sources)
        graph.add_node("run_existing_rag_flow", self._run_existing_flow)
        graph.add_node("save_conversation_memory", self._save_conversation_memory)
        graph.set_entry_point("load_conversation_memory")
        graph.add_edge("load_conversation_memory", "entry_planner")
        graph.add_conditional_edges(
            "entry_planner",
            _route_after_planner,
            {
                "direct_response": "direct_response",
                "load_evidence_sources": "resolve_prompt_with_memory",
            },
        )
        graph.add_edge("resolve_prompt_with_memory", "load_evidence_sources")
        graph.add_edge("direct_response", "save_conversation_memory")
        graph.add_edge("load_evidence_sources", "run_existing_rag_flow")
        graph.add_edge("run_existing_rag_flow", "save_conversation_memory")
        graph.add_edge("save_conversation_memory", END)
        return graph.compile()

    def _run_without_langgraph(self, state: ResearchGraphState) -> ResearchGraphState:
        state = self._load_conversation_memory(state)
        state = self._entry_planner(state)
        if _route_after_planner(state) == "direct_response":
            return self._save_conversation_memory(self._direct_response(state))
        state = self._resolve_prompt_with_memory(state)
        state = self._load_evidence_sources(state)
        return self._save_conversation_memory(self._run_existing_flow(state))

    def _load_conversation_memory(self, state: ResearchGraphState) -> ResearchGraphState:
        if self._memory_store is None:
            return state
        remembered_context = self._memory_store.recall_memory(
            user_id=state["user_id"],
            thread_id=state["thread_id"],
            query=state["prompt"],
        )
        recent_messages = remembered_context.get("recent_messages") or []
        session_id = self._memory_store.create_session(
            user_id=state["user_id"],
            thread_id=state["thread_id"],
            title=state["prompt"][:40] or "conversation",
            task_type="conversation",
        )
        self._memory_store.add_message(session_id=session_id, role="user", content=state["prompt"])
        return {
            **state,
            "session_id": session_id,
            "remembered_context": remembered_context,
            "memory_citations": remembered_context.get("citations", []),
            "messages": [
                {"role": item["role"], "content": item["content"]}
                for item in recent_messages
            ]
            + [{"role": "user", "content": state["prompt"]}],
        }

    def _entry_planner(self, state: ResearchGraphState) -> ResearchGraphState:
        command = extract_cli_command(state["prompt"])
        if command is not None:
            return {
                **state,
                "route_plan": {
                    "route": "cli_tool",
                    "confidence": 1.0,
                    "reason": "User explicitly requested a CLI command.",
                    "tasks": ["run_cli"],
                    "command": command,
                },
            }
        plan = self._plan_route(state["prompt"])
        return {**state, "route_plan": plan}

    def _direct_response(self, state: ResearchGraphState) -> ResearchGraphState:
        plan = state.get("route_plan") or _fallback_route_plan()
        if plan.get("route") == "cli_tool":
            result = run_cli(
                str(plan.get("command") or ""),
                self._local_source_root,
                mode=str(state.get("collected_vars", {}).get("commandMode") or "plan"),
                approved=bool(state.get("collected_vars", {}).get("commandApproved")),
            )
            output = str((result.get("data") or {}).get("stdout") or (result.get("data") or {}).get("stderr") or "").strip()
            if result.get("error") == "human_approval_required":
                response = _build_direct_response(
                    prompt=state["prompt"],
                    collection=state["collection"],
                    agent_id=state["agent_id"],
                    thread_id=state["thread_id"],
                    user_id=state["user_id"],
                    plan=plan,
                    final_answer="Command approval is required before I run this.",
                    status="awaiting_approval",
                    approval_request=(result.get("data") or {}).get("approvalRequest"),
                )
                response = _decorate_response_with_tool_result(response, "run_cli", result, {"command": plan.get("command")})
                return {**state, "response": response}
            final_answer = (
                f"命令执行结果：\n{output or '命令执行完成，但没有输出。'}"
                if result.get("ok")
                else f"命令没有执行：{result.get('error')}。这条命令没有通过当前权限策略。"
            )
            response = _build_direct_response(
                prompt=state["prompt"],
                collection=state["collection"],
                agent_id=state["agent_id"],
                thread_id=state["thread_id"],
                user_id=state["user_id"],
                plan=plan,
                final_answer=final_answer,
            )
            response = _decorate_response_with_tool_result(response, "run_cli", result, {"command": plan.get("command")})
            return {**state, "response": response}
        if plan.get("route") == "capability_answer":
            capability = self._agent_runtime.capability_answer(state["prompt"])
            response = _build_direct_response(
                prompt=state["prompt"],
                collection=state["collection"],
                agent_id=state["agent_id"],
                thread_id=state["thread_id"],
                user_id=state["user_id"],
                plan=plan,
                final_answer=str(capability.get("answer") or ""),
                extra_response_json={"capabilities": capability},
            )
            return {**state, "response": response}
        final_answer = self._direct_answer_from_plan(plan)
        response = _build_direct_response(
            prompt=state["prompt"],
            collection=state["collection"],
            agent_id=state["agent_id"],
            thread_id=state["thread_id"],
            user_id=state["user_id"],
            plan=plan,
            final_answer=final_answer,
        )
        return {**state, "response": response}

    def _plan_route(self, prompt: str) -> dict[str, Any]:
        if self._planner_generator is None:
            return _fallback_route_plan()
        rendered = self._prompt_registry.render("entry_planner", query=prompt)
        try:
            result = self._planner_generator.generate(rendered.user, system_prompt=rendered.system)
            parsed = _extract_json_object(str(result.get("answer", "")))
            if parsed is None:
                return _fallback_route_plan()
            return _normalize_route_plan(parsed)
        except Exception:
            return _fallback_route_plan()

    def _direct_answer_from_plan(self, plan: dict[str, Any]) -> str:
        if plan.get("route") == "clarify" and plan.get("clarifying_question"):
            return str(plan["clarifying_question"])
        answer_key = plan.get("answer_key")
        if answer_key in {"meta_identity", "boundary_response"}:
            return self._prompt_registry.render(str(answer_key)).user
        if plan.get("route") == "out_of_scope":
            return self._prompt_registry.render("boundary_response").user
        return self._prompt_registry.render("meta_identity").user

    def _resolve_prompt_with_memory(self, state: ResearchGraphState) -> ResearchGraphState:
        remembered_context = state.get("remembered_context") or {}
        if not _looks_like_followup(state["prompt"]) or not remembered_context:
            return {**state, "resolved_prompt": state["prompt"]}
        context_text = _render_memory_context(remembered_context)
        if not context_text:
            return {**state, "resolved_prompt": state["prompt"]}
        resolved_prompt = f"Context from previous turns: {context_text}\nCurrent question: {state['prompt']}"
        return {**state, "resolved_prompt": resolved_prompt}

    def _load_evidence_sources(self, state: ResearchGraphState) -> ResearchGraphState:
        if self._evidence_source_registry is None:
            return state
        evidence = self._evidence_source_registry.query(state.get("resolved_prompt") or state["prompt"])
        return {**state, "evidence_registry_result": evidence}

    def _run_existing_flow(self, state: ResearchGraphState) -> ResearchGraphState:
        rag_prompt = state.get("resolved_prompt") or state["prompt"]
        response = self._rag_query_service.run(
            prompt=rag_prompt,
            collection=state["collection"],
            agent_id=state["agent_id"],
            thread_id=state["thread_id"],
            user_id=state["user_id"],
            collected_vars=state["collected_vars"],
        )
        if state.get("evidence_registry_result"):
            response = _decorate_response_with_evidence_registry(
                response,
                state["evidence_registry_result"],
            )
        if _is_empty_rag_response(response):
            response = _decorate_response_with_source_fallback(
                response,
                query=state.get("resolved_prompt") or state["prompt"],
                local_source_root=self._local_source_root,
                enable_web_search=self._enable_web_search,
            )
        response = _restore_public_prompt(response, state)
        return {**state, "response": response}

    def _save_conversation_memory(self, state: ResearchGraphState) -> ResearchGraphState:
        response = _decorate_response_with_memory(state["response"], state)
        if self._memory_store is None or not state.get("session_id"):
            return {**state, "response": response}

        final_answer = str(response.get("finalAnswer") or "")
        if final_answer:
            self._memory_store.add_message(
                session_id=state["session_id"],
                role="assistant",
                content=final_answer,
            )
        self._memory_store.upsert_thread_summary(
            user_id=state["user_id"],
            thread_id=state["thread_id"],
            summary=_summarize_conversation_state(state, final_answer),
            latest_session_id=state["session_id"],
            final_answer=final_answer,
        )
        return {**state, "response": response}


def _route_after_planner(state: ResearchGraphState) -> str:
    route = (state.get("route_plan") or {}).get("route")
    if route in {"direct_answer", "capability_answer", "clarify", "out_of_scope", "cli_tool"}:
        return "direct_response"
    return "load_evidence_sources"


def _looks_like_followup(prompt: str) -> bool:
    lowered = prompt.lower()
    followup_markers = [
        "continue",
        "previous",
        "same",
        "that product",
        "刚才",
        "继续",
        "上面",
        "之前",
        "这个产品",
        "那个产品",
        "它",
    ]
    return any(marker in lowered for marker in followup_markers)


def _render_memory_context(remembered_context: dict[str, Any]) -> str:
    parts: list[str] = []
    thread_summary = remembered_context.get("thread_summary")
    if isinstance(thread_summary, dict) and thread_summary.get("summary"):
        parts.append(str(thread_summary["summary"]))
    for item in remembered_context.get("recent_messages") or []:
        if isinstance(item, dict) and item.get("content"):
            parts.append(f"{item.get('role', 'message')}: {item['content']}")
    return " | ".join(parts[:8])


def _summarize_conversation_state(state: ResearchGraphState, final_answer: str) -> str:
    resolved_prompt = state.get("resolved_prompt") or state["prompt"]
    if resolved_prompt != state["prompt"]:
        return f"Resolved prompt: {resolved_prompt[:500]}; latest answer: {final_answer[:500]}"
    return f"Latest question: {state['prompt'][:500]}; latest answer: {final_answer[:500]}"


def _restore_public_prompt(response: dict[str, Any], state: ResearchGraphState) -> dict[str, Any]:
    request_json = response.get("requestJson") if isinstance(response.get("requestJson"), dict) else {}
    return {
        **response,
        "prompt": state["prompt"],
        "requestJson": {
            **request_json,
            "prompt": state["prompt"],
            "threadId": state["thread_id"],
        },
    }


def _decorate_response_with_memory(response: dict[str, Any], state: ResearchGraphState) -> dict[str, Any]:
    response_json = response.get("responseJson") if isinstance(response.get("responseJson"), dict) else {}
    memory_payload = {
        "resolvedPrompt": state.get("resolved_prompt") or state["prompt"],
        "rememberedContext": state.get("remembered_context") or {},
        "memoryCitations": state.get("memory_citations") or [],
    }
    request_json = response.get("requestJson") if isinstance(response.get("requestJson"), dict) else {}
    return {
        **response,
        "prompt": state["prompt"],
        "requestJson": {
            **request_json,
            "prompt": state["prompt"],
            "threadId": state["thread_id"],
        },
        "responseJson": {
            **response_json,
            "memory": memory_payload,
        },
    }


def _fallback_route_plan() -> dict[str, Any]:
    return {
        "route": "clarify",
        "confidence": 0.0,
        "reason": "入口规划器未返回可用结果。",
        "tasks": [],
        "answer_key": None,
        "needs_user_input": True,
        "clarifying_question": "请告诉我你想研究的保险产品、条款问题、理赔场景，或上传需要分析的资料。",
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```", r"(\{.*\})"]:
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_route_plan(raw: dict[str, Any]) -> dict[str, Any]:
    allowed_routes = {
        "direct_answer",
        "capability_answer",
        "insurance_research",
        "claim_analysis",
        "document_review",
        "clarify",
        "out_of_scope",
    }
    route = raw.get("route")
    if route not in allowed_routes:
        return _fallback_route_plan()
    tasks = raw.get("tasks")
    return {
        "route": route,
        "confidence": float(raw.get("confidence") or 0.0),
        "reason": str(raw.get("reason") or ""),
        "tasks": [str(item) for item in tasks] if isinstance(tasks, list) else [],
        "answer_key": raw.get("answer_key") if raw.get("answer_key") in {"meta_identity", "boundary_response"} else None,
        "needs_user_input": bool(raw.get("needs_user_input", False)),
        "clarifying_question": raw.get("clarifying_question") if isinstance(raw.get("clarifying_question"), str) else None,
    }


def _build_direct_response(
    prompt: str,
    collection: str,
    agent_id: str,
    thread_id: str | None,
    user_id: str,
    plan: dict[str, Any],
    final_answer: str,
    status: str = "succeeded",
    approval_request: dict[str, Any] | None = None,
    extra_response_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = f"run_{uuid4().hex}"
    timestamp = datetime.now(UTC).isoformat()
    node = {
        "id": "entry_planner",
        "label": "入口规划",
        "status": status,
        "startedAt": timestamp,
        "finishedAt": timestamp,
        "durationMs": 0,
        "stateSummary": f"LLM Planner 路由为 {plan.get('route')}，未进入知识库检索。",
    }
    event = {
        "id": f"{run_id}_evt_entry_planner",
        "nodeId": "entry_planner",
        "type": "node_end",
        "timestamp": timestamp,
        "title": "入口规划",
        "detail": str(plan.get("reason") or "LLM Planner 决定直接回复。"),
        "payload": {"routePlan": plan, "requiresKnowledgeBase": False},
    }
    return {
        "id": run_id,
        "mode": "real",
        "prompt": prompt,
        "status": status,
        "startedAt": timestamp,
        "finishedAt": timestamp,
        "latencyMs": 0,
        "nodes": [node],
        "events": [event],
        "toolCalls": [],
        "vectorMatches": [],
        "requestJson": {
            "prompt": prompt,
            "agentId": agent_id,
            "threadId": thread_id,
            "collection": collection,
            "userId": user_id,
        },
        "responseJson": {
            "routePlan": plan,
            "requiresKnowledgeBase": False,
            "route": "direct_response",
            **(extra_response_json or {}),
        },
        "finalAnswer": final_answer,
        **({"approvalRequest": approval_request} if approval_request else {}),
    }


def _decorate_response_with_evidence_registry(
    response: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    timestamp = response.get("startedAt") or datetime.now(UTC).isoformat()
    run_id = str(response.get("id") or "run")
    node_id = "load_evidence_sources"
    company_count = len(evidence.get("companyMatches") or [])
    material_count = len(evidence.get("materialMatches") or [])
    detail = evidence.get("summary") or (
        f"Matched {company_count} company source entries and {material_count} official material candidates."
    )
    node = {
        "id": node_id,
        "label": "Load evidence sources",
        "status": "succeeded",
        "startedAt": timestamp,
        "finishedAt": timestamp,
        "durationMs": 0,
        "stateSummary": detail,
    }
    event = {
        "id": f"{run_id}_evt_{node_id}",
        "nodeId": node_id,
        "type": "tool_call",
        "timestamp": timestamp,
        "title": "Load evidence sources",
        "detail": detail,
        "payload": evidence,
    }
    tool_call = {
        "id": f"{run_id}_tool_source_registry_lookup",
        "nodeId": node_id,
        "name": "source_registry_lookup",
        "status": "succeeded",
        "arguments": {"prompt": response.get("prompt", "")},
        "durationMs": 0,
        "resultPreview": detail,
    }
    response_json = {
        **(response.get("responseJson") if isinstance(response.get("responseJson"), dict) else {}),
        "evidenceSourceRegistry": evidence,
    }
    return {
        **response,
        "nodes": [node, *(response.get("nodes") or [])],
        "events": [event, *(response.get("events") or [])],
        "toolCalls": [tool_call, *(response.get("toolCalls") or [])],
        "responseJson": response_json,
    }


def _is_empty_rag_response(response: dict[str, Any]) -> bool:
    final_answer = str(response.get("finalAnswer") or "")
    insufficient_markers = (
        "知识库中没有足够依据",
        "知识库没有足够依据",
        "未包含",
        "未涉及",
        "无法帮您查找",
        "无法查询",
        "建议您直接",
        "建议你直接",
        "提供该产品",
        "上传后",
    )
    return any(marker in final_answer for marker in insufficient_markers)


def _decorate_response_with_source_fallback(
    response: dict[str, Any],
    query: str,
    local_source_root: Path,
    enable_web_search: bool,
) -> dict[str, Any]:
    local_result = local_search(query, local_source_root)
    matches = list((local_result.get("data") or {}).get("matches") or [])
    response = _decorate_response_with_tool_result(response, "local_search", local_result, {"query": query})
    if matches:
        lines = [
            "知识库暂时没有命中，但我从本地文件找到了这些线索：",
            *[
                f"- {item.get('excerpt', '').strip()}（来源: {item.get('path')}）"
                for item in matches[:5]
                if item.get("excerpt") or item.get("path")
            ],
        ]
        vector_matches = [
            {
                "id": f"local_{index + 1}",
                "nodeId": "local_search",
                "provider": "chroma",
                "collection": "local-files",
                "title": Path(str(item.get("path") or f"local_{index + 1}")).name,
                "contentPreview": str(item.get("excerpt") or ""),
                "metadata": {"path": item.get("path"), "line": item.get("line"), "source": "local_search"},
            }
            for index, item in enumerate(matches[:5])
        ]
        return {
            **response,
            "finalAnswer": "\n".join(lines),
            "vectorMatches": [*vector_matches, *(response.get("vectorMatches") or [])],
            "responseJson": {
                **(response.get("responseJson") if isinstance(response.get("responseJson"), dict) else {}),
                "sourceFallback": {"localMatches": matches[:5]},
            },
        }

    if not enable_web_search:
        return response

    web_result = web_search(query)
    response = _decorate_response_with_tool_result(response, "web_search", web_result, {"query": query})
    results = list((web_result.get("data") or {}).get("results") or [])
    if not results:
        return response

    final_answer = "\n".join(
        [
            "知识库暂时没有命中，但我联网找到这些可继续核验的线索：",
            *[f"- {item.get('title') or item.get('url')}（{item.get('url')}）" for item in results[:3]],
        ]
    )
    return {
        **response,
        "finalAnswer": final_answer,
        "responseJson": {
            **(response.get("responseJson") if isinstance(response.get("responseJson"), dict) else {}),
            "sourceFallback": {"webResults": results[:3]},
        },
    }


def _decorate_response_with_tool_result(
    response: dict[str, Any],
    tool_name: str,
    result: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    timestamp = response.get("startedAt") or datetime.now(UTC).isoformat()
    run_id = str(response.get("id") or "run")
    node_id = tool_name
    status = "succeeded" if result.get("ok") else ("pending" if result.get("error") == "human_approval_required" else "failed")
    detail = _preview((result.get("data") or {}).get("stdout") or result.get("data") or result.get("error") or "")
    node = {
        "id": node_id,
        "label": tool_name,
        "status": status,
        "startedAt": timestamp,
        "finishedAt": timestamp,
        "durationMs": 0,
        "stateSummary": detail,
    }
    event = {
        "id": f"{run_id}_evt_{node_id}",
        "nodeId": node_id,
        "type": "tool_call",
        "timestamp": timestamp,
        "title": tool_name,
        "detail": detail,
        "payload": result,
    }
    tool_call = {
        "id": f"{run_id}_tool_{node_id}",
        "nodeId": node_id,
        "name": tool_name,
        "status": status,
        "arguments": arguments,
        "durationMs": 0,
        "resultPreview": detail,
    }
    return {
        **response,
        "nodes": [*(response.get("nodes") or []), node],
        "events": [*(response.get("events") or []), event],
        "toolCalls": [*(response.get("toolCalls") or []), tool_call],
    }


def _preview(value: Any) -> str:
    if isinstance(value, str):
        return value[:600]
    return json.dumps(value, ensure_ascii=False, default=str)[:600]
