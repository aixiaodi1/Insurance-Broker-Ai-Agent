from __future__ import annotations

import hashlib

from app.services.agent_runtime import (
    CommandMode,
    CommandPermissionDecision,
    get_default_command_permission_guard,
)


def check_command_permission(command: str, mode: str = "plan") -> CommandPermissionDecision:
    return get_default_command_permission_guard().check(command, mode)


def normalize_command(command: str) -> str:
    return get_default_command_permission_guard().normalize(command)


def approval_request(command: str, mode: str = "plan") -> dict:
    decision = check_command_permission(command, mode)
    digest = hashlib.sha256(
        f"{decision['normalized']}|{decision['mode']}|{decision['risk']}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": f"cmd:{digest}",
        "type": "command",
        "command": command,
        "normalizedCommand": decision["normalized"],
        "mode": decision["mode"],
        "risk": decision["risk"],
        "reason": decision["reason"],
    }
