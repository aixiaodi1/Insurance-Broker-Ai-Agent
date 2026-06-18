from __future__ import annotations

import asyncio

from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep
from app.web_acquisition.service import WebAcquisitionService
from app.web_acquisition.storage import SQLiteAcquisitionStore


class FakeFetcher:
    def __init__(self, result: AcquisitionResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str, list[str] | None]] = []

    async def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        self.calls.append((url, goal, allowed_domains))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def result(strategy: str, success: bool, code: str = "") -> AcquisitionResult:
    errors = [AcquisitionError(code=code, message=code, layer=strategy)] if code else []
    return AcquisitionResult(
        success=success,
        input_url="https://www.example.com/product",
        final_url="https://www.example.com/product",
        strategy_used=strategy,
        steps=[AcquisitionStep(layer=strategy, action="fetch", description=f"{strategy} fetch")],
        errors=errors,
    )


def test_service_auto_stops_after_successful_http(tmp_path):
    http = FakeFetcher(result("http", True))
    playwright = FakeFetcher(result("playwright", True))
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=http,
        playwright_fetcher=playwright,
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal", allowed_domains=["example.com"]))

    assert response["status"] == "succeeded"
    assert response["result"].strategy_used == "http"
    assert http.calls == [("https://www.example.com/product", "goal", ["example.com"])]
    assert playwright.calls == []
    assert service.storage.get_task(response["task_id"])["status"] == "succeeded"


def test_service_auto_escalates_until_first_success(tmp_path):
    http = FakeFetcher(result("http", False, "quality_too_low"))
    playwright = FakeFetcher(result("playwright", False, "quality_too_low"))
    mobile = FakeFetcher(result("mobile_browser", False, "quality_too_low"))
    site_discovery = FakeFetcher(result("site_discovery", False, "sitemap_not_found"))
    search_recovery = FakeFetcher(result("search_recovery", True))
    browser_use = FakeFetcher(result("browser_use", True))
    harness = FakeFetcher(result("harness", True))
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=http,
        playwright_fetcher=playwright,
        mobile_browser_fetcher=mobile,
        site_discovery_fetcher=site_discovery,
        search_recovery_fetcher=search_recovery,
        browser_use_fetcher=browser_use,
        harness_runner=harness,
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal"))

    assert response["status"] == "succeeded"
    assert response["result"].strategy_used == "search_recovery"
    assert len(http.calls) == 1
    assert len(playwright.calls) == 1
    assert len(mobile.calls) == 1
    assert len(site_discovery.calls) == 1
    assert len(search_recovery.calls) == 1
    assert browser_use.calls == []
    assert harness.calls == []


def test_service_explicit_strategy_only_runs_matching_layer(tmp_path):
    http = FakeFetcher(result("http", True))
    playwright = FakeFetcher(result("playwright", True))
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=http,
        playwright_fetcher=playwright,
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal", strategy="playwright_only"))

    assert response["status"] == "succeeded"
    assert response["result"].strategy_used == "playwright"
    assert http.calls == []
    assert len(playwright.calls) == 1


def test_service_persists_failed_result_when_all_layers_fail(tmp_path):
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=FakeFetcher(result("http", False, "quality_too_low")),
        playwright_fetcher=FakeFetcher(result("playwright", False, "playwright_unavailable")),
        mobile_browser_fetcher=FakeFetcher(result("mobile_browser", False, "mobile_browser_unavailable")),
        site_discovery_fetcher=FakeFetcher(result("site_discovery", False, "sitemap_not_found")),
        search_recovery_fetcher=FakeFetcher(result("search_recovery", False, "no_search_candidates")),
        browser_use_fetcher=FakeFetcher(result("browser_use", False, "browser_use_unavailable")),
        harness_runner=FakeFetcher(result("harness", False, "harness_not_found")),
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal"))

    assert response["status"] == "failed"
    assert response["result"].strategy_used == "harness"
    stored = service.storage.get_task(response["task_id"])
    assert stored["status"] == "failed"
    assert stored["result"]["errors"][0]["code"] == "harness_not_found"


def test_service_explicit_new_fallback_strategies_only_run_matching_layer(tmp_path):
    mobile = FakeFetcher(result("mobile_browser", True))
    site_discovery = FakeFetcher(result("site_discovery", True))
    search_recovery = FakeFetcher(result("search_recovery", True))
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        mobile_browser_fetcher=mobile,
        site_discovery_fetcher=site_discovery,
        search_recovery_fetcher=search_recovery,
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal", strategy="site_discovery_only"))

    assert response["status"] == "succeeded"
    assert response["result"].strategy_used == "site_discovery"
    assert mobile.calls == []
    assert len(site_discovery.calls) == 1
    assert search_recovery.calls == []


def test_service_converts_unexpected_exception_to_failed_result(tmp_path):
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=FakeFetcher(RuntimeError("boom")),
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal", strategy="http_only"))

    assert response["status"] == "failed"
    assert response["result"].strategy_used == "none"
    assert response["result"].errors[0].code == "orchestration_error"
