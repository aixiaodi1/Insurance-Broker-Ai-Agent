import asyncio

from app.web_acquisition.config import WebAcquisitionConfig
from app.web_acquisition.downloader import DownloadOutcome
from app.web_acquisition.playwright_fetcher import PlaywrightFetcher
from app.web_acquisition.schemas import DownloadedFile
from app.web_acquisition.security import SecurityGate


class FakePage:
    def __init__(self) -> None:
        self.html = """
        <html><head><title>动态产品资料</title></head><body>
          <main>保险 产品 条款 费率 现金价值 信息披露 """ + ("保险责任 " * 80) + """</main>
          <a href="/initial.pdf">产品条款</a>
          <button data-selector="download-doc">下载</button>
          <button data-selector="login">登录</button>
        </body></html>
        """
        self.goto_calls: list[str] = []
        self.clicked: list[str] = []
        self.scrolled = False

    async def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.goto_calls.append(url)

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        return None

    async def evaluate(self, script: str) -> None:
        if "scroll" in script.lower():
            self.scrolled = True

    async def title(self) -> str:
        return "动态产品资料"

    async def content(self) -> str:
        return self.html

    async def inner_text(self, selector: str) -> str:
        return "保险 产品 条款 费率 现金价值 信息披露 " + ("保险责任 " * 80)

    async def candidate_elements(self):
        return [
            {"selector": "button[data-selector='download-doc']", "text": "下载"},
            {"selector": "button[data-selector='login']", "text": "登录"},
        ]

    async def click(self, selector: str, timeout: int) -> None:
        self.clicked.append(selector)
        if "download-doc" in selector:
            self.html = self.html.replace("</body>", '<a href="/clicked-rate.pdf">费率表 PDF</a></body>')


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def new_page(self) -> FakePage:
        return self.page


class FakePool:
    def __init__(self, page: FakePage | None = None, error: Exception | None = None) -> None:
        self.page = page or FakePage()
        self.error = error

    def borrow_context(self):
        pool = self

        class Lease:
            async def __aenter__(self):
                if pool.error:
                    raise pool.error
                return FakeContext(pool.page)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return Lease()


class FakeDownloader:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def download(self, url: str, allowed_domains=None):
        self.urls.append(url)
        return DownloadOutcome(
            file=DownloadedFile(
                source_url=url,
                final_url=url,
                file_path="data/downloads/aa/fake.pdf",
                filename="fake.pdf",
                content_type="application/pdf",
                size_bytes=7,
                sha256="abc123",
            )
        )


def test_playwright_fetcher_renders_scrolls_clicks_safe_candidates_and_downloads_pdfs():
    page = FakePage()
    downloader = FakeDownloader()
    fetcher = PlaywrightFetcher(
        config=WebAcquisitionConfig(),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        browser_pool=FakePool(page),
        downloader=downloader,
    )

    result = asyncio.run(fetcher.fetch("https://example.com/product", goal="find docs", allowed_domains=["example.com"]))

    assert result.success is True
    assert result.strategy_used == "playwright"
    assert page.goto_calls == ["https://example.com/product"]
    assert page.scrolled is True
    assert page.clicked == ["button[data-selector='download-doc']"]
    assert any(step.action == "click" and step.metadata["text"] == "下载" for step in result.steps)
    assert "https://example.com/clicked-rate.pdf" in {item.url for item in result.pdf_links}
    assert "https://example.com/clicked-rate.pdf" in downloader.urls
    assert result.downloaded_files


def test_playwright_fetcher_returns_unavailable_error_when_pool_fails():
    fetcher = PlaywrightFetcher(
        config=WebAcquisitionConfig(),
        security_gate=SecurityGate(resolve_host=lambda host: ["93.184.216.34"]),
        browser_pool=FakePool(error=RuntimeError("browser missing")),
    )

    result = asyncio.run(fetcher.fetch("https://example.com/product", goal="find docs", allowed_domains=["example.com"]))

    assert result.success is False
    assert result.strategy_used == "playwright"
    assert result.errors[0].code == "playwright_unavailable"
