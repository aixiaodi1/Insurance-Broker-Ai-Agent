from __future__ import annotations

import json
from typing import Any

from app.tools.registry import execute_node_tool, get_node_tool_specs


RESEARCH_TERMS = (
    "官方",
    "资料",
    "条款",
    "赔付",
    "理赔",
    "免责",
    "等待期",
    "产品对比",
    "对比",
    "保什么",
    "瀹樻柟",
    "official",
    "terms",
    "coverage",
    "claim",
    "exclusion",
    "waiting period",
    "compare",
)

LOOKUP_TERMS = (
    "查",
    "查询",
    "鏌",
    "lookup",
    "search",
    "look up",
)

TRIAGE_TERMS = LOOKUP_TERMS + (
    "look",
    "check",
    "investigate",
    "\u770b",
    "\u770b\u770b",
    "\u5e2e\u6211\u770b",
)

KNOWN_PRODUCT_TERMS = (
    "众民保",
    "浼楁皯淇",
)

INSURANCE_TERMS = (
    "保险",
    "险",
    "保单",
    "保费",
    "重疾",
    "医疗",
    "寿险",
    "annuity",
    "insurance",
    "policy",
)

ASSISTANT_IDENTITY_TERMS = (
    "你是谁",
    "你是什么",
    "介绍一下你",
    "who are you",
)

MEMORY_TERMS = (
    "我是谁",
    "上一句",
    "上句话",
    "刚才说",
    "前面说",
    "记得我",
    "记忆",
    "previous",
    "who am i",
)

CLI_PREFIXES = (
    "运行命令",
    "执行命令",
    "run command",
    "cli:",
)


def route_user_intent(state: dict[str, Any], router_model: Any | None = None) -> dict[str, Any]:
    text = (state.get("user_input") or "").strip()
    lowered = text.lower()
    command = _extract_cli_command(text)
    if command is not None:
        state["requested_command"] = command
        return _set_route(state, "cli_tool", "explicit_cli_command")

    if _contains(lowered, ASSISTANT_IDENTITY_TERMS):
        return _set_route(state, "identity", "assistant_identity_question")

    if _contains(lowered, MEMORY_TERMS):
        return _set_route(state, "memory_lookup", "memory_or_history_question")

    if _is_research_request(lowered):
        return _set_route(state, "official_evidence_research", "explicit_insurance_research")

    if _contains(lowered, INSURANCE_TERMS):
        return _set_route(state, "clarification", "insurance_request_missing_product_or_question")

    if _should_probe_with_global_tools(lowered):
        if router_model is not None:
            model_probed = _probe_with_router_model(state, text, router_model)
            if model_probed:
                return model_probed
        probed = _probe_local_insurance_clue(state, text)
        if probed:
            return probed

    return _set_route(state, "chat", "non_research_conversation")


def _is_research_request(text: str) -> bool:
    if _contains(text, RESEARCH_TERMS):
        return True
    has_lookup_intent = _contains(text, LOOKUP_TERMS)
    return has_lookup_intent and (
        _contains(text, INSURANCE_TERMS) or _contains(text, KNOWN_PRODUCT_TERMS)
    )


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


def _set_route(state: dict[str, Any], task_type: str, reason: str) -> dict[str, Any]:
    state["task_type"] = task_type
    state["route_reason"] = reason
    return state


def _should_probe_with_global_tools(text: str) -> bool:
    return _contains(text, TRIAGE_TERMS)


def _probe_local_insurance_clue(state: dict[str, Any], query: str) -> dict[str, Any] | None:
    search_result = execute_node_tool(
        "global_router",
        "local_search",
        {"query": query, "limit": 3},
    )
    state.setdefault("tool_events", []).append(
        {
            "node": "global_router",
            "tool": "local_search",
            "status": "success" if search_result.ok else "fail",
            "input_summary": {"query": query},
            "output_summary": search_result.data,
            "error": search_result.error,
        }
    )
    if not search_result.ok:
        return None

    matches = search_result.data.get("matches", [])
    if not _matches_insurance_clue(matches):
        return None
    state["global_route_observations"] = matches
    return _set_route(state, "official_evidence_research", "global_router_local_insurance_clue")


def _probe_with_router_model(state: dict[str, Any], query: str, router_model: Any) -> dict[str, Any] | None:
    response = router_model.generate(
        query,
        system_prompt=(
            "You are a safe global router. Decide whether a user request may be an insurance product "
            "research task. You may only call the provided tools. Do not answer the user."
        ),
        tools=get_node_tool_specs("global_router"),
        tool_choice="auto",
    )
    for tool_call in response.get("tool_calls", []):
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if not isinstance(function, dict):
            continue
        tool_name = str(function.get("name") or "")
        arguments = _parse_tool_arguments(function.get("arguments"))
        result = execute_node_tool("global_router", tool_name, arguments)
        state.setdefault("tool_events", []).append(
            {
                "node": "global_router",
                "tool": tool_name,
                "status": "success" if result.ok else "fail",
                "input_summary": arguments,
                "output_summary": result.data,
                "error": result.error,
            }
        )
        if result.ok and _matches_insurance_clue(result.data.get("matches", [])):
            state["global_route_observations"] = result.data.get("matches", [])
            return _set_route(state, "official_evidence_research", "global_router_model_tool_clue")
    return None


def _parse_tool_arguments(raw_arguments: object) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str) or not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _matches_insurance_clue(matches: list[dict[str, Any]]) -> bool:
    for match in matches:
        text = f"{match.get('path', '')} {match.get('excerpt', '')}".lower()
        if _contains(text, INSURANCE_TERMS) or _contains(text, RESEARCH_TERMS):
            return True
    return False


def _extract_cli_command(text: str) -> str | None:
    stripped = text.strip()
    lowered = stripped.lower()
    for prefix in CLI_PREFIXES:
        if lowered.startswith(prefix.lower()):
            command = stripped[len(prefix):].strip(" ：:")
            return command or None
    return None
