from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypedDict

import yaml


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "agent_runtime"
CommandMode = Literal["plan", "build"]


class CommandPermissionDecision(TypedDict):
    action: Literal["allow", "ask", "deny"]
    mode: CommandMode
    command: str
    normalized: str
    reason: str
    risk: str


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Runtime YAML must contain a mapping: {path}")
    return data


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@dataclass(frozen=True)
class AgentRuntime:
    runtime_dir: Path
    tools_data: dict[str, Any]
    plugins_data: dict[str, Any]
    skills_data: dict[str, Any]
    capability_data: dict[str, Any]

    @classmethod
    def from_dir(cls, runtime_dir: str | Path = DEFAULT_RUNTIME_DIR) -> "AgentRuntime":
        root = Path(runtime_dir)
        return cls(
            runtime_dir=root,
            tools_data=_read_yaml(root / "tools.core.yaml"),
            plugins_data=_read_yaml(root / "tools.plugins.index.yaml"),
            skills_data=_read_yaml(root / "skills.index.yaml"),
            capability_data=_read_yaml(root / "capability.answers.yaml"),
        )

    def core_tools(self) -> list[dict[str, Any]]:
        return _as_list(self.tools_data.get("tools"))

    def core_tool_ids(self) -> set[str]:
        return {str(tool.get("id")) for tool in self.core_tools() if tool.get("id")}

    def plugin_index(self) -> list[dict[str, Any]]:
        return _as_list(self.plugins_data.get("plugins"))

    def skill_index(self) -> list[dict[str, Any]]:
        return _as_list(self.skills_data.get("skills"))

    def capability_answer(self, prompt: str) -> dict[str, Any]:
        lowered = prompt.lower()
        intents = _as_list(self.capability_data.get("intents"))
        for intent in intents:
            keywords = [str(item).lower() for item in intent.get("keywords") or []]
            if any(keyword and keyword in lowered for keyword in keywords):
                return self._capability_payload(intent)
        fallback = self.capability_data.get("fallback")
        if isinstance(fallback, dict):
            return self._capability_payload(fallback)
        return {"answer": "", "matchedTools": []}

    def _capability_payload(self, spec: dict[str, Any]) -> dict[str, Any]:
        matched_ids = [str(item) for item in spec.get("matched_tools") or []]
        tools_by_id = {str(tool.get("id")): tool for tool in self.core_tools()}
        return {
            "answer": str(spec.get("answer") or ""),
            "matchedTools": [
                {
                    "id": tool_id,
                    "label": str(tools_by_id.get(tool_id, {}).get("label") or tool_id),
                    "permissionProfile": str(
                        tools_by_id.get(tool_id, {}).get("permission_profile") or "unknown"
                    ),
                }
                for tool_id in matched_ids
            ],
        }


@dataclass(frozen=True)
class CommandPermissionGuard:
    config: dict[str, Any]

    @classmethod
    def from_file(cls, path: str | Path) -> "CommandPermissionGuard":
        return cls(_read_yaml(Path(path)))

    def check(self, command: str, mode: str = "plan") -> CommandPermissionDecision:
        effective_mode: CommandMode = "build" if mode == "build" else "plan"
        normalized = self.normalize(command)
        lowered = normalized.lower()

        for rule in _as_list(self.config.get("hard_deny")):
            if self._matches(rule, lowered):
                reason = str(rule.get("reason") or "hardline_blocklist")
                return _decision(
                    "deny",
                    effective_mode,
                    command,
                    normalized,
                    reason,
                    str(rule.get("risk") or reason),
                )

        for rule in _as_list(self.config.get("ask")):
            if self._matches(rule, normalized):
                return _decision(
                    "ask",
                    effective_mode,
                    command,
                    normalized,
                    str(rule.get("reason") or "dangerous_pattern"),
                    str(rule.get("risk") or rule.get("id") or "unknown"),
                )

        if effective_mode == "plan":
            for rule in _as_list(self.config.get("plan_ask")):
                if self._matches(rule, normalized):
                    return _decision(
                        "ask",
                        effective_mode,
                        command,
                        normalized,
                        str(rule.get("reason") or "plan_mode_guard"),
                        str(rule.get("risk") or rule.get("id") or "unknown"),
                    )

        return _decision("allow", effective_mode, command, normalized, "safe_command", "low")

    def normalize(self, command: str) -> str:
        normalize_config = self.config.get("normalize") if isinstance(self.config.get("normalize"), dict) else {}
        text = command
        if normalize_config.get("strip_ansi", True):
            text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        if normalize_config.get("nfkc", True):
            text = unicodedata.normalize("NFKC", text)
        if normalize_config.get("remove_backslash_escapes", True):
            text = re.sub(r"\\(?=[A-Za-z])", "", text)
        if normalize_config.get("remove_empty_string_quotes", True):
            text = text.replace("''", "").replace('""', "")
        aliases = normalize_config.get("env_aliases")
        if isinstance(aliases, dict):
            for source, target in aliases.items():
                text = text.replace(str(source), str(target))
        return re.sub(r"\s+", " ", text).strip()

    def _matches(self, rule: dict[str, Any], command: str) -> bool:
        pattern = rule.get("pattern")
        return isinstance(pattern, str) and re.search(pattern, command, re.IGNORECASE) is not None


@lru_cache(maxsize=1)
def load_agent_runtime() -> AgentRuntime:
    return AgentRuntime.from_dir(DEFAULT_RUNTIME_DIR)


@lru_cache(maxsize=1)
def get_default_command_permission_guard() -> CommandPermissionGuard:
    return CommandPermissionGuard.from_file(DEFAULT_RUNTIME_DIR / "permissions.command.yaml")


def _decision(
    action: Literal["allow", "ask", "deny"],
    mode: CommandMode,
    command: str,
    normalized: str,
    reason: str,
    risk: str,
) -> CommandPermissionDecision:
    return {
        "action": action,
        "mode": mode,
        "command": command,
        "normalized": normalized,
        "reason": reason,
        "risk": risk,
    }
