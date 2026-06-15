from pathlib import Path

from app.services.command_permissions import check_command_permission
from app.services.agent_tools import run_cli


def test_hardline_deny_blocks_unrecoverable_delete() -> None:
    decision = check_command_permission("r\\m -rf /", mode="build")

    assert decision["action"] == "deny"
    assert decision["reason"] == "hardline_blocklist"


def test_plan_mode_requires_approval_for_write_commands() -> None:
    decision = check_command_permission("python -m pip install requests", mode="plan")

    assert decision["action"] == "ask"
    assert decision["risk"] == "environment_mutation"


def test_build_mode_allows_non_dangerous_install_command() -> None:
    decision = check_command_permission("python -m pip --version", mode="build")

    assert decision["action"] == "allow"


def test_delete_file_requires_human_approval() -> None:
    decision = check_command_permission("rm notes.md", mode="build")

    assert decision["action"] == "ask"
    assert decision["risk"] == "file_delete"


def test_run_cli_returns_approval_request_for_ask_command(tmp_path: Path) -> None:
    result = run_cli("rm notes.md", tmp_path, mode="build")

    assert result["ok"] is False
    assert result["error"] == "human_approval_required"
    assert result["data"]["approvalRequest"]["command"] == "rm notes.md"
    assert result["data"]["approvalRequest"]["mode"] == "build"


def test_run_cli_executes_allowed_arbitrary_command(tmp_path: Path) -> None:
    result = run_cli("python --version", tmp_path, mode="plan")

    assert result["ok"] is True
    assert "Python" in result["data"]["stdout"] or "Python" in result["data"]["stderr"]
