from pathlib import Path


SECRET_FILENAMES = {".env", "config.toml", "secrets.toml"}


def secret_write_deny_gate(path: str) -> dict[str, object]:
    name = Path(path).name.lower()
    denied = name in SECRET_FILENAMES or "token" in name or "secret" in name
    return {
        "allowed": not denied,
        "reason": "禁止写入密钥文件" if denied else None,
    }
