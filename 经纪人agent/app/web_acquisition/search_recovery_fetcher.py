from __future__ import annotations

from time import perf_counter
from urllib.parse import urlparse

from app.search.orchestrator import SearchOrchestrator, build_default_search_orchestrator
from app.search.router import SearchRouter
from app.search.schemas import SearchRequest
from app.web_acquisition.http_fetcher import FastHttpFetcher
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep
from app.web_acquisition.security import SecurityGate, SecurityViolation


class SearchRecoveryFetcher:
    def __init__(
        self,
        search_router: SearchRouter | SearchOrchestrator | None = None,
        candidate_fetcher: FastHttpFetcher | None = None,
        security_gate: SecurityGate | None = None,
    ) -> None:
        self.search_router = search_router or build_default_search_orchestrator()
        self.candidate_fetcher = candidate_fetcher or FastHttpFetcher()
        self.security_gate = security_gate or SecurityGate()

    def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="search_recovery", action="search", description="Search for alternate public entry points", url_before=url)]
        try:
            check = self.security_gate.validate_url(url, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return _failure(url, exc.code, str(exc), steps, started)

        query = f"site:{check.host} {goal} PDF 官方 信息披露 条款"
        if isinstance(self.search_router, SearchOrchestrator):
            response = self.search_router.search(SearchRequest(original_question=goal, query_goal=query))
        else:
            response = self.search_router.search(query)
        steps.append(
            AcquisitionStep(
                layer="search_recovery",
                action="observe",
                description="Collected search recovery candidates",
                metadata={"query": query, "provider_used": response.provider_used, "candidate_count": len(response.results)},
            )
        )
        effective_domains = allowed_domains or [_registrable_domain(check.host)]
        for item in response.results:
            try:
                self.security_gate.validate_url(item.url, allowed_domains=effective_domains)
            except SecurityViolation:
                continue
            result = self.candidate_fetcher.fetch(item.url, goal, allowed_domains=effective_domains)
            result.strategy_used = "search_recovery"
            result.steps = steps + result.steps
            if result.success:
                return result
        return _failure(url, "no_search_candidates", "No search recovery candidate succeeded", steps, started)


def _registrable_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _failure(url: str, code: str, message: str, steps: list[AcquisitionStep], started: float) -> AcquisitionResult:
    return AcquisitionResult(
        success=False,
        input_url=url,
        final_url=url,
        strategy_used="search_recovery",
        steps=steps,
        errors=[AcquisitionError(code=code, message=message, layer="search_recovery", url=url)],
        duration_ms=int((perf_counter() - started) * 1000),
    )
