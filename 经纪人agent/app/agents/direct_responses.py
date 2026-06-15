from __future__ import annotations

from typing import Any

from app.tools.agent_tools import run_cli


def generate_direct_response(state: dict[str, Any]) -> dict[str, Any]:
    task_type = state.get("task_type")
    if task_type == "identity":
        state["final_summary"] = _assistant_identity()
    elif task_type == "memory_lookup":
        state["final_summary"] = _memory_lookup_response(state)
    elif task_type == "clarification":
        state["final_summary"] = _clarification_response()
    elif task_type == "cli_tool":
        state["final_summary"] = _cli_response(state)
    else:
        state["final_summary"] = _chat_response()
    return state


def _assistant_identity() -> str:
    return (
        "我是保险产品研究 Agent，主要帮你查保险产品的官方资料、条款、赔付、免责、等待期和产品对比。"
        "涉及保险、金融、法律或医疗结论时，我会优先说明来源、证据等级和不确定性。"
    )


def _memory_lookup_response(state: dict[str, Any]) -> str:
    text = state.get("user_input") or ""
    if not state.get("thread_id_provided"):
        return (
            "这次请求没有传 thread_id，我会把它当作新线程处理；因此不能可靠判断上一句话。"
            "请带上同一个 thread_id 再问，我就能按该线程召回上下文。"
        )

    if "上一句" in text or "上句话" in text or "previous" in text.lower():
        previous = _previous_user_message(state)
        if previous is None:
            return "我在这个 thread_id 下还没有找到上一轮用户消息，所以不能编造上一句话。"
        _append_memory_citation(state, previous)
        return f"你上一句话是：{previous}"

    if "我是谁" in text or "who am i" in text.lower():
        facts = (state.get("remembered_context") or {}).get("facts") or []
        if not facts:
            return "我现在没有足够的已保存身份信息来判断你是谁；我不会编造你的身份。"
        labels = ", ".join(item.get("key", "") for item in facts if item.get("key"))
        return f"我能确认的已保存信息包括：{labels or '暂无可读身份字段'}。"

    remembered = state.get("remembered_context") or {}
    citations = remembered.get("citations") or []
    if not citations:
        return "我没有在当前 thread_id 和用户记忆里找到可引用的相关记忆。"
    labels = "；".join(item.get("label", "") for item in citations[:3] if item.get("label"))
    return f"我找到了这些可引用的记忆线索：{labels}"


def _clarification_response() -> str:
    return "请告诉我要查的保险产品名称？"


def _chat_response() -> str:
    return "我在。这个问题不需要进入保险研究链路；如果你要查保险产品，请给我产品名或具体条款问题。"


def _cli_response(state: dict[str, Any]) -> str:
    command = state.get("requested_command") or ""
    result = run_cli(command)
    state.setdefault("tool_events", []).append(
        {
            "node": "direct_response",
            "tool": "run_cli",
            "status": "success" if result.ok else "fail",
            "input_summary": {"command": command},
            "output_summary": result.data,
            "error": result.error,
        }
    )
    if not result.ok:
        return f"命令没有执行：{result.error}。当前只允许 rg、dir、ls、Get-ChildItem 这类读取命令。"
    stdout = (result.data.get("stdout") or "").strip()
    stderr = (result.data.get("stderr") or "").strip()
    output = stdout or stderr or "命令执行完成，但没有输出。"
    return f"命令执行结果：\n{output}"


def _previous_user_message(state: dict[str, Any]) -> str | None:
    messages = list(state.get("messages") or [])
    current_input = state.get("user_input")
    if messages and messages[-1].get("content") == current_input:
        messages = messages[:-1]
    for message in reversed(messages):
        if message.get("role") == "user" and message.get("content"):
            return str(message["content"])
    return None


def _append_memory_citation(state: dict[str, Any], content: str) -> None:
    citations = list(state.get("memory_citations") or [])
    citations.append({"source": "message", "id": "recent_thread_message", "label": content[:80]})
    state["memory_citations"] = citations
