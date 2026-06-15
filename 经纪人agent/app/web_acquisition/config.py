from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WebAcquisitionConfig:
    request_timeout_seconds: int = 10
    total_timeout_seconds: int = 90
    download_timeout_seconds: int = 30
    max_redirects: int = 5
    max_file_size_bytes: int = 50 * 1024 * 1024
    max_total_download_bytes: int = 200 * 1024 * 1024
    quality_success_threshold: float = 0.65
    downloads_dir: Path = Path("data/downloads")
    allowed_content_types: set[str] = field(
        default_factory=lambda: {
            "text/html",
            "text/plain",
            "application/json",
            "application/pdf",
        }
    )
