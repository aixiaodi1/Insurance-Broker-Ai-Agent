from __future__ import annotations

import inspect
from time import perf_counter
from typing import Any

from app.web_acquisition.browser_use_fetcher import BrowserUseAgentFetcher
from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.harness import HarnessRunner, SiteHarnessRegistry
from app.web_acquisition.http_fetcher import FastHttpFetcher
from app.web_acquisition.mobile_browser_fetcher import MobileLightBrowserFetcher
from app.web_acquisition.playwright_fetcher import PlaywrightFetcher
from app.web_acquisition.search_recovery_fetcher import SearchRecoveryFetcher
from app.web_acquisition.site_discovery_fetcher import SiteDiscoveryFetcher
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep, StrategyName
from app.web_acquisition.storage import SQLiteAcquisitionStore


class WebAcquisitionService:
    def __init__(
        self,
        storage: SQLiteAcquisitionStore,
        config: WebAcquisitionConfig | None = None,
        http_fetcher: Any | None = None,
        playwright_fetcher: Any | None = None,
        mobile_browser_fetcher: Any | None = None,
        site_discovery_fetcher: Any | None = None,
        search_recovery_fetcher: Any | None = None,
        browser_use_fetcher: Any | None = None,
        harness_runner: Any | None = None,
    ) -> None:
        self.storage = storage
        self.storage.init_schema()
        self.config = config or WebAcquisitionConfig()
        self.http_fetcher = http_fetcher or FastHttpFetcher(config=self.config)
        self.playwright_fetcher = playwright_fetcher or PlaywrightFetcher(config=self.config)
        self.mobile_browser_fetcher = mobile_browser_fetcher or MobileLightBrowserFetcher(PlaywrightFetcher(config=self.config))
        self.site_discovery_fetcher = site_discovery_fetcher or SiteDiscoveryFetcher(candidate_fetcher=FastHttpFetcher(config=self.config))
        self.search_recovery_fetcher = search_recovery_fetcher or SearchRecoveryFetcher(candidate_fetcher=FastHttpFetcher(config=self.config))
        self.browser_use_fetcher = browser_use_fetcher or BrowserUseAgentFetcher(config=self.config)
        self.harness_runner = harness_runner or HarnessRunner(SiteHarnessRegistry())

    async def acquire(
        self,
        url: str,
        goal: str,
        allowed_domains: list[str] | None = None,
        strategy: StrategyName = "auto",
        max_steps: int = 20,
        timeout_seconds: int = 90,
    ) -> dict:
        self.config.browser_use_max_steps = max_steps
        self.config.total_timeout_seconds = timeout_seconds
        task_id = self.storage.create_task(url, goal, allowed_domains, strategy)
        started = perf_counter()
        try:
            result = await self._run_strategy(url, goal, allowed_domains, strategy)
        except Exception as exc:
            result = self._orchestration_failure(url, exc, started)
        status = "succeeded" if result.success else "failed"
        self.storage.finish_task(task_id, status, result)
        return {"task_id": task_id, "status": status, "result": result}

    async def _run_strategy(
        self,
        url: str,
        goal: str,
        allowed_domains: list[str] | None,
        strategy: StrategyName,
    ) -> AcquisitionResult:
        if strategy == "auto":
            final_result: AcquisitionResult | None = None
            for fetcher in (
                self.http_fetcher,
                self.playwright_fetcher,
                self.mobile_browser_fetcher,
                self.site_discovery_fetcher,
                self.search_recovery_fetcher,
                self.browser_use_fetcher,
                self.harness_runner,
            ):
                final_result = await self._fetch(fetcher, url, goal, allowed_domains)
                if final_result.success:
                    return final_result
            if final_result is None:
                return self._invalid_strategy(url, "auto")
            return final_result

        fetcher = {
            "http_only": self.http_fetcher,
            "playwright_only": self.playwright_fetcher,
            "mobile_browser_only": self.mobile_browser_fetcher,
            "site_discovery_only": self.site_discovery_fetcher,
            "search_recovery_only": self.search_recovery_fetcher,
            "browser_use_only": self.browser_use_fetcher,
            "harness_only": self.harness_runner,
        }.get(strategy)
        if fetcher is None:
            return self._invalid_strategy(url, strategy)
        return await self._fetch(fetcher, url, goal, allowed_domains)

    async def _fetch(self, fetcher: Any, url: str, goal: str, allowed_domains: list[str] | None) -> AcquisitionResult:
        return await self._maybe_await(fetcher.fetch(url, goal, allowed_domains=allowed_domains))

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    def _invalid_strategy(self, url: str, strategy: str) -> AcquisitionResult:
        return AcquisitionResult(
            success=False,
            input_url=url,
            strategy_used="none",
            errors=[AcquisitionError(code="invalid_strategy", message=f"Unsupported strategy: {strategy}", layer="service", url=url)],
        )

    def _orchestration_failure(self, url: str, exc: Exception, started: float) -> AcquisitionResult:
        return AcquisitionResult(
            success=False,
            input_url=url,
            strategy_used="none",
            steps=[AcquisitionStep(layer="service", action="orchestrate", description="Run acquisition strategy")],
            errors=[AcquisitionError(code="orchestration_error", message=str(exc), layer="service", url=url)],
            duration_ms=int((perf_counter() - started) * 1000),
        )
