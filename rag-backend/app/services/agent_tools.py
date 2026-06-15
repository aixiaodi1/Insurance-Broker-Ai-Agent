from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.services.command_permissions import approval_request, check_command_permission

TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv", ".py", ".toml", ".yaml", ".yml"}
IGNORED_PATH_PARTS = {".git", ".next", ".pytest_cache", "__pycache__", "node_modules", "tests"}
COMMON_ENGLISH_TERMS = {
    "a",
    "an",
    "and",
    "coverage",
    "find",
    "for",
    "get",
    "help",
    "in",
    "insurance",
    "look",
    "lookup",
    "me",
    "medical",
    "of",
    "official",
    "one",
    "please",
    "policy",
    "product",
    "products",
    "search",
    "summary",
    "the",
    "to",
    "with",
}
WEB_INTENT_TERMS = {
    "a",
    "an",
    "and",
    "find",
    "for",
    "get",
    "help",
    "in",
    "look",
    "lookup",
    "me",
    "of",
    "one",
    "please",
    "search",
    "the",
    "to",
    "with",
}
COMMON_CJK_TERMS = {
    "保险",
    "产品",
    "资料",
    "官方",
    "联合",
    "医疗",
    "医疗险",
    "疗险",
    "一款",
    "款医",
    "帮我",
    "查找",
    "查询",
    "找一",
    "找一款",
    "住院",
    "费用",
}


def extract_cli_command(prompt: str) -> str | None:
    stripped = prompt.strip()
    lowered = stripped.lower()
    for prefix in ("运行命令", "执行命令", "run command", "cli:"):
        if lowered.startswith(prefix.lower()):
            command = stripped[len(prefix):].strip(" ：:")
            return command or None
    return None


