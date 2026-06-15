from __future__ import annotations

import json
import re
from typing import Protocol


class MemoryExtractor(Protocol):
    def generate(self, prompt: str, system_prompt: str | None = None) -> dict: ...


def extract_memory_payload(user_input: str, final_summary: str | None, extractor: MemoryExtractor) -> dict:
    prompt = _build_prompt(user_input=user_input, final_summary=final_summary)
    try:
        result = extractor.generate(prompt, system_prompt=_system_prompt())
        answer = str(result.get("answer", ""))
        json_text = _extract_json(answer)
        if json_text is None:
            return {"ok": False, "error": "memory extractor did not return JSON"}
        payload = json.loads(json_text)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if not isinstance(payload, dict):
        return {"ok": False, "error": "memory extractor JSON must be an object"}

    return {
        "ok": True,
        "facts": _list_of_dicts(payload.get("facts")),
        "project_memories": _list_of_dicts(payload.get("project_memories")),
        "evidence_memories": _list_of_dicts(payload.get("evidence_memories")),
    }


def _build_prompt(user_input: str, final_summary: str | None) -> str:
    return (
        "Extract durable memory from this insurance research interaction.\n"
        "Return JSON with keys: facts, project_memories, evidence_memories.\n"
        "Only include facts that are useful in future tasks and include confidence for user facts.\n\n"
        f"User input:\n{user_input}\n\n"
        f"Assistant summary:\n{final_summary or ''}"
    )


def _system_prompt() -> str:
    return (
        "You extract memory for an auditable insurance research agent. "
        "Long-term memory is only a clue, not formal evidence."
    )


def _extract_json(text: str) -> str | None:
    text = text.strip()
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```", r"(\{.*\})"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _list_of_dicts(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
