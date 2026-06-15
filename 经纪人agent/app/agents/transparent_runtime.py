from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.agents.bootstrap_context import AgentContextAssembler
from app.agents.transparent_planning import PLANNING_SYSTEM_PROMPT, PUBLIC_PLANNING_SCHEMA
from app.tools.registry import execute_tool, get_all_tool_specs


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict: ...


class TransparentAgentRuntime:
    def __init__(
        self,
        llm_client: LLMClient,
        project_root: Path | str,
        max_turns: int = 8,
    ) -> None:
        self.llm_client = llm_client
        self.project_root = Path(project_root)
        self.max_turns = max_turns
        self.context_assembler = AgentContextAssembler(project_root=self.project_root)

    def stream(self, message: str, thread_id: str | None = None, user_id: str = "default"):
        run_id = f"run_{uuid4().hex}"
        observations: list[dict[str, Any]] = []
        final_answer = ""

        yield self._event("run_started", run_id=run_id, summary="收到请求，开始装配上下文。")

        context = self.context_assembler.build()
        yield self._event(
            "context_loaded",
            run_id=run_id,
            summary="已加载本轮上下文、工具、sub-agent 和 provider 摘要。",
            context={
                "documents": {name: payload["status"] for name, payload in context["documents"].items()},
                "tool_count": len(context["tools"]),
                "sub_agent_count": len(context["sub_agents"]),
                "provider": context["provider"],
                "current_datetime": context["current_datetime"],
            },
        )

        planning = self._plan(message, context)
        intent = planning.get("intent_anchor", {})
        decomposition = planning.get("task_decomposition", {})
        yield self._event("intent_anchor", run_id=run_id, summary=str(intent.get("user_goal") or ""), intent=intent)
        yield self._event(
            "task_decomposition",
            run_id=run_id,
            summary=f"{len(decomposition.get('ordered_tasks', []) or [])} tasks planned.",
            task_decomposition=decomposition,
        )

        if planning.get("execution_mode") != "execute":
            final_answer = self._plan_only_answer(planning)
            yield self._event("final_answer", run_id=run_id, finalAnswer=final_answer, summary="计划模式已完成。")
            yield self._event("run_finished", run_id=run_id, run=self._run_payload(run_id, message, final_answer, planning, observations))
            return

        for turn in range(self.max_turns):
            response = self.llm_client.generate(
                self._react_prompt(message, planning, observations),
                system_prompt=self._react_system_prompt(context),
                tools=get_all_tool_specs(),
                tool_choice="auto",
            )
            tool_calls = response.get("tool_calls") or []
            if tool_calls:
                for tool_call in tool_calls:
                    function = tool_call.get("function") if isinstance(tool_call, dict) else None
                    if not isinstance(function, dict):
                        continue
                    tool_name = str(function.get("name") or "")
                    args = self._parse_arguments(function.get("arguments"))
                    yield self._event(
                        "tool_started",
                        run_id=run_id,
                        summary=f"正在执行工具：{tool_name}",
                        toolCall={"name": tool_name, "arguments": args, "status": "running"},
                    )
                    result = execute_tool(tool_name, args)
                    observation = {
                        "turn": turn + 1,
                        "tool": tool_name,
                        "arguments": args,
                        "ok": result.ok,
                        "data": result.data,
                        "error": result.error,
                    }
                    observations.append(observation)
                    yield self._event(
                        "tool_finished",
                        run_id=run_id,
                        summary=self._preview(result.data if result.ok else result.error),
                        toolCall={
                            "name": tool_name,
                            "arguments": args,
                            "status": "succeeded" if result.ok else "failed",
                            "resultPreview": self._preview(result.data),
                        },
                    )
                    yield self._event(
                        "observation",
                        run_id=run_id,
                        summary=f"{tool_name} returned {'ok' if result.ok else result.error}",
                        observation=observation,
                    )
                continue

            answer = str(response.get("answer") or "").strip()
            if answer:
                final_answer = answer
                yield self._event("final_answer", run_id=run_id, finalAnswer=final_answer, summary="最终回答已生成。")
                yield self._event("run_finished", run_id=run_id, run=self._run_payload(run_id, message, final_answer, planning, observations))
                return

        final_answer = "本轮已达到最大 ReAct 步数，尚未生成最终答案。"
        yield self._event("final_answer", run_id=run_id, finalAnswer=final_answer, summary="达到最大步骤。")
        yield self._event("run_finished", run_id=run_id, run=self._run_payload(run_id, message, final_answer, planning, observations, status="failed"))

    def _plan(self, message: str, context: dict[str, Any]) -> dict[str, Any]:
        response = self.llm_client.generate(
            self._planning_prompt(message, context),
            system_prompt=PLANNING_SYSTEM_PROMPT,
        )
        try:
            parsed = json.loads(str(response.get("answer") or ""))
        except json.JSONDecodeError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _planning_prompt(self, message: str, context: dict[str, Any]) -> str:
        return "\n\n".join(
            [
                "Build public intent anchoring and hypothesis-driven decomposition for this user message.",
                f"Schema:\n{json.dumps(PUBLIC_PLANNING_SCHEMA, ensure_ascii=False)}",
                f"Bootstrap context:\n{json.dumps(context, ensure_ascii=False, default=str)[:30000]}",
                f"User message:\n{message}",
            ]
        )

    def _react_system_prompt(self, context: dict[str, Any]) -> str:
        return "\n\n".join(
            [
                "You are a transparent ReAct agent. Use tools when needed, treat tool results as observations, and only answer when ready.",
                "Do not expose hidden chain-of-thought. Do expose concise public process summaries through the runtime events.",
                "IMPORTANT: Never expose internal error details, tool failures, or implementation diagnostics to the user. If a tool fails silently, try an alternative approach or provide a helpful response without mentioning the failure.",
                "Final answers must be user-friendly and helpful, never debugging information or error reports.",
                f"Bootstrap context:\n{json.dumps(context, ensure_ascii=False, default=str)[:30000]}",
            ]
        )

    def _react_prompt(self, message: str, planning: dict[str, Any], observations: list[dict[str, Any]]) -> str:
        return "\n\n".join(
            [
                f"User message:\n{message}",
                f"Public plan:\n{json.dumps(planning, ensure_ascii=False, default=str)}",
                f"Observations so far:\n{json.dumps(observations, ensure_ascii=False, default=str)}",
                "Return tool calls if more work is needed, otherwise return the final user-facing answer.",
            ]
        )

    @staticmethod
    def _parse_arguments(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _plan_only_answer(planning: dict[str, Any]) -> str:
        intent = planning.get("intent_anchor", {})
        tasks = (planning.get("task_decomposition", {}) or {}).get("ordered_tasks", [])
        lines = [
            "我先不执行工具，先给出本轮理解和任务拆解。",
            f"目标：{intent.get('user_goal', '')}",
            f"阻碍：{intent.get('real_blocker', '')}",
            "任务：",
        ]
        lines.extend(f"- {item.get('description', '')}" for item in tasks if isinstance(item, dict))
        return "\n".join(lines)

    @staticmethod
    def _event(event_type: str, **payload: Any) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }

    @staticmethod
    def _preview(value: Any) -> str:
        if isinstance(value, str):
            return value[:500]
        return json.dumps(value, ensure_ascii=False, default=str)[:500]

    @staticmethod
    def _run_payload(
        run_id: str,
        message: str,
        final_answer: str,
        planning: dict[str, Any],
        observations: list[dict[str, Any]],
        status: str = "succeeded",
    ) -> dict[str, Any]:
        return {
            "id": run_id,
            "mode": "real",
            "prompt": message,
            "status": status,
            "finalAnswer": final_answer,
            "responseJson": {
                "planning": planning,
                "observations": observations,
            },
        }
