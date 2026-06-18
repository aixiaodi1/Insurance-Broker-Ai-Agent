from __future__ import annotations

from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.extractor import Extractor
from app.web_acquisition.quality import score_quality
from app.web_acquisition.schemas import AcquisitionError, AcquisitionResult, AcquisitionStep, FetchResponse
from app.web_acquisition.security import SecurityGate, SecurityViolation
from app.search.safety import PromptInjectionGuard


class FastHttpFetcher:
    def __init__(
        self,
        config: WebAcquisitionConfig | None = None,
        security_gate: SecurityGate | None = None,
        transport=None,
    ) -> None:
        self.config = config or WebAcquisitionConfig()
        self.security_gate = security_gate or SecurityGate(max_redirects=self.config.max_redirects)
        self.transport = transport or self._default_transport
        self.extractor = Extractor()
        self.prompt_guard = PromptInjectionGuard()

    def fetch(self, url: str, goal: str, allowed_domains: list[str] | None = None) -> AcquisitionResult:
        started = perf_counter()
        steps = [AcquisitionStep(layer="security", action="validate", description="Validate input URL", url_before=url)]
        try:
            self.security_gate.validate_url(url, allowed_domains=allowed_domains)
            response = self.transport(url, self.config.request_timeout_seconds, self.config.max_redirects)
            self.security_gate.validate_redirect_chain(url, response.redirect_chain, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return self._failure(url, "security", exc.code, str(exc), started, steps)
        except Exception as exc:
            return self._failure(url, "http", type(exc).__name__, str(exc), started, steps)

        content_type = response.content_type
        if content_type not in self.config.allowed_content_types:
            return self._failure(url, "http", "unsupported_content_type", content_type, started, steps, final_url=response.final_url)

        steps.append(
            AcquisitionStep(
                layer="http",
                action="fetch",
                description=f"Fetched {response.final_url} with status {response.status_code}",
                url_before=url,
                url_after=response.final_url,
                metadata={"content_type": content_type},
            )
        )

        if content_type == "application/pdf":
            return AcquisitionResult(
                success=True,
                input_url=url,
                final_url=response.final_url,
                strategy_used="http",
                redirect_chain=response.redirect_chain,
                steps=steps,
                quality_score=1.0,
                duration_ms=self._duration(started),
            )

        text = response.body.decode("utf-8", errors="ignore")
        extracted = self.extractor.extract_html(text, response.final_url) if content_type == "text/html" else self.extractor.extract_text(text, response.final_url)
        injection_report = self.prompt_guard.scan(extracted.text)
        if injection_report.suspected:
            steps.append(
                AcquisitionStep(
                    layer="security",
                    action="scan_prompt_injection",
                    description="Scanned untrusted external content for prompt injection indicators",
                    url_after=response.final_url,
                    metadata={"risk_flags": injection_report.flags, "untrusted_external_content": True},
                )
            )
            return AcquisitionResult(
                success=False,
                input_url=url,
                final_url=response.final_url,
                strategy_used="http",
                redirect_chain=response.redirect_chain,
                steps=steps,
                errors=[
                    AcquisitionError(
                        code="prompt_injection_blocked",
                        message="External content was quarantined before model use",
                        layer="security",
                        url=response.final_url,
                    )
                ],
                duration_ms=self._duration(started),
            )
        quality = score_quality(extracted, threshold=self.config.quality_success_threshold)
        errors = []
        if quality.should_escalate:
            errors.append(
                AcquisitionError(
                    code="quality_too_low",
                    message="HTTP content quality is below threshold",
                    layer="http",
                    url=response.final_url,
                )
            )

        return AcquisitionResult(
            success=not quality.should_escalate,
            input_url=url,
            final_url=response.final_url,
            strategy_used="http",
            title=extracted.title,
            text=extracted.text,
            html=extracted.html,
            links=extracted.links,
            pdf_links=extracted.pdf_links,
            redirect_chain=response.redirect_chain,
            steps=steps,
            errors=errors,
            quality_score=quality.score,
            duration_ms=self._duration(started),
        )

    def _failure(
        self,
        input_url: str,
        layer: str,
        code: str,
        message: str,
        started: float,
        steps: list[AcquisitionStep],
        final_url: str = "",
    ) -> AcquisitionResult:
        return AcquisitionResult(
            success=False,
            input_url=input_url,
            final_url=final_url,
            strategy_used="http",
            steps=steps,
            errors=[AcquisitionError(code=code, message=message, layer=layer, url=input_url)],
            duration_ms=self._duration(started),
        )

    def _default_transport(self, url: str, timeout_seconds: int, max_redirects: int) -> FetchResponse:
        opener = build_opener()
        request = Request(url, headers={"User-Agent": "insurance-web-acquisition/0.1"})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read()
                final_url = response.geturl()
                headers = {key.lower(): value for key, value in response.headers.items()}
                return FetchResponse(
                    url=url,
                    final_url=final_url,
                    status_code=response.status,
                    headers=headers,
                    body=body,
                    redirect_chain=[final_url] if final_url != url else [],
                )
        except HTTPError as exc:
            body = exc.read()
            headers = {key.lower(): value for key, value in exc.headers.items()}
            return FetchResponse(url=url, final_url=exc.url, status_code=exc.code, headers=headers, body=body)
        except URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

    def _duration(self, started: float) -> int:
        return int((perf_counter() - started) * 1000)
