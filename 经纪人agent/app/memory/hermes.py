from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Literal

MemoryTarget = Literal["memory", "user"]

ENTRY_SEPARATOR = "\n§\n"
TARGET_LABELS: dict[MemoryTarget, str] = {
    "memory": "MEMORY",
    "user": "USER",
}
TARGET_DESCRIPTIONS: dict[MemoryTarget, str] = {
    "memory": "personal notes",
    "user": "user profile",
}


class HermesMemoryStore:
    def __init__(
        self,
        root_dir: Path,
        memory_char_limit: int = 2200,
        user_char_limit: int = 1375,
    ) -> None:
        self.root_dir = root_dir
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def memory_path(self) -> Path:
        return self.root_dir / "MEMORY.md"

    @property
    def user_path(self) -> Path:
        return self.root_dir / "USER.md"

    def list_entries(self, target: MemoryTarget) -> list[str]:
        path = self._path_for_target(target)
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        return [entry.strip() for entry in raw.split(ENTRY_SEPARATOR) if entry.strip()]

    def add(self, target: MemoryTarget, content: str) -> dict:
        content = content.strip()
        if not content:
            return self._result(target, "add", False, "content is empty")

        blocked_reason = self._scan_forbidden_content(content)
        if blocked_reason is not None:
            return self._result(target, "add", False, blocked_reason)

        entries = self.list_entries(target)
        if content in entries:
            return self._result(target, "add", True, "duplicate skipped", entries=entries)

        updated_entries = entries + [content]
        if self._usage(updated_entries) > self._limit_for_target(target):
            return self._result(
                target,
                "add",
                False,
                "memory limit exceeded; consolidate entries first",
                entries=entries,
            )

        self._write_entries(target, updated_entries)
        return self._result(target, "add", True, "entry added", entries=updated_entries)

    def replace(self, target: MemoryTarget, old_text: str, content: str) -> dict:
        content = content.strip()
        if not content:
            return self._result(target, "replace", False, "content is empty")

        blocked_reason = self._scan_forbidden_content(content)
        if blocked_reason is not None:
            return self._result(target, "replace", False, blocked_reason)

        entries = self.list_entries(target)
        matches = [index for index, entry in enumerate(entries) if old_text in entry]
        if not matches:
            return self._result(target, "replace", False, "no matching entry found", entries=entries)
        if len(matches) > 1:
            return self._result(target, "replace", False, "multiple matching entries found", entries=entries)

        index = matches[0]
        updated_entries = list(entries)
        updated_entries[index] = content

        if content in entries and entries[index] != content:
            return self._result(target, "replace", False, "replacement would create a duplicate", entries=entries)

        if self._usage(updated_entries) > self._limit_for_target(target):
            return self._result(
                target,
                "replace",
                False,
                "memory limit exceeded; consolidate entries first",
                entries=entries,
            )

        self._write_entries(target, updated_entries)
        return self._result(target, "replace", True, "entry replaced", entries=updated_entries)

    def remove(self, target: MemoryTarget, old_text: str) -> dict:
        entries = self.list_entries(target)
        matches = [index for index, entry in enumerate(entries) if old_text in entry]
        if not matches:
            return self._result(target, "remove", False, "no matching entry found", entries=entries)
        if len(matches) > 1:
            return self._result(target, "remove", False, "multiple matching entries found", entries=entries)

        index = matches[0]
        updated_entries = [entry for i, entry in enumerate(entries) if i != index]
        self._write_entries(target, updated_entries)
        return self._result(target, "remove", True, "entry removed", entries=updated_entries)

    def render_snapshot(self) -> str:
        parts: list[str] = []
        for target in ("memory", "user"):
            parts.append(self.render_target(target))
        return "\n\n".join(parts)

    def render_target(self, target: MemoryTarget) -> str:
        entries = self.list_entries(target)
        used = self._usage(entries)
        limit = self._limit_for_target(target)
        percent = int((used / limit) * 100) if limit else 0
        label = TARGET_LABELS[target]
        description = TARGET_DESCRIPTIONS[target]
        header = f"{label} ({description}) [{percent}% - {used}/{limit} chars]"
        body = ENTRY_SEPARATOR.join(entries) if entries else "(empty)"
        return "\n".join([header, body])

    def stats(self, target: MemoryTarget) -> dict[str, int | str]:
        entries = self.list_entries(target)
        used = self._usage(entries)
        limit = self._limit_for_target(target)
        percent = int((used / limit) * 100) if limit else 0
        return {
            "target": target,
            "used_chars": used,
            "limit_chars": limit,
            "percent": percent,
            "entries": len(entries),
        }

    def _path_for_target(self, target: MemoryTarget) -> Path:
        return self.memory_path if target == "memory" else self.user_path

    def _limit_for_target(self, target: MemoryTarget) -> int:
        return self.memory_char_limit if target == "memory" else self.user_char_limit

    def _usage(self, entries: list[str]) -> int:
        if not entries:
            return 0
        return sum(len(entry) for entry in entries) + max(0, len(entries) - 1) * len(ENTRY_SEPARATOR)

    def _write_entries(self, target: MemoryTarget, entries: list[str]) -> None:
        path = self._path_for_target(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = ENTRY_SEPARATOR.join(entries)
        path.write_text(payload, encoding="utf-8")

    def _scan_forbidden_content(self, content: str) -> str | None:
        for character in content:
            if self._is_control_character(character):
                return "content contains unsupported control characters"

        forbidden_patterns = [
            "ignore previous instructions",
            "system prompt",
            "developer message",
            "api key",
            "password",
            "secret",
            "token",
            "private key",
        ]
        lowered = content.lower()
        for pattern in forbidden_patterns:
            if pattern in lowered:
                return f"content blocked by memory safety rule: {pattern}"
        return None

    def _is_control_character(self, character: str) -> bool:
        if character in {"\t", "\n", "\r"}:
            return False
        return unicodedata.category(character) in {"Cc", "Cf"}

    def _result(
        self,
        target: MemoryTarget,
        action: str,
        success: bool,
        message: str,
        entries: list[str] | None = None,
    ) -> dict:
        current_entries = entries if entries is not None else self.list_entries(target)
        return {
            "success": success,
            "target": target,
            "action": action,
            "message": message,
            "entries": current_entries,
            "stats": self.stats(target),
        }
