from __future__ import annotations

import inspect
from time import perf_counter
from typing import Protocol
from urllib.parse import urlparse

from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep
from app.web_acquisition.security import SecurityGate, SecurityViolation


class SiteSpecificHarness(Protocol):
    domains: tuple[str, ...]

    async def run(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        ...


class SiteHarnessRegistry:
    def __init__(self) -> None:
        self._harnesses: dict[str, SiteSpecificHarness] = {}

    def register(self, harness: SiteSpecificHarness, domains: tuple[str, ...] | None = None) -> None:
        for domain in domains or harness.domains:
            normalized = self._normalize_domain(domain)
            if normalized:
                self._harnesses[normalized] = harness

    def get_harness(self, domain_or_url: str) -> SiteSpecificHarness | None:
        host = self._host(domain_or_url)
        if not host:
            return None
        for domain, harness in self._harnesses.items():
            if host == domain or host.endswith(f".{domain}"):
                return harness
        return None

    def _host(self, domain_or_url: str) -> str:
        parsed = urlparse(domain_or_url)
        host = parsed.hostname if parsed.hostname else domain_or_url
        return self._normalize_domain(host)

    def _normalize_domain(self, domain: str) -> str:
        return domain.lower().strip().strip(".")


class HarnessRunner:
    def __init__(self, registry: SiteHarnessRegistry, security_gate: SecurityGate | None = None) -> None:
        self.registry = registry
        self.security_gate = security_gate or SecurityGate()

    async def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="security", action="validate", description="Validate input URL", url_before=url)]
        try:
            check = self.security_gate.validate_url(url, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return self._failure(url, exc.code, str(exc), "security", started, steps)

        harness = self.registry.get_harness(check.host)
        if harness is None:
            return self._failure(url, "harness_not_found", f"No site-specific harness registered for {check.host}", "harness", started, steps)

        try:
            result = await self._maybe_await(harness.run(check.normalized_url, goal, allowed_domains=allowed_domains))
        except Exception as exc:
            return self._failure(url, type(exc).__name__, str(exc), "harness", started, steps)

        if not isinstance(result, AcquisitionResult):
            return self._failure(url, "invalid_harness_result", "Harness returned an invalid result", "harness", started, steps)

        result.strategy_used = "harness"
        result.steps = steps + result.steps
        if not result.final_url:
            result.final_url = check.normalized_url
        result.duration_ms = result.duration_ms or self._duration(started)
        return result

    def _failure(
        self,
        input_url: str,
        code: str,
        message: str,
        layer: str,
        started: float,
        steps: list[AcquisitionStep],
    ) -> AcquisitionResult:
        return AcquisitionResult(
            success=False,
            input_url=input_url,
            final_url=input_url,
            strategy_used="harness",
            steps=steps,
            errors=[AcquisitionError(code=code, message=message, layer=layer, url=input_url)],
            duration_ms=self._duration(started),
        )

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value
        return value

    def _duration(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)
