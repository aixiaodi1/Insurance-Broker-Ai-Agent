import asyncio

import pytest

from app.web_acquisition.browser_pool import BrowserPool, BrowserPoolUnavailable


class FakeContext:
    def __init__(self) -> None:
        self.cookies_cleared = False
        self.closed = False

    async def clear_cookies(self) -> None:
        self.cookies_cleared = True

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.closed = False

    async def new_context(self) -> FakeContext:
        context = FakeContext()
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True


def test_browser_pool_borrows_context_and_cleans_it_on_release():
    created: list[FakeBrowser] = []

    async def run_test():
        async def factory():
            browser = FakeBrowser()
            created.append(browser)
            return browser

        pool = BrowserPool(pool_size=1, browser_factory=factory)
        await pool.start()
        async with pool.borrow_context() as context:
            assert isinstance(context, FakeContext)
            assert context.closed is False

        assert context.cookies_cleared is True
        assert context.closed is True
        assert len(created) == 1
        await pool.close()
        assert created[0].closed is True

    asyncio.run(run_test())


def test_browser_pool_reuses_started_browser_for_multiple_contexts():
    created: list[FakeBrowser] = []

    async def run_test():
        async def factory():
            browser = FakeBrowser()
            created.append(browser)
            return browser

        pool = BrowserPool(pool_size=1, browser_factory=factory)
        await pool.start()
        async with pool.borrow_context():
            pass
        async with pool.borrow_context():
            pass

        assert len(created) == 1
        assert len(created[0].contexts) == 2
        assert pool.health_check()["available"] is True
        await pool.close()

    asyncio.run(run_test())


def test_browser_pool_raises_structured_unavailable_error():
    async def run_test():
        async def factory():
            raise RuntimeError("playwright not installed")

        pool = BrowserPool(pool_size=1, browser_factory=factory)
        with pytest.raises(BrowserPoolUnavailable) as exc:
            await pool.start()

        assert exc.value.code == "playwright_unavailable"
        assert "playwright not installed" in str(exc.value)

    asyncio.run(run_test())
