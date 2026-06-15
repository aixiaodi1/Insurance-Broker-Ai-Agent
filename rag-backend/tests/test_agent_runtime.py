from pathlib import Path

from app.services.agent_runtime import CommandPermissionGuard, load_agent_runtime


def test_runtime_manifest_exposes_layered_tool_and_skill_indexes() -> None:
    runtime = load_agent_runtime()

    assert "filesystem.read" in runtime.core_tool_ids()
    assert "shell.exec" in runtime.core_tool_ids()
    assert all(tool["layer"] == "core" for tool in runtime.core_tools())
    assert runtime.plugin_index()
    assert all("schema" not in plugin for plugin in runtime.plugin_index())
    assert all("schema_ref" in plugin for plugin in runtime.plugin_index())
    assert runtime.skill_index()
    assert all("description" in skill and "doc_ref" in skill for skill in runtime.skill_index())


def test_command_permission_guard_loads_rules_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "permissions.command.yaml"
    config_path.write_text(
        """
modes:
  plan:
    default: ask_for_mutation
  build:
    default: allow_low_risk
normalize:
  strip_ansi: true
  nfkc: true
  remove_backslash_escapes: true
  remove_empty_string_quotes: true
  env_aliases:
    $HERMES_HOME: ~/.hermes
hard_deny:
  - id: custom_deny
    pattern: "^custom-danger$"
    reason: custom_hardline
ask:
  - id: custom_ask
    pattern: "^custom-ask$"
    reason: custom_guard
    risk: custom_risk
plan_ask:
  - id: custom_plan
    pattern: "^custom-plan$"
    reason: custom_plan_guard
    risk: custom_plan_risk
""",
        encoding="utf-8",
    )

    guard = CommandPermissionGuard.from_file(config_path)

    assert guard.check("custom-danger", mode="build")["action"] == "deny"
    ask_decision = guard.check("custom-ask", mode="build")
    assert ask_decision["action"] == "ask"
    assert ask_decision["risk"] == "custom_risk"
    plan_decision = guard.check("custom-plan", mode="plan")
    assert plan_decision["action"] == "ask"
    assert plan_decision["reason"] == "custom_plan_guard"
