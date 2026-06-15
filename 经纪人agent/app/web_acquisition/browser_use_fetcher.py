from __future__ import annotations

import inspect
from time import perf_counter
from typing import Any

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.downloader import Downloader
from app.web_acquisition.extractor import classify_document
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep, DiscoveredLink, DownloadedFile
from app.web_acquisition.security import SecurityGate, SecurityViolation


BROWSER_USE_PUBLIC_SYSTEM_INSTRUCTION = """
你只负责查找公开可访问的保险产品资料。
允许：打开公开页面、滚动、点击下载/查看/条款/说明书/信息披露/费率/现金价值等公开资料入口。
禁止：登录、注册、购买、投保、支付、提交表单、填写验证码、联系在线客服、进入个人中心或处理任何非公开账户流程。
如果遇到禁止动作或需要登录/验证码才能继续，立即停止并报告。
""".strip()


class BrowserUseAgentFetcher:
    def __init__(
        self,
        config: WebAcquisitionConfig | None = None,
        security_gate: SecurityGate | None = None,
        agent_runner: Any | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        self.config = config or WebAcquisitionConfig()
        self.security_gate = security_gate or SecurityGate(max_redirects=self.config.max_redirects)
        self.agent_runner = agent_runner
        self.downloader = downloader

    async def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="security", action="validate", description="Validate input URL", url_before=url)]
        try:
            check = self.security_gate.validate_url(url, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return self._failure(url, exc.code, str(exc), "security", started, steps)

        if self.agent_runner is None:
            return self._failure(url, "browser_use_unavailable", "No browser-use runner is configured", "browser_use", started, steps)

        task = self._build_task(check.normalized_url, goal)
        try:
            raw_result = await self._maybe_await(self.agent_runner(task))
        except Exception as exc:
            return self._failure(url, "browser_use_unavailable", str(exc), "browser_use", started, steps)

        if not isinstance(raw_result, dict):
            return self._failure(url, "invalid_browser_use_result", "Runner returned a non-dict result", "browser_use", started, steps)

        final_url = str(raw_result.get("final_url") or check.normalized_url)
        errors: list[AcquisitionError] = []
        try:
            self.security_gate.validate_url(final_url, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            errors.append(AcquisitionError(code=exc.code, message=str(exc), layer="security", url=final_url))
            final_url = check.normalized_url

        actions = self._as_list(raw_result.get("actions"))
        errors.extend(self._limit_errors(actions, raw_result, final_url))
        for action in actions:
            step = self._action_to_step(action, final_url)
            steps.append(step)
            if self._has_blocked_action(step.description):
                errors.append(
                    AcquisitionError(
                        code="blocked_action_reported",
                        message=f"Browser-use runner reported blocked action: {step.description}",
                        layer="browser_use",
                        url=step.url_after or final_url,
                    )
                )

        links, link_errors = self._documents_to_links(raw_result.get("documents"), final_url, allowed_domains)
        errors.extend(link_errors)
        pdf_links = [link for link in links if self._looks_pdf(link.url)]
        downloaded_files = self._download_pdfs(pdf_links, allowed_domains)

        return AcquisitionResult(
            success=not errors,
            input_url=url,
            final_url=final_url,
            strategy_used="browser_use",
            title=str(raw_result.get("title") or ""),
            text=str(raw_result.get("text") or ""),
            links=links,
            pdf_links=pdf_links,
            downloaded_files=downloaded_files,
            steps=steps,
            errors=errors,
            quality_score=1.0 if links else 0.0,
            duration_ms=self._duration(started),
        )

    def _build_task(self, url: str, goal: str) -> dict[str, Any]:
        return {
            "url": url,
            "goal": goal,
            "system_instruction": BROWSER_USE_PUBLIC_SYSTEM_INSTRUCTION,
            "limits": {
                "max_steps": self.config.browser_use_max_steps,
                "max_navigations": self.config.browser_use_max_navigations,
                "max_clicks": self.config.browser_use_max_clicks,
                "max_runtime_seconds": self.config.browser_use_max_runtime_seconds,
            },
            "allowed_actions": list(self.config.allowed_click_texts),
            "blocked_actions": list(self.config.blocked_click_texts),
        }

    def _documents_to_links(
        self,
        documents: Any,
        source_page: str,
        allowed_domains: list[str] | None,
    ) -> tuple[list[DiscoveredLink], list[AcquisitionError]]:
        links: list[DiscoveredLink] = []
        errors: list[AcquisitionError] = []
        seen: set[str] = set()
        for document in self._as_list(documents):
            if not isinstance(document, dict):
                continue
            raw_url = str(document.get("url") or "")
            if not raw_url:
                continue
            try:
                check = self.security_gate.validate_url(raw_url, allowed_domains=allowed_domains)
            except SecurityViolation as exc:
                errors.append(AcquisitionError(code=exc.code, message=str(exc), layer="security", url=raw_url))
                continue
            if check.normalized_url in seen:
                continue
            seen.add(check.normalized_url)
            text = str(document.get("text") or document.get("title") or "")
            classified = classify_document(text, check.normalized_url)
            links.append(
                DiscoveredLink(
                    url=check.normalized_url,
                    text=text,
                    document_type=classified.document_type,
                    confidence=classified.confidence,
                    source="browser_use",
                    source_page=source_page,
                )
            )
        return links, errors

    def _action_to_step(self, action: Any, final_url: str) -> AcquisitionStep:
        if not isinstance(action, dict):
            return AcquisitionStep(layer="browser_use", action="observe", description=str(action), url_after=final_url)
        action_type = str(action.get("type") or action.get("action") or "action")
        description = str(action.get("text") or action.get("description") or action_type)
        return AcquisitionStep(
            layer="browser_use",
            action=action_type,
            description=description,
            url_before=str(action.get("url_before") or ""),
            url_after=str(action.get("url_after") or final_url),
            metadata={key: value for key, value in action.items() if key not in {"type", "action", "text", "description", "url_before", "url_after"}},
        )

    def _limit_errors(self, actions: list[Any], raw_result: dict[str, Any], final_url: str) -> list[AcquisitionError]:
        click_count = sum(1 for action in actions if self._action_type(action) == "click")
        navigation_count = sum(1 for action in actions if self._action_type(action) in {"navigate", "goto", "open"})
        runtime_seconds = raw_result.get("runtime_seconds")
        breaches: list[str] = []
        if len(actions) > self.config.browser_use_max_steps:
            breaches.append(f"steps={len(actions)}>{self.config.browser_use_max_steps}")
        if click_count > self.config.browser_use_max_clicks:
            breaches.append(f"clicks={click_count}>{self.config.browser_use_max_clicks}")
        if navigation_count > self.config.browser_use_max_navigations:
            breaches.append(f"navigations={navigation_count}>{self.config.browser_use_max_navigations}")
        if isinstance(runtime_seconds, (int, float)) and runtime_seconds > self.config.browser_use_max_runtime_seconds:
            breaches.append(f"runtime_seconds={runtime_seconds}>{self.config.browser_use_max_runtime_seconds}")
        if not breaches:
            return []
        return [
            AcquisitionError(
                code="browser_use_limit_exceeded",
                message="Browser-use runner exceeded configured limits: " + ", ".join(breaches),
                layer="browser_use",
                url=final_url,
            )
        ]

    def _action_type(self, action: Any) -> str:
        if not isinstance(action, dict):
            return ""
        return str(action.get("type") or action.get("action") or "").lower()

    def _download_pdfs(self, pdf_links: list[DiscoveredLink], allowed_domains: list[str] | None) -> list[DownloadedFile]:
        if self.downloader is None:
            return []
        downloaded: list[DownloadedFile] = []
        for link in pdf_links:
            outcome = self.downloader.download(link.url, allowed_domains=allowed_domains)
            if outcome.file is not None:
                downloaded.append(outcome.file)
        return downloaded

    def _has_blocked_action(self, text: str) -> bool:
        normalized = text.strip().lower()
        return any(blocked.lower() in normalized for blocked in self.config.blocked_click_texts)

    def _looks_pdf(self, url: str) -> bool:
        return ".pdf" in url.lower().split("?", 1)[0]

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

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
            strategy_used="browser_use",
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
