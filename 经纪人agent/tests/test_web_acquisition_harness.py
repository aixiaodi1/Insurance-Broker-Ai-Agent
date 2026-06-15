from __future__ import annotations

import asyncio

from app.web_acquisition.harness import HarnessRunner, SiteHarnessRegistry, SiteSpecificHarness
from app.web_acquisition.schemas import AcquisitionResult, AcquisitionStep
from app.web_acquisition.security import SecurityGate


class RecordingHarness(SiteSpecificHarness):
    domains = ("example.com",)

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[str] | None]] = []

    async def run(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        self.calls.append((url, goal, allowed_domains))
        return AcquisitionResult(
            success=True,
            input_url=url,
            final_url=url,
            strategy_used="none",
            title="Harness Product",
            steps=[AcquisitionStep(layer="custom", action="open", description="Open product")],
        )


def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def test_harness_registry_matches_exact_and_subdomains():
    harness = RecordingHarness()
    registry = SiteHarnessRegistry()
    registry.register(harness)

    assert registry.get_harness("example.com") is harness
    assert registry.get_harness("www.example.com") is harness
    assert registry.get_harness("https://product.example.com/path") is harness


def test_harness_registry_does_not_match_domain_spoofing():
    harness = RecordingHarness()
    registry = SiteHarnessRegistry()
    registry.register(harness)

    assert registry.get_harness("example.com.evil.test") is None


def test_harness_runner_validates_input_before_dispatch():
    harness = RecordingHarness()
    registry = SiteHarnessRegistry()
    registry.register(harness)
    runner = HarnessRunner(registry=registry, security_gate=SecurityGate(resolve_host=public_resolver))

    result = asyncio.run(runner.fetch("http://localhost/internal", "查找公开资料"))

    assert result.success is False
    assert result.errors[0].code == "host_not_allowed"
    assert harness.calls == []


def test_harness_runner_dispatches_and_normalizes_strategy():
    harness = RecordingHarness()
    registry = SiteHarnessRegistry()
    registry.register(harness)
    runner = HarnessRunner(registry=registry, security_gate=SecurityGate(resolve_host=public_resolver))

    result = asyncio.run(runner.fetch("https://www.example.com/product", "查找公开资料", allowed_domains=["example.com"]))

    assert result.success is True
    assert result.strategy_used == "harness"
    assert result.title == "Harness Product"
    assert result.steps[0].layer == "security"
    assert result.steps[1].layer == "custom"
    assert harness.calls == [("https://www.example.com/product", "查找公开资料", ["example.com"])]


def test_harness_runner_reports_missing_harness():
    runner = HarnessRunner(registry=SiteHarnessRegistry(), security_gate=SecurityGate(resolve_host=public_resolver))

    result = asyncio.run(runner.fetch("https://www.example.com/product", "查找公开资料"))

    assert result.success is False
    assert result.errors[0].code == "harness_not_found"
    assert result.strategy_used == "harness"
