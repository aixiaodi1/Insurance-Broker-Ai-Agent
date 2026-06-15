from __future__ import annotations

import inspect
from time import perf_counter
from typing import Any

from app.web_acquisition.browser_pool import BrowserPool, BrowserPoolUnavailable
from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.downloader import Downloader
from app.web_acquisition.extractor import Extractor
from app.web_acquisition.quality import score_quality
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep, DownloadedFile
from app.web_acquisition.security import SecurityGate, SecurityViolation


class PlaywrightFetcher:
    def __init__(
        self,
        config: WebAcquisitionConfig | None = None,
        security_gate: SecurityGate | None = None,
        browser_pool: Any | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        self.config = config or WebAcquisitionConfig()
        self.security_gate = security_gate or SecurityGate(max_redirects=self.config.max_redirects)
        self.browser_pool = browser_pool or BrowserPool(pool_size=self.config.browser_pool_size)
        self.downloader = downloader
        self.extractor = Extractor()

    async def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="security", action="validate", description="Validate input URL", url_before=url)]
        try:
            self.security_gate.validate_url(url, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return self._failure(url, exc.code, str(exc), "security", started, steps)

        try:
            async with self.browser_pool.borrow_context() as context:
                page = await self._maybe_await(context.new_page())
                await self._open_and_render(page, url, steps)
                await self._click_safe_candidates(page, url, steps)
                extracted = await self._extract(page, url)
        except (BrowserPoolUnavailable, RuntimeError) as exc:
            return self._failure(url, "playwright_unavailable", str(exc), "playwright", started, steps)
        except Exception as exc:
            return self._failure(url, type(exc).__name__, str(exc), "playwright", started, steps)

        quality = score_quality(extracted, threshold=self.config.quality_success_threshold)
        errors = []
        if quality.should_escalate:
            errors.append(
                AcquisitionError(
                    code="quality_too_low",
                    message="Rendered content quality is below threshold",
                    layer="playwright",
                    url=url,
                )
            )

        downloaded_files = self._download_pdfs(extracted.pdf_links, allowed_domains)
        return AcquisitionResult(
            success=not quality.should_escalate,
            input_url=url,
            final_url=url,
            strategy_used="playwright",
            title=extracted.title,
            text=extracted.text,
            html=extracted.html,
            links=extracted.links,
            pdf_links=extracted.pdf_links,
            downloaded_files=downloaded_files,
            steps=steps,
            errors=errors,
            quality_score=quality.score,
            duration_ms=self._duration(started),
        )

    async def _open_and_render(self, page: Any, url: str, steps: list[AcquisitionStep]) -> None:
        await self._maybe_await(page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout_seconds * 1000))
        steps.append(AcquisitionStep(layer="playwright", action="goto", description="Opened page", url_before=url, url_after=url))
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if callable(wait_for_load_state):
            await self._maybe_await(wait_for_load_state("networkidle", timeout=10_000))
            steps.append(AcquisitionStep(layer="playwright", action="wait", description="Waited for bounded network idle", url_after=url))
        evaluate = getattr(page, "evaluate", None)
        if callable(evaluate):
            await self._maybe_await(evaluate("window.scrollTo(0, document.body.scrollHeight)"))
            steps.append(AcquisitionStep(layer="playwright", action="scroll", description="Scrolled to trigger lazy loading", url_after=url))

    async def _click_safe_candidates(self, page: Any, source_url: str, steps: list[AcquisitionStep]) -> None:
        candidate_elements = getattr(page, "candidate_elements", None)
        if not callable(candidate_elements):
            return
        candidates = await self._maybe_await(candidate_elements())
        for candidate in candidates[:10]:
            text = str(candidate.get("text") or "")
            selector = str(candidate.get("selector") or "")
            if not selector or not self._is_allowed_click(text):
                continue
            await self._maybe_await(page.click(selector, timeout=self.config.step_timeout_seconds * 1000))
            steps.append(
                AcquisitionStep(
                    layer="playwright",
                    action="click",
                    description="Clicked safe candidate",
                    url_before=source_url,
                    url_after=source_url,
                    metadata={"selector": selector, "text": text},
                )
            )

    async def _extract(self, page: Any, source_url: str):
        html = await self._maybe_await(page.content())
        extracted = self.extractor.extract_html(html, source_url)
        title = await self._maybe_await(page.title())
        if title:
            extracted.title = str(title)
        inner_text = getattr(page, "inner_text", None)
        if callable(inner_text):
            text = await self._maybe_await(inner_text("body"))
            if text:
                extracted.text = str(text)
        return extracted

    def _download_pdfs(self, pdf_links, allowed_domains: list[str] | None) -> list[DownloadedFile]:
        if self.downloader is None:
            return []
        downloaded: list[DownloadedFile] = []
        for link in pdf_links:
            outcome = self.downloader.download(link.url, allowed_domains=allowed_domains)
            if outcome.file is not None:
                downloaded.append(outcome.file)
        return downloaded

    def _is_allowed_click(self, text: str) -> bool:
        normalized = text.strip().lower()
        if any(blocked.lower() in normalized for blocked in self.config.blocked_click_texts):
            return False
        return any(allowed.lower() in normalized for allowed in self.config.allowed_click_texts)

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
            strategy_used="playwright",
            steps=steps,
            errors=[AcquisitionError(code=code, message=message, layer=layer, url=input_url)],
            duration_ms=self._duration(started),
        )

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    def _duration(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)
