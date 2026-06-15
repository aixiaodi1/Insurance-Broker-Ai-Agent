from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.config import PROJECT_ROOT, settings
from app.tools.registry import get_all_tool_specs


BOOTSTRAP_DOCS = (
    "AGENTS.md",
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "TOOLS.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
    "Skills.md",
    "SUB_AGENTS.md",
    "PROVIDERS.md",
)


class AgentContextAssembler:
    def __init__(self, project_root: Path | str = PROJECT_ROOT, timezone: str = "Asia/Shanghai") -> None:
        self.project_root = Path(project_root)
        self.timezone = timezone

    def build(self) -> dict[str, Any]:
        return {
            "current_datetime": self._now(),
            "documents": self._read_documents(),
            "tools": self._tool_summaries(),
            "sub_agents": self._sub_agent_summaries(),
            "provider": self._provider_summary(),
        }

    def render_for_prompt(self) -> str:
        context = self.build()
        lines = [
            f"[current_datetime]\n{context['current_datetime']}",
            "[provider]\n" + _compact(context["provider"]),
        ]
        for name, payload in context["documents"].items():
            status = payload.get("status")
            text = payload.get("content") or payload.get("error") or ""
            lines.append(f"[{name} | {status}]\n{text}")
        lines.append("[tools]\n" + _compact(context["tools"]))
        lines.append("[sub_agents]\n" + _compact(context["sub_agents"]))
        return "\n\n".join(lines)

    def _now(self) -> str:
        tz = timezone(timedelta(hours=8), name=self.timezone) if self.timezone == "Asia/Shanghai" else UTC
        return datetime.now(tz).isoformat()

    def _read_documents(self) -> dict[str, dict[str, str]]:
        documents: dict[str, dict[str, str]] = {}
        for name in BOOTSTRAP_DOCS:
            path = self.project_root / name
            if not path.is_file():
                documents[name] = {"status": "missing", "error": f"{name} not found"}
                continue
            documents[name] = {"status": "loaded", "content": path.read_text(encoding="utf-8")}
        return documents

    def _tool_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for spec in get_all_tool_specs():
            function = spec.get("function", {})
            summaries.append(
                {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                }
            )
        return summaries

    def _sub_agent_summaries(self) -> list[dict[str, Any]]:
        contracts_dir = Path(settings.subagent_contracts_dir) if settings.subagent_contracts_dir else self.project_root / "app" / "subagent" / "contracts"
        if not contracts_dir.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in sorted(contracts_dir.glob("*.y*ml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            summaries.append(
                {
                    "name": str(raw.get("name") or path.stem),
                    "description": str(raw.get("description") or ""),
                    "tools": raw.get("tools", {}),
                    "input_schema": raw.get("input_schema", {}),
                }
            )
        return summaries

    def _provider_summary(self) -> dict[str, Any]:
        return {
            "llm_provider": settings.llm_provider,
            "llm_api_base_url_configured": bool(settings.llm_api_base_url),
            "llm_api_path": settings.llm_api_path,
            "llm_model": settings.llm_model,
            "llm_api_key_configured": bool(settings.llm_api_key or settings.minimax_api_key),
            "web_search_enabled": settings.enable_web_search,
            "subagent_contracts_dir": settings.subagent_contracts_dir or "app/subagent/contracts",
        }


def _compact(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str, indent=2)
