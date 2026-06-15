from __future__ import annotations

import asyncio

from app.web_acquisition.browser_use_fetcher import BrowserUseAgentFetcher
from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.schemas import DownloadedFile, FetchResponse
from app.web_acquisition.security import SecurityGate


class RecordingRunner:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def __call__(self, task: dict) -> dict:
        self.calls.append(task)
        return self.response


class StaticDownloader:
    def __init__(self) -> None:
        self.downloaded_urls: list[str] = []

    def download(self, url: str, allowed_domains: list[str] | None = None):
        self.downloaded_urls.append(url)
        return type(
            "Outcome",
            (),
            {
                "file": DownloadedFile(
                    source_url=url,
                    final_url=url,
                    file_path="data/downloads/example.pdf",
                    filename="example.pdf",
                    content_type="application/pdf",
                    size_bytes=5,
                    sha256="abc123",
                )
            },
        )()


def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def test_browser_use_fetcher_builds_constrained_public_material_task():
    runner = RecordingRunner(
        {
            "final_url": "https://www.example.com/product",
            "title": "Example Product",
            "text": "保险 产品 条款 现金价值 产品说明书",
            "documents": [
                {"url": "https://www.example.com/product/clause.pdf", "text": "产品条款"},
                {"url": "https://www.example.com/product/rate.pdf", "text": "费率表"},
            ],
            "actions": [
                {"type": "navigate", "url_before": "", "url_after": "https://www.example.com/product"},
                {"type": "click", "text": "下载产品条款"},
            ],
        }
    )
    downloader = StaticDownloader()
    fetcher = BrowserUseAgentFetcher(
        config=WebAcquisitionConfig(browser_use_max_steps=7, browser_use_max_clicks=3),
        security_gate=SecurityGate(resolve_host=public_resolver),
        agent_runner=runner,
        downloader=downloader,
    )

    result = asyncio.run(fetcher.fetch("https://www.example.com/product", "找到公开保险资料"))

    assert result.success is True
    assert result.strategy_used == "browser_use"
    assert result.final_url == "https://www.example.com/product"
    assert [link.text for link in result.pdf_links] == ["产品条款", "费率表"]
    assert [file.filename for file in result.downloaded_files] == ["example.pdf", "example.pdf"]
    assert len(result.steps) == 3
    task = runner.calls[0]
    assert task["url"] == "https://www.example.com/product"
    assert task["goal"] == "找到公开保险资料"
    assert task["limits"]["max_steps"] == 7
    assert task["limits"]["max_clicks"] == 3
    assert task["allowed_actions"]
    assert "登录" in task["blocked_actions"]
    assert "公开" in task["system_instruction"]
    assert downloader.downloaded_urls == [
        "https://www.example.com/product/clause.pdf",
        "https://www.example.com/product/rate.pdf",
    ]


def test_browser_use_fetcher_rejects_blocked_reported_actions():
    runner = RecordingRunner(
        {
            "final_url": "https://www.example.com/product",
            "title": "Example Product",
            "actions": [{"type": "click", "text": "立即投保"}],
            "documents": [{"url": "https://www.example.com/product/clause.pdf", "text": "产品条款"}],
        }
    )
    fetcher = BrowserUseAgentFetcher(security_gate=SecurityGate(resolve_host=public_resolver), agent_runner=runner)

    result = asyncio.run(fetcher.fetch("https://www.example.com/product", "找到公开保险资料"))

    assert result.success is False
    assert result.errors[0].code == "blocked_action_reported"
    assert result.errors[0].layer == "browser_use"


def test_browser_use_fetcher_rejects_runner_limit_overflow():
    runner = RecordingRunner(
        {
            "final_url": "https://www.example.com/product",
            "actions": [
                {"type": "click", "text": "下载产品条款"},
                {"type": "click", "text": "下载费率表"},
            ],
            "documents": [{"url": "https://www.example.com/product/clause.pdf", "text": "产品条款"}],
        }
    )
    fetcher = BrowserUseAgentFetcher(
        config=WebAcquisitionConfig(browser_use_max_clicks=1),
        security_gate=SecurityGate(resolve_host=public_resolver),
        agent_runner=runner,
    )

    result = asyncio.run(fetcher.fetch("https://www.example.com/product", "找到公开保险资料"))

    assert result.success is False
    assert result.errors[0].code == "browser_use_limit_exceeded"


def test_browser_use_fetcher_rejects_unsafe_input_before_runner():
    runner = RecordingRunner({})
    fetcher = BrowserUseAgentFetcher(security_gate=SecurityGate(resolve_host=public_resolver), agent_runner=runner)

    result = asyncio.run(fetcher.fetch("http://localhost/internal", "找到公开保险资料"))

    assert result.success is False
    assert result.errors[0].code == "host_not_allowed"
    assert runner.calls == []


def test_browser_use_fetcher_reports_runner_unavailable():
    def broken_runner(task: dict) -> dict:
        raise RuntimeError("browser-use not installed")

    fetcher = BrowserUseAgentFetcher(security_gate=SecurityGate(resolve_host=public_resolver), agent_runner=broken_runner)

    result = asyncio.run(fetcher.fetch("https://www.example.com/product", "找到公开保险资料"))

    assert result.success is False
    assert result.errors[0].code == "browser_use_unavailable"
