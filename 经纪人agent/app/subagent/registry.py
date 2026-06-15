from __future__ import annotations

from app.subagent.loader import SubagentLoader


class RegistryBuilder:
    def __init__(self, loader: SubagentLoader) -> None:
        self._loader = loader

    def build_registry_prompt(self) -> str:
        names = self._loader.list_available()
        lines: list[str] = ["可用子 agent："]

        for name in names:
            try:
                definition = self._loader.load_sync(name)
                desc = definition.description.replace("\n", " ").strip()
                params = definition.input_schema.get("properties", {})
                required = definition.input_schema.get("required", [])
                params_desc = ", ".join(
                    f"{k}: {v.get('type', 'any')}{' (必填)' if k in required else ''}"
                    for k, v in params.items()
                )
                lines.append(f"- {name}: {desc}")
                lines.append(f"  输入: {{{params_desc}}}")
            except FileNotFoundError:
                continue

        lines.append("")
        lines.append('调用方式: spawn("subagent_name", {"参数": "值"})')
        lines.append("注意: subagent 之间不可嵌套调用")
        return "\n".join(lines)
