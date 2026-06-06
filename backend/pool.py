"""
BrowserPool: pre-warm N Chromium contexts behind one browser process and lend
them to tasks via an async context manager, instead of launching a whole browser
per task.

Why contexts, not browsers: a Playwright BrowserContext is an isolated session
(own cookies/storage) but shares the single Chromium process — far cheaper to
pre-warm and reuse than a fresh browser launch each task.

Windows note: every Playwright call still goes through ONE shared
_ProactorLoopThread (the same mechanism BrowserManager uses), so subprocess
launch keeps working under uvicorn/arq Selector loops. The lend/return queue
lives on the caller's loop; only the Playwright coroutines hop to the Proactor
loop via `_dispatch`.
"""
import asyncio
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright

from backend import config
from backend.browser import (
    _PageSession,
    _ProactorLoopThread,
    _needs_proactor_thread,
    _CONTEXT_KWARGS,
    _STEALTH_INIT,
)
from backend.logging_config import get_logger

log = get_logger("agentflow.pool")


class LeasedBrowser(_PageSession):
    """A single pooled context+page exposing the full _PageSession action API.

    Dispatches Playwright work onto the pool's shared Proactor loop. Lifecycle
    (create/close) is owned by the pool, so it has no start()/stop() of its own.
    """

    def __init__(self, pool: "BrowserPool", context, page, index: int):
        super().__init__()
        self._pool = pool
        self.context = context
        self.page = page
        self.index = index

    async def _dispatch(self, coro):
        return await self._pool._dispatch(coro)

    async def _reset_impl(self):
        """Wipe session state so the next task starts clean but warm."""
        try:
            await self.context.clear_cookies()
            await self.page.goto("about:blank")
        except Exception as e:  # best-effort; a wedged page is replaced lazily
            log.warning("pool.reset_failed", extra={"index": self.index, "error": str(e)})


class BrowserPool:
    def __init__(self, size: int | None = None):
        self.size = size or config.BROWSER_POOL_SIZE
        self.playwright = None
        self.browser = None
        self._loop_thread: _ProactorLoopThread | None = None
        self._available: asyncio.Queue[LeasedBrowser] | None = None
        self._all: list[LeasedBrowser] = []
        self._started = False
        self._closing = False

    async def _dispatch(self, coro):
        if self._loop_thread is not None:
            return await self._loop_thread.run(coro)
        return await coro

    async def start(self):
        """Launch one browser and pre-warm `size` contexts."""
        if self._started:
            return
        if _needs_proactor_thread():
            self._loop_thread = _ProactorLoopThread()
        self._available = asyncio.Queue()
        await self._dispatch(self._start_impl())
        self._started = True
        log.info("pool.started", extra={"size": self.size, "headless": config.BROWSER_HEADLESS})

    async def _start_impl(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=config.BROWSER_HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        for i in range(self.size):
            ctx = await self.browser.new_context(**_CONTEXT_KWARGS)
            await ctx.add_init_script(_STEALTH_INIT)
            page = await ctx.new_page()
            leased = LeasedBrowser(self, ctx, page, i)
            self._all.append(leased)
            self._available.put_nowait(leased)

    @asynccontextmanager
    async def acquire(self, timeout: float | None = None):
        """
        Lend a warmed browser; return it (reset) on exit. Blocks up to `timeout`
        seconds when all contexts are in use, bounding concurrency to pool size.
        """
        if not self._started:
            raise RuntimeError("BrowserPool.start() must be called before acquire()")
        if self._closing:
            raise RuntimeError("BrowserPool is shutting down")
        wait = config.POOL_ACQUIRE_TIMEOUT if timeout is None else timeout
        leased = await asyncio.wait_for(self._available.get(), timeout=wait)
        log.info("pool.acquired", extra={"index": leased.index,
                                         "available": self._available.qsize()})
        try:
            yield leased
        finally:
            # Reset on the Proactor loop, then make it lendable again.
            await self._dispatch(leased._reset_impl())
            leased._marks = {}
            self._available.put_nowait(leased)
            log.info("pool.released", extra={"index": leased.index,
                                             "available": self._available.qsize()})

    async def stop(self):
        """Close every context, the browser, and the shared Proactor loop."""
        if not self._started:
            return
        self._closing = True
        await self._dispatch(self._stop_impl())
        if self._loop_thread is not None:
            self._loop_thread.shutdown()
            self._loop_thread = None
        self._started = False
        log.info("pool.stopped", extra={"size": self.size})

    async def _stop_impl(self):
        for leased in self._all:
            try:
                await leased.context.close()
            except Exception:
                pass
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self._all.clear()
        self.browser = None
        self.playwright = None
