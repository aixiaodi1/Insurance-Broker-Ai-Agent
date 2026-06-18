from __future__ import annotations

from app.web_acquisition.playwright_fetcher import PlaywrightFetcher
from app.web_acquisition.schemas import AcquisitionStep


class MobileLightBrowserFetcher:
    def __init__(self, delegate: PlaywrightFetcher | None = None) -> None:
        self.delegate = delegate or PlaywrightFetcher()

    async def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None):
        result = await self.delegate.fetch(url, goal, allowed_domains=allowed_domains)
        result.strategy_used = "mobile_browser"
        result.steps.append(
            AcquisitionStep(
                layer="mobile_browser",
                action="retry",
                description="Retried page with the mobile-light browser fallback",
                url_before=url,
                url_after=result.final_url or url,
                metadata={"profile": "mobile_light"},
            )
        )
        for error in result.errors:
            if error.layer == "playwright":
                error.layer = "mobile_browser"
        return result
