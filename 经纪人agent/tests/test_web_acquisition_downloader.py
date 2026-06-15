import hashlib

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.downloader import Downloader
from app.web_acquisition.schemas import FetchResponse
from app.web_acquisition.security import SecurityGate


def test_downloader_saves_pdf_by_sha256_and_deduplicates(tmp_path):
    body = b"%PDF-1.4\nsample"
    expected_sha = hashlib.sha256(body).hexdigest()

    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "application/pdf"},
            body=body,
        )

    config = WebAcquisitionConfig(downloads_dir=tmp_path)
    downloader = Downloader(config=config, security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]), transport=transport)

    first = downloader.download("https://example.com/a.pdf", allowed_domains=["example.com"])
    second = downloader.download("https://example.com/a.pdf", allowed_domains=["example.com"])

    assert first.sha256 == expected_sha
    assert second.sha256 == expected_sha
    assert first.file_path == second.file_path
    assert (tmp_path / expected_sha[:2] / f"{expected_sha}.pdf").exists()


def test_downloader_rejects_unsupported_content_type(tmp_path):
    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(url=url, final_url=url, status_code=200, headers={"content-type": "text/html"}, body=b"<html></html>")

    downloader = Downloader(
        config=WebAcquisitionConfig(downloads_dir=tmp_path),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = downloader.download("https://example.com/a.html", allowed_domains=["example.com"])

    assert result.error_code == "unsupported_content_type"


def test_downloader_rejects_file_size_limit(tmp_path):
    def transport(url, timeout_seconds, max_redirects):
        return FetchResponse(url=url, final_url=url, status_code=200, headers={"content-type": "application/pdf"}, body=b"x" * 12)

    downloader = Downloader(
        config=WebAcquisitionConfig(downloads_dir=tmp_path, max_file_size_bytes=10),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        transport=transport,
    )

    result = downloader.download("https://example.com/big.pdf", allowed_domains=["example.com"])

    assert result.error_code == "file_too_large"
