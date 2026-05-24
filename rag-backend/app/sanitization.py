import re


def sanitize_error_message(message: str) -> str:
    if not message:
        return "unknown error"

    sanitized = re.sub(r"[A-Za-z]:[\\/][^\s]+", "<path>", message)
    sanitized = re.sub(r"(?<!\w)/(?:[^\s/]+/)+[^\s]+", "<path>", sanitized)
    sanitized = re.sub(
        r"(?i)\bauthorization\s*[:=]\s*bearer\s+[^'\"\s]+",
        "authorization=<redacted>",
        sanitized,
    )
    sanitized = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", sanitized)
    sanitized = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|authorization)\s*[:=]\s*['\"]?[^'\"\s]+",
        r"\1=<redacted>",
        sanitized,
    )
    return sanitized