def run_cli(
    command: str,
    cwd: Path,
    timeout_seconds: int = 8,
    mode: str = "plan",
    approved: bool = False,
) -> dict[str, Any]:
    decision = check_command_permission(command, mode)
    if decision["action"] == "deny":
        return {
            "ok": False,
            "source": "run_cli",
            "data": {"command": command, "permission": decision},
            "error": "command_denied",
        }
    if decision["action"] == "ask" and not approved:
        return {
            "ok": False,
            "source": "run_cli",
            "data": {
                "command": command,
                "permission": decision,
                "approvalRequest": approval_request(command, mode),
            },
            "error": "human_approval_required",
        }
    external_paths = _external_paths(command, cwd)
    if external_paths and not approved:
        return {
            "ok": False,
            "source": "run_cli",
            "data": {
                "command": command,
                "permission": {
                    "action": "ask",
                    "mode": mode,
                    "command": command,
                    "normalized": command,
                    "reason": "external_path_guard",
                    "risk": "external_path",
                    "paths": [str(path) for path in external_paths],
                },
                "approvalRequest": _external_path_approval_request(command, mode),
            },
            "error": "human_approval_required",
        }
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd.resolve()),
            text=True,
            encoding="utf-8",
            errors="ignore",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=True,
        )
    except FileNotFoundError:
        return {"ok": False, "source": "run_cli", "data": {"command": command}, "error": "command_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "source": "run_cli", "data": {"command": command}, "error": "command_timeout"}

    return {
        "ok": completed.returncode in (0, 1),
        "source": "run_cli",
        "data": {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[:4000],
            "stderr": completed.stderr[:1200],
            "permission": decision,
        },
        "error": None if completed.returncode in (0, 1) else "command_failed",
    }


def _external_path_approval_request(command: str, mode: str) -> dict:
    request = approval_request(command, mode)
    return {
        "id": request["id"],
        "type": "command",
        "command": command,
        "normalizedCommand": request["normalizedCommand"],
        "mode": "build" if mode == "build" else "plan",
        "risk": "external_path",
        "reason": "external_path_guard",
    }


def _external_paths(command: str, cwd: Path) -> list[Path]:
    root = cwd.resolve()
    paths: list[Path] = []
    for raw in re.findall(r"[A-Za-z]:\\(?:[^<>:\"|?*\r\n]+)", command):
        candidate = Path(raw.strip().strip("\"'"))
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if not _is_relative_to(resolved, root):
                paths.append(resolved)
    return paths


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def local_search(query: str, root: Path, limit: int = 5) -> dict[str, Any]:
    search_root = root.resolve()
    terms = _query_terms(query)
    matches: list[dict[str, Any]] = []
    for term in terms:
        matches.extend(_rg_search(term, search_root, limit - len(matches)))
        matches = _dedupe_matches(matches)
        if len(matches) >= limit:
            break
    if not matches:
        matches = _walk_search(terms, search_root, limit)
    matches = _dedupe_matches(matches)
    return {"ok": True, "source": "local_search", "data": {"query": query, "root": str(search_root), "matches": matches[:limit]}, "error": None}


def web_search(query: str, limit: int = 3) -> dict[str, Any]:
    search_query = _web_search_query(query)
    known_results = _known_web_results(search_query, limit)
    if len(known_results) >= limit and not _is_broad_insurance_research_query(search_query):
        return {
            "ok": True,
            "source": "web_search",
            "data": {"query": search_query, "original_query": query, "results": known_results[:limit]},
            "error": None,
        }
    url = f"https://www.bing.com/search?q={quote_plus(search_query)}"
    fetched = web_fetch(url, max_chars=160000)
    if not fetched["ok"]:
        return {"ok": False, "source": "web_search", "data": {"query": search_query, "original_query": query, "results": known_results}, "error": fetched["error"]}
    results: list[dict[str, str]] = [*known_results]
    for match in re.finditer(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', fetched["data"].get("raw_html", ""), re.I | re.S):
        item = {"title": _clean_text(match.group(2)), "url": _unwrap_bing_url(html.unescape(match.group(1)))}
        if item["url"] not in {result["url"] for result in results}:
            results.append(item)
        if len(results) >= limit:
            break
    return {"ok": True, "source": "web_search", "data": {"query": search_query, "original_query": query, "results": results}, "error": None}


def web_fetch(url: str, max_chars: int = 4000) -> dict[str, Any]:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 agent-workbench/0.1"})
        with urlopen(request, timeout=10) as response:
            content_type = response.headers.get("content-type", "")
            body = response.read(max_chars * 4)
    except HTTPError as exc:
        body = exc.read(4000).decode("utf-8", errors="ignore")
        return {
            "ok": False,
            "source": "web_fetch",
            "data": {"url": url, "status": exc.code, "text": body[:4000]},
            "error": "HTTPError",
        }
    except Exception as exc:
        return {"ok": False, "source": "web_fetch", "data": {"url": url}, "error": type(exc).__name__}
    raw = body.decode("utf-8", errors="ignore")
    text = _clean_text(_html_to_text(raw)) if "html" in content_type else raw[:max_chars]
    return {"ok": True, "source": "web_fetch", "data": {"url": url, "content_type": content_type, "text": text[:max_chars], "raw_html": raw[:max_chars]}, "error": None}


def _query_terms(query: str) -> list[str]:
    terms = [
        term
        for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}", query)
        if len(term) > 2 and term.lower() not in COMMON_ENGLISH_TERMS
    ]
    for cjk_text in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        terms.append(cjk_text)
        for size in (4, 3, 2):
            terms.extend(
                term
                for term in (cjk_text[index:index + size] for index in range(0, max(len(cjk_text) - size + 1, 0)))
                if not _is_common_cjk_term(term)
            )
    if not terms and query.strip():
        terms.append(query.strip())
    unique_terms: list[str] = []
    for term in terms:
        if term and term not in unique_terms:
            unique_terms.append(term)
    return unique_terms[:30]


def _is_common_cjk_term(term: str) -> bool:
    return term in COMMON_CJK_TERMS or (len(term) <= 4 and any(common in term for common in COMMON_CJK_TERMS))


def _web_search_query(query: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", query):
        return _rewrite_cjk_web_query(query)
    terms = [
        term
        for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query)
        if term.lower() not in WEB_INTENT_TERMS
    ]
    return " ".join(terms) or query.strip()


def _rewrite_cjk_web_query(query: str) -> str:
    cleaned = query.strip()
    for phrase in (
        "你帮我去",
        "帮我去",
        "帮我",
        "请",
        "查一下",
        "查找",
        "查询",
        "找一款",
        "找一个",
        "找",
        "一款",
        "一个",
        "去",
    ):
        cleaned = cleaned.replace(phrase, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("医疗险", " 医疗险")
    return re.sub(r"\s+", " ", cleaned).strip() or query.strip()


def _known_web_results(query: str, limit: int) -> list[dict[str, str]]:
    return []


def _is_broad_insurance_research_query(query: str) -> bool:
    lowered = query.lower()
    return (
        "irr" in lowered
        or "\u5206\u7ea2" in query
        or "\u6536\u76ca" in query
        or "\u4fdd\u5fb7\u4fe1" in query
        or "\u661f\u798f\u5bb6" in query
    )


def github_repo_tree(repo_url: str, limit: int = 300) -> dict[str, Any]:
    repo = _github_repo_slug(repo_url)
    if not repo:
        return {"ok": False, "source": "github_repo_tree", "data": {"url": repo_url}, "error": "invalid_github_repo"}
    api_root = f"https://api.github.com/repos/{repo}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 agent-workbench/0.1"}
        repo_request = Request(api_root, headers=headers)
        with urlopen(repo_request, timeout=10) as response:
            repo_payload = json.loads(response.read(300_000).decode("utf-8", errors="ignore"))
        default_branch = str(repo_payload.get("default_branch") or "main") if isinstance(repo_payload, dict) else "main"
        api_url = f"{api_root}/git/trees/{default_branch}?recursive=1"
        request = Request(api_url, headers=headers)
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except HTTPError as exc:
        body = exc.read(4000).decode("utf-8", errors="ignore")
        return {
            "ok": False,
            "source": "github_repo_tree",
            "data": {"repo": repo, "url": repo_url, "status": exc.code, "text": body[:4000]},
            "error": "HTTPError",
        }
    except Exception as exc:
        return {"ok": False, "source": "github_repo_tree", "data": {"repo": repo, "url": repo_url}, "error": type(exc).__name__}
    tree = payload.get("tree") if isinstance(payload, dict) else []
    files = [
        {"path": str(item.get("path") or ""), "type": str(item.get("type") or "")}
        for item in tree
        if isinstance(item, dict) and item.get("path")
    ][:limit]
    return {"ok": True, "source": "github_repo_tree", "data": {"repo": repo, "url": repo_url, "files": files}, "error": None}


def github_file_read(repo_url: str, path: str, max_chars: int = 12000) -> dict[str, Any]:
    repo = _github_repo_slug(repo_url)
    if not repo or not path:
        return {
            "ok": False,
            "source": "github_file_read",
            "data": {"repoUrl": repo_url, "path": path},
            "error": "invalid_github_file",
        }
    raw_url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
    fetched = web_fetch(raw_url, max_chars=max_chars)
    if not fetched.get("ok"):
        return {"ok": False, "source": "github_file_read", "data": {"repoUrl": repo_url, "path": path}, "error": fetched.get("error")}
    data = fetched.get("data") or {}
    return {
        "ok": True,
        "source": "github_file_read",
        "data": {
            "repoUrl": repo_url,
            "repo": repo,
            "path": path,
            "text": str(data.get("text") or data.get("raw_html") or "")[:max_chars],
        },
        "error": None,
    }


def _github_repo_slug(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if owner in {"search", "topics", "marketplace"}:
        return None
    return f"{owner}/{repo}"


def _rg_search(term: str, root: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or shutil.which("rg") is None:
        return []
    completed = subprocess.run(
        [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--ignore-case",
            "--glob",
            "!tests/**",
            "--glob",
            "!**/__pycache__/**",
            "--glob",
            "!node_modules/**",
            "--glob",
            "!.git/**",
            "--glob",
            "!.next/**",
            term,
            str(root),
        ],
        text=True,
        encoding="utf-8",
        errors="ignore",
        capture_output=True,
        timeout=8,
        check=False,
    )
    if completed.returncode not in (0, 1):
        return []
    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        match = re.match(r"^(.*):(\d+):(.*)$", line)
        if match and not _is_ignored_path(Path(match.group(1))):
            matches.append({"path": match.group(1), "line": int(match.group(2)), "excerpt": match.group(3).strip()})
        if len(matches) >= limit:
            break
    return matches


def _walk_search(terms: list[str], root: Path, limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    lowered_terms = [term.lower() for term in terms if term]
    for path in root.rglob("*"):
        if len(matches) >= limit:
            break
        if _is_ignored_path(path) or not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(term in text.lower() for term in lowered_terms):
            excerpt = next((line.strip() for line in text.splitlines() if any(term in line.lower() for term in lowered_terms)), "")
            matches.append({"path": str(path), "line": None, "excerpt": excerpt[:500]})
    return matches


def _dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, Any, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in matches:
        key = (str(item.get("path") or ""), item.get("line"), str(item.get("excerpt") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _is_ignored_path(path: Path) -> bool:
    return any(part.lower() in IGNORED_PATH_PARTS for part in path.parts)


def _html_to_text(text: str) -> str:
    parser = _TextExtractor()
    parser.feed(text)
    return parser.text()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _unwrap_bing_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc not in {"www.bing.com", "bing.com"} or "/ck/" not in parsed.path:
        return url
    encoded = parse_qs(parsed.query).get("u", [""])[0]
    if not encoded:
        return url
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    try:
        padding = "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(encoded + padding).decode("utf-8", errors="ignore")
    except Exception:
        return unquote(encoded)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self._parts)
