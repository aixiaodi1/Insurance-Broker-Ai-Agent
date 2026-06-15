from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "prompts.default.yaml"
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass(frozen=True)
class RenderedPrompt:
    name: str
    version: str
    system: str | None
    user: str
    json_mode: bool
    temperature: float | None
    max_tokens: int | None


class PromptRegistry:
    def __init__(self, data: dict[str, Any]) -> None:
        self._blocks = data.get("blocks") if isinstance(data.get("blocks"), dict) else {}
        self._prompts = data.get("prompts") if isinstance(data.get("prompts"), dict) else {}

    @classmethod
    def from_file(cls, path: str | Path) -> "PromptRegistry":
        raw = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            raise ValueError("Prompt registry YAML must contain a mapping.")
        return cls(data)

    def render(self, name: str, **variables: Any) -> RenderedPrompt:
        spec = self._prompt_spec(name)
        system = self._render_system(spec, variables)
        user = self._render_template(str(spec.get("user") or ""), variables)
        return RenderedPrompt(
            name=name,
            version=str(spec.get("version") or "unversioned"),
            system=system,
            user=user,
            json_mode=bool(spec.get("json_mode", False)),
            temperature=float(spec["temperature"]) if spec.get("temperature") is not None else None,
            max_tokens=int(spec["max_tokens"]) if spec.get("max_tokens") is not None else None,
        )

    def _prompt_spec(self, name: str) -> dict[str, Any]:
        spec = self._prompts.get(name)
        if not isinstance(spec, dict):
            raise KeyError(f"Unknown prompt: {name}")
        return spec

    def _render_system(self, spec: dict[str, Any], variables: dict[str, Any]) -> str | None:
        parts: list[str] = []
        for block_name in spec.get("system_blocks") or []:
            block = self._blocks.get(block_name)
            if block is None:
                raise KeyError(f"Unknown prompt block: {block_name}")
            parts.append(self._render_template(str(block), variables))
        if spec.get("system"):
            parts.append(self._render_template(str(spec["system"]), variables))
        system = "\n\n".join(part.strip() for part in parts if part.strip())
        return system or None

    def _render_template(self, template: str, variables: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in variables:
                raise KeyError(key)
            return str(variables[key])

        return _PLACEHOLDER_RE.sub(replace, template).strip()


@lru_cache(maxsize=1)
def get_default_prompt_registry() -> PromptRegistry:
    return PromptRegistry.from_file(DEFAULT_PROMPT_PATH)
