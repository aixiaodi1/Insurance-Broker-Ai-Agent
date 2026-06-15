from __future__ import annotations

from typing import Any

CHARS_PER_TOKEN_ZH = 2
CHARS_PER_TOKEN_EN = 4
IMAGE_TOKEN_SIZE = 2000
TOOL_EVENT_OVERHEAD = 50


def estimate_tokens(text: str) -> int:
    zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_count = len(text) - zh_count
    return max(1, zh_count // CHARS_PER_TOKEN_ZH + en_count // CHARS_PER_TOKEN_EN)


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        total += estimate_tokens(role) + estimate_tokens(str(content))
    return total


def estimate_tool_event_tokens(events: list[dict[str, Any]]) -> int:
    total = 0
    for event in events:
        total += TOOL_EVENT_OVERHEAD
        for key in ("input_summary", "output_summary"):
            val = event.get(key)
            if isinstance(val, dict):
                total += estimate_tokens(str(val))
            elif isinstance(val, str):
                total += estimate_tokens(val)
    return total


def format_tool_events_for_summary(events: list[dict[str, Any]]) -> str:
    if not events:
        return "(无工具事件)"
    lines: list[str] = []
    for ev in events:
        node = ev.get("node", "?")
        tool = ev.get("tool", "?")
        status = ev.get("status", "?")
        inp = ev.get("input_summary", {})
        out = ev.get("output_summary", {})
        inp_str = str(inp)[:200] if inp else ""
        out_str = str(out)[:300] if out else ""
        parts = [f"[{node}] {tool} ({status})"]
        if inp_str:
            parts.append(f"  入参: {inp_str}")
        if out_str:
            parts.append(f"  输出: {out_str}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)
