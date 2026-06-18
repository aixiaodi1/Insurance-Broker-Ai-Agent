from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StrategyName = Literal[
    "auto",
    "http_only",
    "playwright_only",
    "mobile_browser_only",
    "site_discovery_only",
    "search_recovery_only",
    "browser_use_only",
    "harness_only",
]
StrategyUsed = Literal["http", "playwright", "mobile_browser", "site_discovery", "search_recovery", "browser_use", "harness", "none"]


@dataclass(slots=True)
class AcquisitionStep:
    layer: str
    action: str
    description: str
    url_before: str | None = None
    url_after: str | None = None
    screenshot_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AcquisitionError:
    code: str
    message: str
    layer: str
    url: str | None = None


@dataclass(slots=True)
class DiscoveredLink:
    url: str
    text: str = ""
    document_type: str = "unknown"
    confidence: float = 0.0
    source: str = "unknown"
    source_page: str = ""


@dataclass(slots=True)
class DownloadedFile:
    source_url: str
    final_url: str
    file_path: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


@dataclass(slots=True)
class ExtractedContent:
    title: str = ""
    text: str = ""
    html: str = ""
    links: list[DiscoveredLink] = field(default_factory=list)
    pdf_links: list[DiscoveredLink] = field(default_factory=list)
    document_links: list[DiscoveredLink] = field(default_factory=list)
    iframe_links: list[DiscoveredLink] = field(default_factory=list)
    script_candidate_links: list[DiscoveredLink] = field(default_factory=list)
    button_candidate_links: list[DiscoveredLink] = field(default_factory=list)


@dataclass(slots=True)
class FetchResponse:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        raw = self.headers.get("content-type") or self.headers.get("Content-Type") or ""
        return raw.split(";", 1)[0].strip().lower()


@dataclass(slots=True)
class AcquisitionResult:
    success: bool
    input_url: str
    final_url: str = ""
    strategy_used: StrategyUsed = "none"
    title: str = ""
    text: str = ""
    html: str = ""
    links: list[DiscoveredLink] = field(default_factory=list)
    pdf_links: list[DiscoveredLink] = field(default_factory=list)
    downloaded_files: list[DownloadedFile] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    redirect_chain: list[str] = field(default_factory=list)
    steps: list[AcquisitionStep] = field(default_factory=list)
    errors: list[AcquisitionError] = field(default_factory=list)
    quality_score: float = 0.0
    duration_ms: int = 0
