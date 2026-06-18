from __future__ import annotations

import re
from time import perf_counter
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from app.web_acquisition.http_fetcher import FastHttpFetcher
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep
from app.web_acquisition.security import SecurityGate, SecurityViolation


class SiteDiscoveryFetcher:
    def __init__(
        self,
        candidate_fetcher: FastHttpFetcher | None = None,
        security_gate: SecurityGate | None = None,
        transport=None,
    ) -> None:
        self.candidate_fetcher = candidate_fetcher or FastHttpFetcher()
        self.security_gate = security_gate or SecurityGate()
        self.transport = transport or self._default_transport

    def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="site_discovery", action="discover", description="Discover public site maps", url_before=url)]
        try:
            check = self.security_gate.validate_url(url, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return _failure(url, "site_discovery", exc.code, str(exc), steps, started)

        candidates = self._discover_candidates(check.normalized_url, steps)
        for candidate in candidates:
            try:
                self.security_gate.validate_url(candidate, allowed_domains=allowed_domains)
            except SecurityViolation:
                continue
            result = self.candidate_fetcher.fetch(candidate, goal, allowed_domains=allowed_domains)
            result.strategy_used = "site_discovery"
            result.steps = steps + result.steps
            if result.success:
                return result
        return _failure(url, "site_discovery", "sitemap_not_found", "No usable sitemap or robots candidate succeeded", steps, started)

    def _discover_candidates(self, url: str, steps: list[AcquisitionStep]) -> list[str]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        seeds = [urljoin(origin, "/robots.txt"), urljoin(origin, "/sitemap.xml")]
        candidates: list[str] = []
        for seed in seeds:
            text = self.transport(seed)
            if not text:
                continue
            steps.append(AcquisitionStep(layer="site_discovery", action="read", description="Read discovery document", url_after=seed))
            candidates.extend(_extract_urls(text, origin))
        return list(dict.fromkeys(candidates))

    def _default_transport(self, url: str) -> str:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 insurance-agent-research/0.1"})
            with urlopen(request, timeout=8) as response:
                return response.read(1_000_000).decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - network failures vary by environment.
            return ""


def _extract_urls(text: str, origin: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\"]+", text)
    urls.extend(urljoin(origin, path) for path in re.findall(r"<loc>\s*([^<]+)\s*</loc>", text, flags=re.I))
    return [url.strip() for url in urls if url.strip()]


def _failure(url: str, strategy: str, code: str, message: str, steps: list[AcquisitionStep], started: float) -> AcquisitionResult:
    return AcquisitionResult(
        success=False,
        input_url=url,
        final_url=url,
        strategy_used=strategy,
        steps=steps,
        errors=[AcquisitionError(code=code, message=message, layer=strategy, url=url)],
        duration_ms=int((perf_counter() - started) * 1000),
    )
