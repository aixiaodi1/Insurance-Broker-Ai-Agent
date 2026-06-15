from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.services.agent_runtime import AgentRuntime, load_agent_runtime


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "agent_runtime"


class SystemPromptAssembler:
    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        runtime_dir: str | Path = DEFAULT_RUNTIME_DIR,
        project_root: str | Path | None = None,
    ) -> None:
        self._runtime = runtime or load_agent_runtime()
        self._runtime_dir = Path(runtime_dir)
        self._project_root = Path(project_root) if project_root is not None else Path.cwd()

    def build(self, remembered_context: dict[str, Any] | None = None) -> str:
        sections = [
            self._read_markdown("identity.md"),
            self._read_markdown("behavior.md"),
            self._render_system_policy(),
            self._render_core_tools(),
            self._render_plugin_index(),
            self._render_skill_index(),
            self._render_project_context(),
            self._render_memory(remembered_context or {}),
            self._render_react_contract(),
        ]
        return "\n\n".join(section for section in sections if section.strip())

    def _read_markdown(self, name: str) -> str:
        path = self._runtime_dir / name
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def _render_system_policy(self) -> str:
        path = self._runtime_dir / "system_policy.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        rules = data.get("rules") if isinstance(data, dict) else []
        lines = ["# System Policy"]
        lines.extend(f"- {rule}" for rule in rules if isinstance(rule, str))
        return "\n".join(lines)

    def _render_core_tools(self) -> str:
        lines = ["# Core Tools"]
        for tool in self._runtime.core_tools():
            tool_id = tool.get("id")
            description = tool.get("description") or ""
            permission = tool.get("permission_profile") or "unknown"
            if tool_id:
                lines.append(f"- {tool_id}: {description} Permission: {permission}.")
        return "\n".join(lines)

    def _render_plugin_index(self) -> str:
        lines = ["# Plugin Tool Index"]
        for plugin in self._runtime.plugin_index():
            plugin_id = plugin.get("id")
            description = plugin.get("description") or ""
            schema_ref = plugin.get("schema_ref") or ""
            if plugin_id:
                lines.append(f"- {plugin_id}: {description} Schema ref: {schema_ref}.")
        return "\n".join(lines)

    def _render_skill_index(self) -> str:
        lines = ["# Skills Index"]
        for skill in self._runtime.skill_index():
            skill_id = skill.get("id")
            description = skill.get("description") or ""
            doc_ref = skill.get("doc_ref") or ""
            if skill_id:
                lines.append(f"- {skill_id}: {description} Doc ref: {doc_ref}.")
        return "\n".join(lines)

    def _render_project_context(self) -> str:
        for name in ("AGENTS.md", "agents.md"):
            path = self._project_root / name
            if path.exists():
                content = path.read_text(encoding="utf-8", errors="ignore").strip()
                if content:
                    return f"# Project Context\n\n## {name}\n\n{content[:12000]}"
        return ""

    def _render_memory(self, remembered_context: dict[str, Any]) -> str:
        if not remembered_context:
            return ""
        summary = remembered_context.get("thread_summary")
        recent = remembered_context.get("recent_messages") or []
        lines = ["# Conversation Context"]
        if isinstance(summary, dict) and summary.get("summary"):
            lines.append(f"- Summary: {summary['summary']}")
        for item in recent[:6]:
            if isinstance(item, dict) and item.get("content"):
                lines.append(f"- {item.get('role', 'message')}: {item['content']}")
        return "\n".join(lines)

    def _render_react_contract(self) -> str:
        return "\n".join(
            [
                "# ReAct Output Contract",
                "你必须只输出 JSON，不要输出 Markdown 或额外解释。",
                '直接回答：{"action":"final","answer":"..."}',
                '追问：{"action":"clarify","question":"..."}',
                '调用工具：{"action":"tool_call","tool":"local_search|web_search|web.fetch|github.repo_tree|github.file_read|shell.exec","arguments":{...}}',
                '进入 workflow：{"action":"workflow_call","workflow":"insurance_research|claim_analysis|document_review","arguments":{"prompt":"..."}}',
                "最多选择一个 action。不要编造工具结果。",
            ]
        )
