from __future__ import annotations

import ipaddress
import socket
from dataclasses import replace
from urllib.parse import urlparse

from app.config import settings
from app.search.providers import BaiduQianfanSearchProvider, FirecrawlSearchProvider
from app.search.schemas import SearchItem, SearchProvider, SearchProviderResult, SearchResponse
from app.search.safety import PromptInjectionGuard


HIGH_RISK_TERMS = (
    "保险",
    "条款",
    "pdf",
    "官方",
    "监管",
    "金融",
    "法律",
    "医疗",
    "政策",
    "公司",
    "资质",
    "最新",
)

MARKETING_DOMAINS = (
    "baijiahao.baidu.com",
    "zhidao.baidu.com",
)


class SearchRouter:
    def __init__(
        self,
        primary: SearchProvider,
        fallback: SearchProvider,
        resolve_host=None,
        high_risk_dual_provider: bool = True,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.high_risk_dual_provider = high_risk_dual_provider
        self.resolve_host = resolve_host or _resolve_host
        self.prompt_guard = PromptInjectionGuard()

    def search(self, query: str, limit: int = 8) -> SearchResponse:
        errors: list[dict] = []
        primary_result = self.primary.search(query, limit=limit)

        if self.high_risk_dual_provider and looks_high_risk_query(query):
            fallback_result = self.fallback.search(query, limit=limit)
            errors.extend(_provider_errors(primary_result, fallback_result))
            results = self._rank(self._safe_unique(primary_result.results + fallback_result.results, errors))[:limit]
            return SearchResponse(
                query=query,
                provider_used=f"{self.primary.name}+{self.fallback.name}",
                fallback_used=False,
                results=results,
                errors=errors,
            )

        if primary_result.ok and primary_result.results:
            return SearchResponse(
                query=query,
                provider_used=self.primary.name,
                fallback_used=False,
                results=self._rank(self._safe_unique(primary_result.results, errors))[:limit],
                errors=errors,
            )

        fallback_result = self.fallback.search(query, limit=limit)
        errors.extend(_provider_errors(primary_result, fallback_result))
        return SearchResponse(
            query=query,
            provider_used=self.fallback.name,
            fallback_used=True,
            results=self._rank(self._safe_unique(fallback_result.results, errors))[:limit],
            errors=errors,
        )

    def _safe_unique(self, items: list[SearchItem], errors: list[dict]) -> list[SearchItem]:
        seen: set[str] = set()
        safe: list[SearchItem] = []
        for item in items:
            error_code = _unsafe_url_reason(item.url, self.resolve_host)
            if error_code:
                errors.append({"code": error_code, "url": item.url, "provider": item.provider})
                continue
            normalized = item.url.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            safe.append(_score_item(item, self.prompt_guard))
        return safe

    def _rank(self, items: list[SearchItem]) -> list[SearchItem]:
        return sorted(items, key=lambda item: item.score, reverse=True)


def build_default_search_router() -> SearchRouter:
    return SearchRouter(
        primary=BaiduQianfanSearchProvider(
            api_key=settings.baidu_qianfan_api_key,
            endpoint=settings.baidu_qianfan_search_endpoint,
            timeout_seconds=settings.search_timeout_seconds,
        ),
        fallback=FirecrawlSearchProvider(
            api_key=settings.firecrawl_api_key,
            endpoint=settings.firecrawl_search_endpoint,
            timeout_seconds=settings.search_timeout_seconds,
        ),
        high_risk_dual_provider=settings.search_high_risk_dual_provider,
    )


def looks_high_risk_query(query: str) -> bool:
    lowered = query.lower()
    return any(term.lower() in lowered for term in HIGH_RISK_TERMS)


def _score_item(item: SearchItem, prompt_guard: PromptInjectionGuard) -> SearchItem:
    parsed = urlparse(item.url)
    host = parsed.netloc.lower()
    trust_tier = _trust_tier(host, parsed.path)
    risk_flags = list(item.risk_flags)
    if any(host == domain or host.endswith(f".{domain}") for domain in MARKETING_DOMAINS):
        risk_flags.append("seo_or_marketing_risk")
    report = prompt_guard.scan(f"{item.title}\n{item.snippet}")
    if report.suspected:
        risk_flags.extend(report.flags)

    base = {
        "regulator": 0.95,
        "official_document": 0.9,
        "official": 0.82,
        "unknown": 0.45,
    }[trust_tier]
    if "seo_or_marketing_risk" in risk_flags:
        base -= 0.25
    if report.suspected:
        base -= 0.15
    return replace(item, trust_tier=trust_tier, risk_flags=list(dict.fromkeys(risk_flags)), score=max(base, 0.0))


def _trust_tier(host: str, path: str) -> str:
    if host.endswith(".gov.cn") or "cbirc.gov.cn" in host or "nfra.gov.cn" in host:
        return "regulator"
    if path.lower().split("?", 1)[0].endswith(".pdf"):
        return "official_document"
    if not any(host == domain or host.endswith(f".{domain}") for domain in MARKETING_DOMAINS):
        return "official"
    return "unknown"


def _provider_errors(*results: SearchProviderResult) -> list[dict]:
    errors: list[dict] = []
    for result in results:
        if not result.ok:
            errors.append({"code": result.error or "provider_error", "provider": result.provider})
    return errors


def _unsafe_url_reason(url: str, resolve_host) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "scheme_not_allowed"
    host = parsed.hostname or ""
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return "host_not_allowed"
    try:
        ips = resolve_host(host)
    except Exception:
        return "dns_resolution_failed"
    for raw_ip in ips:
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            return "ip_not_allowed"
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return "ip_not_allowed"
    return ""


def _resolve_host(host: str) -> list[str]:
    return [item[4][0] for item in socket.getaddrinfo(host, None)]
