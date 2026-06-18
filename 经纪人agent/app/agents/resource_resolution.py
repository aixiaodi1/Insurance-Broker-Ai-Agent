from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


GITHUB_HOSTS = {"github.com", "www.github.com"}


def resolve_resource_context(message: str, project_root: Path | str) -> dict:
    root = Path(project_root)
    local = _detect_local_path(message, root)
    if local:
        return {
            "resource_type": "local_path",
            "location": "local",
            "resource_id": str(local),
            "canonical_url": "",
            "task_type": _task_type(message),
            "confidence": 0.9,
            "needs_external_fetch": False,
            "local_search_recommended": True,
            "primary_tools": ["local_read", "local_search"],
            "fallback_tools": ["run_cli"],
            "candidate_urls": [],
        }

    github_repo = _detect_github_repo(message)
    if github_repo:
        owner, repo = github_repo
        resource_id = f"{owner}/{repo}"
        return {
            "resource_type": "github_repo",
            "location": "remote",
            "resource_id": resource_id,
            "canonical_url": f"https://github.com/{resource_id}",
            "task_type": _task_type(message),
            "confidence": 0.88,
            "needs_external_fetch": True,
            "local_search_recommended": False,
            "primary_tools": ["web_fetch"],
            "fallback_tools": ["web_search"],
            "candidate_urls": [
                f"https://api.github.com/repos/{resource_id}",
                f"https://github.com/{resource_id}",
                f"https://raw.githubusercontent.com/{resource_id}/HEAD/README.md",
                f"https://raw.githubusercontent.com/{resource_id}/main/README.md",
                f"https://raw.githubusercontent.com/{resource_id}/master/README.md",
            ],
        }

    package = _detect_package_name(message)
    if package:
        registry, package_name = package
        canonical_url = _package_url(registry, package_name)
        return {
            "resource_type": "package_name",
            "location": "remote",
            "resource_id": package_name,
            "canonical_url": canonical_url,
            "package_registry": registry,
            "task_type": _task_type(message),
            "confidence": 0.78,
            "needs_external_fetch": True,
            "local_search_recommended": False,
            "primary_tools": ["web_fetch"],
            "fallback_tools": ["web_search"],
            "candidate_urls": [canonical_url],
        }

    web_url = _detect_web_url(message)
    if web_url:
        return {
            "resource_type": "web_url",
            "location": "remote",
            "resource_id": web_url,
            "canonical_url": web_url,
            "task_type": _task_type(message),
            "confidence": 0.8,
            "needs_external_fetch": True,
            "local_search_recommended": False,
            "primary_tools": ["web_fetch"],
            "fallback_tools": ["web_search"],
            "candidate_urls": [web_url],
        }

    return {
        "resource_type": "unknown",
        "location": "unknown",
        "resource_id": "",
        "canonical_url": "",
        "task_type": _task_type(message),
        "confidence": 0.0,
        "needs_external_fetch": False,
        "local_search_recommended": True,
        "primary_tools": [],
        "fallback_tools": [],
        "candidate_urls": [],
    }


def _detect_local_path(message: str, root: Path) -> Path | None:
    for raw in re.findall(r"([A-Za-z]:\\[^\s]+|/[^\s]+|\.[/\\][^\s]+)", message):
        candidate = Path(raw.strip("\"'，。,."))
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists():
            return resolved
    return None


def _detect_github_repo(message: str) -> tuple[str, str] | None:
    url = _detect_web_url(message)
    if url:
        parsed = urlparse(url)
        if parsed.netloc.lower() in GITHUB_HOSTS:
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if len(parts) >= 2 and _valid_repo_part(parts[0]) and _valid_repo_part(parts[1]):
                return parts[0], _strip_git_suffix(parts[1])

    match = re.search(r"(?<![\w.-])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:\.git)?(?![\w.-])", message)
    if match and _valid_repo_part(match.group(1)) and _valid_repo_part(match.group(2)):
        return match.group(1), _strip_git_suffix(match.group(2))
    return None


def _detect_web_url(message: str) -> str:
    match = re.search(r"(https?://[^\s]+|(?:www\.)?github\.com/[^\s]+)", message, re.I)
    if not match:
        return ""
    url = match.group(1).strip("\"'，。,.")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl().rstrip("/")


def _task_type(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("what is", "what does", "readme", "usage")):
        return "explain_project"
    if any(token in message for token in ("什么用", "有什么用", "看看这个项目", "介绍", "用途")):
        return "explain_project"
    return "general_research"


def _detect_package_name(message: str) -> tuple[str, str] | None:
    lowered = message.lower()
    registry = ""
    if "npm" in lowered:
        registry = "npm"
    elif "pypi" in lowered or "pip" in lowered:
        registry = "pypi"
    elif "包" not in message and "package" not in lowered:
        return None
    if not registry:
        return None

    ignored = {"npm", "pypi", "pip", "package", "python", "node", "js"}
    for token in re.findall(r"@?[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)?", message):
        if token.lower() not in ignored:
            return registry, token
    return None


def _package_url(registry: str, package_name: str) -> str:
    if registry == "npm":
        return f"https://www.npmjs.com/package/{package_name}"
    return f"https://pypi.org/project/{package_name}/"


def _valid_repo_part(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and not value.startswith("-")


def _strip_git_suffix(value: str) -> str:
    return value[:-4] if value.endswith(".git") else value
