from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app.search.schemas import SearchItem, SearchProviderResult


class BaiduQianfanSearchProvider:
    name = "baidu_qianfan"

    def __init__(self, api_key: str = "", endpoint: str = "", timeout_seconds: int = 8) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        if not self.api_key or not self.endpoint:
            return SearchProviderResult(provider=self.name, ok=False, error="provider_not_configured")
        payload = json.dumps({"messages": [{"role": "user", "content": query}]}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8", errors="ignore"))
        except HTTPError as exc:
            return SearchProviderResult(provider=self.name, ok=False, error=_http_error(exc.code))
        except Exception as exc:  # pragma: no cover - provider failures vary by network.
            return SearchProviderResult(provider=self.name, ok=False, error=type(exc).__name__)
        if not isinstance(data, dict) or not isinstance(data.get("references"), list):
            return SearchProviderResult(provider=self.name, ok=False, error="provider_contract_error")
        if data.get("code") not in (None, 0):
            return SearchProviderResult(provider=self.name, ok=False, error="provider_contract_error")
        return SearchProviderResult(provider=self.name, ok=True, results=_parse_items(data["references"], self.name, limit))


class FirecrawlSearchProvider:
    name = "firecrawl"

    def __init__(self, api_key: str = "", endpoint: str = "https://api.firecrawl.dev/v2/search", timeout_seconds: int = 8) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        if not self.api_key or not self.endpoint:
            return SearchProviderResult(provider=self.name, ok=False, error="provider_not_configured")
        payload = json.dumps({"query": query, "limit": limit, "sources": ["web"]}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8", errors="ignore"))
        except HTTPError as exc:
            return SearchProviderResult(provider=self.name, ok=False, error=_http_error(exc.code))
        except Exception as exc:  # pragma: no cover - provider failures vary by network.
            return SearchProviderResult(provider=self.name, ok=False, error=type(exc).__name__)
        if not isinstance(data, dict):
            return SearchProviderResult(provider=self.name, ok=False, error="provider_contract_error")
        web = data.get("data", {}).get("web") if isinstance(data.get("data"), dict) else None
        if data.get("success") is not True or not isinstance(web, list):
            return SearchProviderResult(provider=self.name, ok=False, error="provider_contract_error")
        return SearchProviderResult(provider=self.name, ok=True, results=_parse_items(web, self.name, limit))


class BaiduBrowserSearchProvider:
    name = "public_browser"

    def __init__(self, runner: Callable[[str, int], list[dict[str, Any]]] | None = None) -> None:
        self.runner = runner or _run_public_playwright_search

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        try:
            rows = self.runner(query, limit)
        except RuntimeError as exc:
            code = str(exc) if str(exc) in {"playwright_unavailable", "browser_challenge"} else type(exc).__name__
            return SearchProviderResult(provider=self.name, ok=False, error=code)
        except Exception as exc:  # pragma: no cover - browser failures depend on runtime.
            return SearchProviderResult(provider=self.name, ok=False, error=type(exc).__name__)
        if not isinstance(rows, list):
            return SearchProviderResult(provider=self.name, ok=False, error="provider_contract_error")
        safe_rows = [row for row in rows if not _looks_browser_spam(row)]
        if not safe_rows:
            return SearchProviderResult(provider=self.name, ok=False, error="no_search_results")
        return SearchProviderResult(provider=self.name, ok=True, results=_parse_items(safe_rows, self.name, limit))


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str = "", endpoint: str = "https://api.search.brave.com/res/v1/web/search", timeout_seconds: int = 8) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        if not self.api_key:
            return SearchProviderResult(provider=self.name, ok=False, error="provider_not_configured")
        url = f"{self.endpoint}?{urlencode({'q': query, 'count': limit})}"
        request = Request(url, headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8", errors="ignore"))
        except Exception as exc:  # pragma: no cover - provider failures vary by network.
            return SearchProviderResult(provider=self.name, ok=False, error=type(exc).__name__)
        return SearchProviderResult(provider=self.name, ok=True, results=_parse_items(data, self.name, limit))


def _parse_items(data: Any, provider: str, limit: int) -> list[SearchItem]:
    rows = _candidate_rows(data)
    items: list[SearchItem] = []
    for index, row in enumerate(rows[:limit], start=1):
        url = str(row.get("url") or row.get("link") or row.get("href") or "")
        if not url:
            continue
        items.append(
            SearchItem(
                title=str(row.get("title") or row.get("name") or ""),
                url=url,
                snippet=str(row.get("snippet") or row.get("description") or row.get("summary") or row.get("content") or ""),
                provider=provider,
                rank=index,
                published_at=row.get("published_at") or row.get("date"),
            )
        )
    return items


def _candidate_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("references", "results", "items", "webPages", "organic"):
        value = data.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict) and isinstance(value.get("value"), list):
            return [row for row in value["value"] if isinstance(row, dict)]
    web = data.get("web")
    if isinstance(web, dict) and isinstance(web.get("results"), list):
        return [row for row in web["results"] if isinstance(row, dict)]
    return []


def _looks_browser_spam(row: dict[str, Any]) -> bool:
    url = str(row.get("url") or row.get("link") or "").lower()
    text = f"{row.get('title', '')} {row.get('snippet', '')} {row.get('description', '')}".lower()
    if row.get("sponsored") is True or any(term in text for term in ("广告", "推广", "赞助")):
        return True
    return "baijiahao.baidu.com" in url or "zhidao.baidu.com" in url


def _run_public_playwright_search(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional live dependency.
        raise RuntimeError("playwright_unavailable") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            rows = _search_baidu_mobile(browser, query, limit)
            if rows:
                return rows
            return _search_360(browser, query, limit)
        finally:
            browser.close()


def _search_baidu_mobile(browser: Any, query: str, limit: int) -> list[dict[str, Any]]:
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
        locale="zh-CN",
        viewport={"width": 412, "height": 915},
    )
    try:
        page = context.new_page()
        page.goto(f"https://m.baidu.com/s?word={quote_plus(query)}", wait_until="domcontentloaded", timeout=30_000)
        if "安全验证" in page.title() or "wappass.baidu.com" in page.url:
            return []
        return _extract_browser_rows(page, ".result, .c-result, #content_left .c-container", limit)
    finally:
        context.close()


def _search_360(browser: Any, query: str, limit: int) -> list[dict[str, Any]]:
    context = browser.new_context(locale="zh-CN")
    try:
        page = context.new_page()
        page.goto(f"https://www.so.com/s?q={quote_plus(query)}", wait_until="domcontentloaded", timeout=30_000)
        return _extract_browser_rows(page, ".res-list, .result", limit)
    finally:
        context.close()


def _extract_browser_rows(page: Any, selector: str, limit: int) -> list[dict[str, Any]]:
    rows = page.eval_on_selector_all(
        selector,
        """(nodes) => nodes.map((node) => {
            const anchor = node.querySelector('h3 a, a[href]');
            return {
                title: anchor ? anchor.innerText : '',
                url: anchor ? (anchor.dataset.mdurl || anchor.href) : '',
                snippet: node.innerText || '',
                sponsored: /广告|推广/.test(node.innerText || '')
            };
        })""",
    )
    return [row for row in rows if isinstance(row, dict) and row.get("url")][:limit]


def _http_error(status_code: int) -> str:
    if status_code in (401, 403):
        return "provider_auth_error"
    if status_code == 429:
        return "provider_rate_limited"
    return "provider_http_error"
