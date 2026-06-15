from __future__ import annotations

import time
from pathlib import Path

import yaml

from app.subagent.schemas import SubagentDefinition


class SubagentLoader:
    def __init__(self, contracts_dir: str | Path, ttl_seconds: int = 60) -> None:
        self._contracts_dir = Path(contracts_dir)
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[SubagentDefinition, float]] = {}

    async def load(self, name: str) -> SubagentDefinition:
        now = time.time()
        cached = self._cache.get(name)
        if cached is not None and (now - cached[1]) < self._ttl:
            return cached[0]

        path = self._resolve_path(name)
        raw = self._read_yaml(path)
        validated = SubagentDefinition.model_validate(raw)
        self._cache[name] = (validated, now)
        return validated

    def load_sync(self, name: str) -> SubagentDefinition:
        now = time.time()
        cached = self._cache.get(name)
        if cached is not None and (now - cached[1]) < self._ttl:
            return cached[0]

        path = self._resolve_path(name)
        raw = self._read_yaml(path)
        validated = SubagentDefinition.model_validate(raw)
        self._cache[name] = (validated, now)
        return validated

    def invalidate(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    def list_available(self) -> list[str]:
        return sorted(
            p.stem for p in self._contracts_dir.glob("*.yaml") if p.is_file()
        )

    def _resolve_path(self, name: str) -> Path:
        for ext in (".yaml", ".yml"):
            path = self._contracts_dir / f"{name}{ext}"
            if path.is_file():
                return path
        msg = f"Subagent contract '{name}' not found in {self._contracts_dir}"
        raise FileNotFoundError(msg)

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            raise ValueError(f"{path} is not a valid YAML mapping")
        return raw
