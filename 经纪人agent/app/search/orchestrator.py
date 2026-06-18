from __future__ import annotations

import re
from datetime import UTC, datetime
from dataclasses import replace
from time import perf_counter
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.search.query_planning import QueryPlanner
from app.search.providers import BaiduBrowserSearchProvider, BaiduQianfanSearchProvider, FirecrawlSearchProvider
from app.search.safety import EgressGuard, PromptInjectionGuard, unsafe_public_url_reason
from app.search.schemas import SearchItem, SearchPlan, SearchProvider, SearchProviderResult, SearchRequest, SearchResponse


TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "source",
}
SEO_DOMAINS = {"baijiahao.baidu.com", "zhidao.baidu.com"}
CLICKBAIT_TERMS = ("震惊", "必看", "揭秘", "速看", "终于曝光")
AD_TERMS = ("广告", "推广", "赞助")


class SemanticReranker(Protocol):
    def rerank(self, plan: SearchPlan, candidates: list[SearchItem]) -> list[SearchItem]: ...


class NoOpSemanticReranker:
    def rerank(self, plan: SearchPlan, candidates: list[SearchItem]) -> list[SearchItem]:
        return candidates


class SearchOrchestrator:
    def __init__(
        self,
        planner: QueryPlanner,
        primary: SearchProvider,
        fallback: SearchProvider,
        browser: SearchProvider,
        resolve_host=None,
        trusted_domains: set[str] | None = None,
        semantic_reranker: SemanticReranker | None = None,
    ) -> None:
        self.planner = planner
        self.primary = primary
        self.fallback = fallback
        self.browser = browser
        self.resolve_host = resolve_host
        self.trusted_domains = {domain.lower().strip(".") for domain in (trusted_domains or set())}
        self.semantic_reranker = semantic_reranker or NoOpSemanticReranker()
        self.prompt_guard = PromptInjectionGuard()
        self.egress_guard = EgressGuard()

    def search(self, request: SearchRequest) -> SearchResponse:
        plan = self.planner.plan(request)
        errors: list[dict] = []
        statuses: list[dict] = []
        trace = [
            {"type": "search_requirement", "requirement": plan.network_requirement, "summary": _intent_summary(plan)},
            {"type": "query_plan_ready", "query_count": len(plan.queries), "roles": [query.role for query in plan.queries]},
        ]
        lists: list[tuple[str, str, SearchProviderResult]] = []

        self._run_provider(self.primary, plan, lists, errors, statuses, trace, request.limit)
        primary_candidates = self._fuse(lists, plan, errors)
        needs_dual = plan.risk_level == "high" or plan.freshness != "not_required"
        fallback_used = needs_dual or not self._sufficient(primary_candidates, plan)
        degradation = "none"
        if fallback_used:
            self._run_provider(self.fallback, plan, lists, errors, statuses, trace, request.limit)
            if not needs_dual:
                degradation = "fallback_provider"

        candidates = self._fuse(lists, plan, errors)
        if not self._sufficient(candidates, plan):
            self._run_provider(self.browser, plan, lists, errors, statuses, trace, request.limit)
            candidates = self._fuse(lists, plan, errors)
            if any(status["provider"] == self.browser.name and status["ok"] for status in statuses):
                degradation = "browser_fallback"

        if not candidates:
            degradation = "degraded_no_search"
        candidates = self.semantic_reranker.rerank(plan, candidates[:20])[: request.limit]
        trace.append({"type": "search_fused", "candidate_count": len(candidates)})
        if degradation != "none":
            trace.append({"type": "search_degraded", "status": degradation})
        used = list(dict.fromkeys(status["provider"] for status in statuses if status["ok"] and status["result_count"] > 0))
        return SearchResponse(
            query=request.original_question,
            provider_used="+".join(used) if used else "none",
            fallback_used=fallback_used,
            results=candidates,
            errors=errors,
            plan=plan,
            degradation=degradation,
            provider_statuses=statuses,
            public_trace=trace,
        )

    def _run_provider(
        self,
        provider: SearchProvider,
        plan: SearchPlan,
        lists: list[tuple[str, str, SearchProviderResult]],
        errors: list[dict],
        statuses: list[dict],
        trace: list[dict],
        limit: int,
    ) -> None:
        started = perf_counter()
        trace.append({"type": "provider_search_started", "provider": provider.name, "query_count": len(plan.queries)})
        total = 0
        provider_ok = False
        for query in plan.queries:
            result = provider.search(query.text, limit=limit)
            lists.append((provider.name, query.role, result))
            provider_ok = provider_ok or result.ok
            total += len(result.results)
            if not result.ok:
                errors.append({"code": result.error or "provider_error", "provider": provider.name, "query_role": query.role})
        duration_ms = int((perf_counter() - started) * 1000)
        statuses.append({"provider": provider.name, "ok": provider_ok, "result_count": total, "duration_ms": duration_ms})
        trace.append(
            {"type": "provider_search_finished", "provider": provider.name, "ok": provider_ok, "result_count": total, "duration_ms": duration_ms}
        )

    def _fuse(
        self,
        lists: list[tuple[str, str, SearchProviderResult]],
        plan: SearchPlan,
        errors: list[dict],
    ) -> list[SearchItem]:
        fused: dict[str, SearchItem] = {}
        for provider, role, result in lists:
            if not result.ok:
                continue
            for rank, raw in enumerate(result.results, start=1):
                safe = self._safe_candidate(raw, provider, role, rank, errors)
                if safe is None:
                    continue
                contribution = 1.0 / (60 + rank)
                current = fused.get(safe.normalized_url)
                if current is None:
                    fused[safe.normalized_url] = replace(safe, rrf_score=contribution)
                else:
                    roles = list(dict.fromkeys(current.query_roles + [role]))
                    fused[safe.normalized_url] = replace(current, rrf_score=current.rrf_score + contribution, query_roles=roles)
        ranked = [self._apply_rules(item, plan) for item in fused.values()]
        return sorted(ranked, key=lambda item: (item.score, item.rrf_score), reverse=True)

    def _safe_candidate(
        self,
        item: SearchItem,
        provider: str,
        role: str,
        rank: int,
        errors: list[dict],
    ) -> SearchItem | None:
        egress = self.egress_guard.validate_url(item.url)
        if not egress.allowed:
            errors.append({"code": egress.reason, "provider": provider, "url": item.url})
            return None
        unsafe_reason = unsafe_public_url_reason(item.url, resolve_host=self.resolve_host)
        if unsafe_reason:
            errors.append({"code": unsafe_reason, "provider": provider, "url": item.url})
            return None
        injection = self.prompt_guard.scan(f"{item.title}\n{item.snippet}")
        if injection.suspected:
            errors.append({"code": "prompt_injection_blocked", "provider": provider, "url": item.url, "risk_flags": injection.flags})
            return None
        normalized = normalize_url(item.url)
        if not normalized:
            errors.append({"code": "invalid_url", "provider": provider, "url": item.url})
            return None
        return replace(
            item,
            provider=provider,
            rank=rank,
            original_url=item.original_url or item.url,
            normalized_url=normalized,
            query_roles=[role],
        )

    def _apply_rules(self, item: SearchItem, plan: SearchPlan) -> SearchItem:
        parsed = urlparse(item.normalized_url)
        host = (parsed.hostname or "").lower()
        trust = "unknown"
        source_type = "webpage"
        adjustment = 0.0
        flags = list(item.risk_flags)
        if host.endswith(".gov.cn") or host in {"nfra.gov.cn", "www.nfra.gov.cn"}:
            trust = "regulator"
            adjustment += 0.30
        elif any(host == domain or host.endswith(f".{domain}") for domain in self.trusted_domains):
            trust = "official"
            adjustment += 0.25
        is_pdf = parsed.path.lower().endswith(".pdf")
        if is_pdf:
            source_type = "pdf"
            if trust in {"official", "regulator"}:
                adjustment += 0.20
            if any(value in plan.document_types for value in ("pdf", "clause", "product_manual", "disclosure", "rate_table", "cash_value_table")):
                adjustment += 0.10
        text = f"{item.title} {item.snippet}".lower()
        if plan.freshness != "not_required" and any(term in text for term in ("最新", "最近", "发布", "2025", "2026")):
            adjustment += 0.10
        if plan.freshness != "not_required" and _is_stale(item.published_at):
            adjustment -= 0.20
            flags.append("freshness_mismatch")
        if any(term in text for term in AD_TERMS):
            adjustment -= 0.40
            flags.append("advertising")
        if host in SEO_DOMAINS or any(host.endswith(f".{domain}") for domain in SEO_DOMAINS):
            adjustment -= 0.30
            flags.append("seo_or_marketing_risk")
        if any(term in text for term in CLICKBAIT_TERMS):
            adjustment -= 0.20
            flags.append("clickbait")
        return replace(
            item,
            trust_tier=trust,
            source_type=source_type,
            risk_flags=list(dict.fromkeys(flags)),
            rule_adjustment=round(adjustment, 4),
            score=round(item.rrf_score + adjustment, 6),
        )

    @staticmethod
    def _sufficient(candidates: list[SearchItem], plan: SearchPlan) -> bool:
        core_entities = [entity for entity in plan.protected_entities if not re.fullmatch(r"\d+(?:\.\d+)?%?", entity)]
        if core_entities and not any(
            any(entity.lower() in f"{item.title} {item.snippet}".lower() for entity in core_entities)
            for item in candidates
        ):
            return False
        if any(item.trust_tier in {"official", "regulator"} for item in candidates):
            return True
        covered_roles = {role for item in candidates for role in item.query_roles}
        return len(candidates) >= 3 and len(covered_roles) >= 2


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().strip(".")
    port = parsed.port
    netloc = host if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_QUERY_KEYS])
    return urlunparse((scheme, netloc, path, "", query, "")).rstrip("/") if path == "/" and not query else urlunparse((scheme, netloc, path, "", query, ""))


def _intent_summary(plan: SearchPlan) -> dict:
    return {
        "freshness": plan.freshness,
        "source_preference": list(plan.source_preference),
        "document_types": list(plan.document_types),
        "risk_level": plan.risk_level,
    }


def _is_stale(published_at: str | None) -> bool:
    if not published_at:
        return False
    match = re.search(r"(?:19|20)\d{2}", published_at)
    if not match:
        return False
    return int(match.group(0)) < datetime.now(UTC).year - 1


def build_default_search_orchestrator() -> SearchOrchestrator:
    from app.config import settings
    from app.memory.llm import build_memory_extractor_from_settings

    model = build_memory_extractor_from_settings(settings)
    trusted = {value.strip() for value in settings.search_trusted_domains.split(",") if value.strip()}
    return SearchOrchestrator(
        planner=QueryPlanner(model=model),
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
        browser=BaiduBrowserSearchProvider(),
        trusted_domains=trusted,
    )
