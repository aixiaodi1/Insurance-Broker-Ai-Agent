from __future__ import annotations

from typing import Any

from app.agents.compact.engine import ContextEngine
from app.agents.compact.prompts import (
    format_compact_summary,
    get_compact_prompt,
    get_iterative_compact_prompt,
)
from app.agents.compact.token_counter import (
    estimate_tokens,
    estimate_tool_event_tokens,
    format_tool_events_for_summary,
)
from app.config import settings

_COMPACT_INPUT_MAX_CHARS = 20000
_TOOL_RESULT_CLEARED = "[旧工具结果内容已清除]"


class ContextCompressor(ContextEngine):
    def __init__(
        self,
        threshold_percent: float = 0.50,
        protect_first_n: int = 3,
        protect_last_n_token_budget: float = 0.25,
        max_consecutive_failures: int = 3,
        max_ineffective_count: int = 2,
    ):
        self.threshold_percent = threshold_percent
        self.protect_first_n = protect_first_n
        self.protect_last_n_token_budget = protect_last_n_token_budget
        self.max_consecutive_failures = max_consecutive_failures
        self.max_ineffective_count = max_ineffective_count
        self.compression_count = 0
        self._consecutive_failures = 0
        self._ineffective_count = 0

    @property
    def name(self) -> str:
        return "hermes_compressor"

    def should_compress(self, state: dict[str, Any]) -> bool:
        budget = _get_budget(state)
        messages = state.get("messages", [])
        tool_events = state.get("tool_events", [])
        return len(messages) > budget["max_messages"] or len(tool_events) > budget["max_tool_events"]

    def update_from_response(self, usage: dict[str, Any]) -> None:
        self.compression_count += 1

    def on_session_reset(self) -> None:
        self._consecutive_failures = 0
        self._ineffective_count = 0

    def compress(
        self, state: dict[str, Any], llm_client: Any = None
    ) -> dict[str, Any]:
        if not self.should_compress(state):
            return dict(state)

        state = dict(state)
        budget = _get_budget(state)
        max_messages = budget["max_messages"]
        max_tool_events = budget["max_tool_events"]
        max_chars = budget["compact_input_max_chars"]

        messages = list(state.get("messages", []))
        tool_events = list(state.get("tool_events", []))
        conversation_summary = state.get("conversation_summary")

        # Hermes Stage 1: prune tool events (cheap, always runs)
        if len(tool_events) > max_tool_events:
            state["tool_events_summary"] = _create_tool_events_rollup(
                tool_events, max_tool_events
            )
            state["tool_events"] = tool_events[-max_tool_events:]

        # Hermes Stage 2: message compression with anti-thrashing
        if len(messages) > max_messages:
            old = messages[:-max_messages]
            recent = messages[-max_messages:]

            # Hermes anti-thrashing: skip LLM if recent compressions were ineffective
            should_use_llm = (
                llm_client is not None
                and self._consecutive_failures < self.max_consecutive_failures
                and self._ineffective_count < self.max_ineffective_count
            )

            if should_use_llm:
                summary = self._summarize_with_llm(
                    old, conversation_summary, max_chars, llm_client
                )
                if summary is not None:
                    self._consecutive_failures = 0
                    savings = len(messages) - max_messages
                    if savings <= 2:
                        self._ineffective_count += 1
                    else:
                        self._ineffective_count = 0
                    state["messages"] = recent
                    state["conversation_summary"] = summary
                else:
                    self._consecutive_failures += 1
                    truncated = _truncate_messages(
                        messages, max_messages, conversation_summary
                    )
                    state["messages"] = truncated[0]
                    state["conversation_summary"] = truncated[1]
            else:
                truncated = _truncate_messages(
                    messages, max_messages, conversation_summary
                )
                state["messages"] = truncated[0]
                state["conversation_summary"] = truncated[1]

        return state

    def _summarize_with_llm(
        self,
        old_messages: list[dict[str, Any]],
        existing_summary: str | None,
        max_chars: int,
        llm_client: Any,
    ) -> str | None:
        formatted = _format_messages_for_summary(old_messages, max_chars)
        if not formatted.strip():
            return None

        prompt_parts = [f"以下是需要摘要的对话历史：\n\n{formatted}"]

        # Hermes iterative update: include existing summary for merging
        if existing_summary:
            prompt_parts.append(
                f"\n\n已有的前期摘要（请合并进新摘要）：\n{existing_summary}"
            )
            system_prompt = get_iterative_compact_prompt()
        else:
            system_prompt = get_compact_prompt()

        try:
            result = llm_client.generate(
                prompt="\n".join(prompt_parts),
                system_prompt=system_prompt,
            )
            raw = str(result.get("answer", ""))
            if not raw.strip():
                return None
            return format_compact_summary(raw)
        except Exception:
            return None


