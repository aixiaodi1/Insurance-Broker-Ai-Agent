from __future__ import annotations

from typing import Literal

MemoryTarget = Literal["memory", "user"]


def capture_memory_entries(user_message: str, assistant_summary: str | None) -> list[tuple[MemoryTarget, str]]:
    entries: list[tuple[MemoryTarget, str]] = []

    user_note = _capture_user_note(user_message)
    if user_note is not None:
        entries.append(("user", user_note))

    work_note = _capture_work_note(user_message, assistant_summary)
    if work_note is not None:
        entries.append(("memory", work_note))

    return entries


def _capture_user_note(text: str) -> str | None:
    lowered = text.lower()
    markers = [
        "请记住",
        "以后请",
        "以后都",
        "我喜欢",
        "我偏好",
        "我习惯",
        "不要",
        "别用",
        "记住我",
        "我希望",
        "下次请",
    ]
    if not any(marker in text for marker in markers) and not any(marker in lowered for marker in markers):
        return None

    note = text.strip().replace("\n", " ")
    if len(note) > 220:
        note = note[:217].rstrip() + "..."
    return f"User preference note: {note}"


def _capture_work_note(user_message: str, assistant_summary: str | None) -> str | None:
    task = _clip(user_message, 120)
    if assistant_summary:
        outcome = _clip(assistant_summary, 220)
        return f"Completed task: {task} | Outcome: {outcome}"
    return f"Completed task: {task}"


def _clip(text: str, limit: int) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
