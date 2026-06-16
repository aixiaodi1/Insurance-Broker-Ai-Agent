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
    browser_use = FakeFetcher(result("browser_use", True))
    harness = FakeFetcher(result("harness", True))
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=http,
        playwright_fetcher=playwright,
        browser_use_fetcher=browser_use,
        harness_runner=harness,
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal"))

    assert response["status"] == "succeeded"
    assert response["result"].strategy_used == "browser_use"
    assert len(http.calls) == 1
    assert len(playwright.calls) == 1
    assert len(browser_use.calls) == 1
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
        browser_use_fetcher=FakeFetcher(result("browser_use", False, "browser_use_unavailable")),
        harness_runner=FakeFetcher(result("harness", False, "harness_not_found")),
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal"))

    assert response["status"] == "failed"
    assert response["result"].strategy_used == "harness"
    stored = service.storage.get_task(response["task_id"])
    assert stored["status"] == "failed"
    assert stored["result"]["errors"][0]["code"] == "harness_not_found"


def test_service_converts_unexpected_exception_to_failed_result(tmp_path):
    service = WebAcquisitionService(
        storage=SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3"),
        http_fetcher=FakeFetcher(RuntimeError("boom")),
    )

    response = asyncio.run(service.acquire("https://www.example.com/product", "goal", strategy="http_only"))

    assert response["status"] == "failed"
    assert response["result"].strategy_used == "none"
    assert response["result"].errors[0].code == "orchestration_error"
