from __future__ import annotations

import html
import base64
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from app.config import settings
from app.memory.schemas import ToolResult


TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv", ".py", ".toml", ".yaml", ".yml"}
ALLOWED_CLI = {"rg", "dir", "ls", "Get-ChildItem"}


def local_search(query: str, root: Path | str | None = None, limit: int = 8) -> ToolResult:
    search_root = Path(root or settings.local_source_root).resolve()
    terms = _query_terms(query)
    matches: list[dict[str, Any]] = []
    started = perf_counter()

    for term in terms:
        matches.extend(_rg_search(term, search_root, limit - len(matches)))
        if len(matches) >= limit:
            break

    if not matches:
        matches = _walk_search(terms, search_root, limit)

    return ToolResult(
        ok=True,
        source="local_search",
        data={
            "query": query,
            "root": str(search_root),
            "matches": matches[:limit],
            "duration_ms": int((perf_counter() - started) * 1000),
        },
    )


def local_read(path: Path | str, max_chars: int = 1600) -> ToolResult:
    target = Path(path).resolve()
    if not target.exists() or not target.is_file():
        return ToolResult(ok=False, source="local_read", data={"path": str(target)}, error="file_not_found")
    if target.suffix.lower() not in TEXT_SUFFIXES:
        return ToolResult(ok=False, source="local_read", data={"path": str(target)}, error="unsupported_file_type")
    text = target.read_text(encoding="utf-8", errors="ignore")
    return ToolResult(
        ok=True,
        source="local_read",
        data={"path": str(target), "text": text[:max_chars], "truncated": len(text) > max_chars},
    )


def run_cli(command: str, cwd: Path | str | None = None, timeout_seconds: int = 8) -> ToolResult:
    parts = _split_command(command)
    if not parts or parts[0] not in ALLOWED_CLI:
        return ToolResult(ok=False, source="run_cli", data={"command": command}, error="command_not_allowed")
    started = perf_counter()
    try:
        completed = subprocess.run(
            parts,
            cwd=str(Path(cwd or settings.local_source_root).resolve()),
            text=True,
            encoding="utf-8",
            errors="ignore",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return ToolResult(ok=False, source="run_cli", data={"command": command}, error="command_not_found")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, source="run_cli", data={"command": command}, error="command_timeout")

    return ToolResult(
        ok=completed.returncode in (0, 1),
        source="run_cli",
        data={
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[:4000],
            "stderr": completed.stderr[:1200],
            "duration_ms": int((perf_counter() - started) * 1000),
        },
        error=None if completed.returncode in (0, 1) else "command_failed",
    )


def web_search(query: str, limit: int = 5) -> ToolResult:
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    fetched = web_fetch(url, max_chars=160000)
    if not fetched.ok:
        return ToolResult(ok=False, source="web_search", data={"query": query, "results": []}, error=fetched.error)

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for match in re.finditer(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', fetched.data.get("raw_html", ""), re.I | re.S):
        result_url = _normalize_result_url(_unwrap_bing_url(html.unescape(match.group(1))))
        if not result_url or result_url in seen_urls:
            continue
        seen_urls.add(result_url)
        results.append(
            {
                "title": _clean_text(match.group(2)),
                "url": result_url,
            }
        )
        if len(results) >= limit:
            break
    return ToolResult(ok=True, source="web_search", data={"query": query, "results": results, "content_kind": "search_results"})


def web_fetch(url: str, max_chars: int = 4000) -> ToolResult:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 insurance-agent-research/0.1"})
        with urlopen(request, timeout=10) as response:
            content_type = response.headers.get("content-type", "")
            body = response.read(max_chars * 4)
    except Exception as exc:  # pragma: no cover - network failures vary by environment.
        return ToolResult(ok=False, source="web_fetch", data={"url": url}, error=type(exc).__name__)

    text = body.decode("utf-8", errors="ignore")
    is_html = "html" in content_type
    plain_text = _clean_text(_html_to_text(_strip_non_content_html(text))) if is_html else text[:max_chars]
    return ToolResult(
        ok=True,
        source="web_fetch",
        data={
            "url": url,
            "domain": urlparse(url).netloc,
            "content_type": content_type,
            "content_kind": "webpage_text" if is_html else "raw_text",
            "text": plain_text[:max_chars],
            "raw_html": text[:max_chars],
        },
    )


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}", query)
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}", query))
    if query.strip() and query.strip() not in terms:
        terms.append(query.strip())
    return terms[:6]


def _rg_search(term: str, root: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or shutil.which("rg") is None:
        return []
    completed = subprocess.run(
        ["rg", "--line-number", "--no-heading", "--color", "never", term, str(root)],
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
        path, line_no, excerpt = _parse_rg_line(line)
        if path:
            matches.append({"path": path, "line": line_no, "excerpt": excerpt})
        if len(matches) >= limit:
            break
    return matches


def _walk_search(terms: list[str], root: Path, limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    lowered_terms = [term.lower() for term in terms if term]
    for path in root.rglob("*"):
        if len(matches) >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        if any(term.lower() in lowered for term in lowered_terms):
            excerpt = next((line.strip() for line in text.splitlines() if any(term.lower() in line.lower() for term in lowered_terms)), "")
            matches.append({"path": str(path), "line": None, "excerpt": excerpt[:500]})
    return matches


def _parse_rg_line(line: str) -> tuple[str | None, int | None, str]:
    match = re.match(r"^(.*):(\d+):(.*)$", line)
    if not match:
        return None, None, line
    return match.group(1), int(match.group(2)), match.group(3).strip()


def _split_command(command: str) -> list[str]:
    return [part for part in command.strip().split() if part]


def _html_to_text(text: str) -> str:
    parser = _TextExtractor()
    parser.feed(text)
    return parser.text()


def _strip_non_content_html(text: str) -> str:
    stripped = text
    for tag in ("script", "style", "noscript", "svg", "nav", "header", "footer"):
        stripped = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", stripped, flags=re.I | re.S)
    return stripped


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _normalize_result_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    normalized = parsed._replace(fragment="").geturl()
    return normalized.rstrip("/")


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