# ── Hermes-style compact context ──
# module-level singleton for backward compatibility (graph nodes, tests)

_compressor: ContextCompressor | None = None

# Exposed for tests
MAX_CONSECUTIVE_FAILURES: int = settings.compact_max_consecutive_failures


def get_compressor() -> ContextCompressor:
    global _compressor
    if _compressor is None:
        _compressor = ContextCompressor(
            max_consecutive_failures=MAX_CONSECUTIVE_FAILURES,
        )
    return _compressor


def compact_context(
    state: dict[str, Any], llm_client: Any = None
) -> dict[str, Any]:
    return get_compressor().compress(state, llm_client=llm_client)


def reset_compact_failures() -> None:
    get_compressor().on_session_reset()


# ── internal helpers ──


def _get_budget(state: dict[str, Any]) -> dict[str, int]:
    budget = state.get("context_budget") or {}
    return {
        "max_messages": int(
            budget.get("max_messages", settings.compact_max_messages)
        ),
        "max_tool_events": int(
            budget.get("max_tool_events", settings.compact_max_tool_events)
        ),
        "compact_input_max_chars": int(
            budget.get(
                "compact_input_max_chars", settings.compact_input_max_chars
            )
        ),
    }


def _truncate_messages(
    messages: list[dict[str, Any]],
    max_messages: int,
    existing_summary: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    if len(messages) <= max_messages:
        return messages, existing_summary

    old = messages[:-max_messages]
    recent = messages[-max_messages:]
    old_text = " | ".join(str(m.get("content", "")) for m in old)
    new_summary = (
        (existing_summary or "")
        + f"\n历史对话摘要: {old_text[:1000]}"
    ).strip()
    return recent, new_summary


def _truncate_tool_events(
    events: list[dict[str, Any]], max_events: int
) -> list[dict[str, Any]]:
    if len(events) <= max_events:
        return events
    return events[-max_events:]


def _create_tool_events_rollup(
    events: list[dict[str, Any]], max_keep: int
) -> dict[str, Any]:
    kept = events[-max_keep:]
    old = events[:-max_keep]
    total = len(events)
    successes = sum(1 for e in events if e.get("status") == "success")
    fails = sum(1 for e in events if e.get("status") == "fail")

    tool_counts: dict[str, int] = {}
    node_counts: dict[str, int] = {}
    fail_details: list[dict[str, Any]] = []
    for e in old:
        t = e.get("tool", "?")
        n = e.get("node", "?")
        tool_counts[t] = tool_counts.get(t, 0) + 1
        node_counts[n] = node_counts.get(n, 0) + 1
        if e.get("status") == "fail":
            fail_details.append(
                {"tool": t, "node": n, "error": e.get("error")}
            )

    return {
        "total": total,
        "success": successes,
        "fail": fails,
        "tool_counts": tool_counts,
        "node_counts": node_counts,
        "fail_details": fail_details[:5],
    }


def _format_messages_for_summary(
    messages: list[dict[str, Any]], max_chars: int
) -> str:
    parts: list[str] = []
    total = 0
    for m in messages:
        role = m.get("role", "?")
        content = str(m.get("content", ""))
        entry = f"[{role}]\n{content}\n"
        total += len(entry)
        if total > max_chars and parts:
            parts.append("...(后续内容已截断)")
            break
        parts.append(entry)

    return "\n".join(parts)
