from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable


class BrowserPoolUnavailable(RuntimeError):
    def __init__(self, message: str, code: str = "playwright_unavailable") -> None:
        super().__init__(message)
        self.code = code


class BrowserPool:
    def __init__(
        self,
        pool_size: int = 1,
        browser_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.pool_size = max(1, pool_size)
        self.browser_factory = browser_factory or self._missing_factory
        self._browsers: list[Any] = []
        self._next_index = 0
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        try:
            for _ in range(self.pool_size):
                self._browsers.append(await self._maybe_await(self.browser_factory()))
        except Exception as exc:
            self._browsers.clear()
            raise BrowserPoolUnavailable(str(exc)) from exc
        self._started = True

    @asynccontextmanager
    async def borrow_context(self) -> AsyncIterator[Any]:
        if not self._started:
            await self.start()
        browser = self._borrow_browser()
        context = await self._maybe_await(browser.new_context())
        try:
            yield context
        finally:
            await self._cleanup_context(context)

    async def close(self) -> None:
        for browser in self._browsers:
            close = getattr(browser, "close", None)
            if callable(close):
                await self._maybe_await(close())
        self._browsers.clear()
        self._started = False

    def health_check(self) -> dict[str, Any]:
        return {
            "available": self._started and bool(self._browsers),
            "pool_size": len(self._browsers),
        }

    def _borrow_browser(self) -> Any:
        if not self._browsers:
            raise BrowserPoolUnavailable("No browser instances are available")
        browser = self._browsers[self._next_index % len(self._browsers)]
        self._next_index += 1
        return browser

    async def _cleanup_context(self, context: Any) -> None:
        clear_cookies = getattr(context, "clear_cookies", None)
        if callable(clear_cookies):
            await self._maybe_await(clear_cookies())
        close = getattr(context, "close", None)
        if callable(close):
            await self._maybe_await(close())

    async def _missing_factory(self) -> Any:
        raise RuntimeError("Playwright browser factory is not configured")

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value
