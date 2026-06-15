from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.schemas import DownloadedFile, FetchResponse
from app.web_acquisition.security import SecurityGate, SecurityViolation


@dataclass(slots=True)
class DownloadOutcome:
    file: DownloadedFile | None = None
    error_code: str | None = None
    error_message: str = ""

    def __getattr__(self, name: str):
        if self.file is not None and hasattr(self.file, name):
            return getattr(self.file, name)
        raise AttributeError(name)


class Downloader:
    def __init__(
        self,
        config: WebAcquisitionConfig | None = None,
        security_gate: SecurityGate | None = None,
        transport=None,
    ) -> None:
        self.config = config or WebAcquisitionConfig()
        self.security_gate = security_gate or SecurityGate(max_redirects=self.config.max_redirects)
        self.transport = transport or self._default_transport
        self._task_downloaded_bytes = 0

    def download(self, url: str, allowed_domains: list[str] | None = None) -> DownloadOutcome:
        try:
            self.security_gate.validate_url(url, allowed_domains=allowed_domains)
            response = self.transport(url, self.config.download_timeout_seconds, self.config.max_redirects)
            self.security_gate.validate_redirect_chain(url, response.redirect_chain, allowed_domains=allowed_domains)
        except SecurityViolation as exc:
            return DownloadOutcome(error_code=exc.code, error_message=str(exc))
        except Exception as exc:
            return DownloadOutcome(error_code=type(exc).__name__, error_message=str(exc))

        if response.content_type != "application/pdf":
            return DownloadOutcome(error_code="unsupported_content_type", error_message=response.content_type)

        size = len(response.body)
        if size > self.config.max_file_size_bytes:
            return DownloadOutcome(error_code="file_too_large", error_message=str(size))
        if self._task_downloaded_bytes + size > self.config.max_total_download_bytes:
            return DownloadOutcome(error_code="task_download_limit_exceeded", error_message=str(size))

        digest = hashlib.sha256(response.body).hexdigest()
        directory = Path(self.config.downloads_dir) / digest[:2]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.pdf"
        if not path.exists():
            path.write_bytes(response.body)
        self._task_downloaded_bytes += size

        downloaded = DownloadedFile(
            source_url=url,
            final_url=response.final_url,
            file_path=str(path),
            filename=path.name,
            content_type=response.content_type,
            size_bytes=size,
            sha256=digest,
        )
        return DownloadOutcome(file=downloaded)

    def _default_transport(self, url: str, timeout_seconds: int, max_redirects: int) -> FetchResponse:
        request = Request(url, headers={"User-Agent": "insurance-web-acquisition/0.1"})
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(self.config.max_file_size_bytes + 1)
            return FetchResponse(
                url=url,
                final_url=response.geturl(),
                status_code=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
                redirect_chain=[response.geturl()] if response.geturl() != url else [],
            )
