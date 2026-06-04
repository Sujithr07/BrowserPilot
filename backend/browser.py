import os
import sys
import asyncio
import threading
from playwright.async_api import async_playwright

# Realistic Chrome user agent — reduces bot detection on sites like Amazon/Flipkart
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class _ProactorLoopThread:
    """
    Runs an asyncio ProactorEventLoop on a dedicated daemon thread.

    On Windows, Playwright needs to spawn its browser as a subprocess, which is
    only supported on a ProactorEventLoop. But uvicorn runs its worker on a
    SelectorEventLoop whenever it uses subprocess mode (``--reload`` or
    ``--workers``), and SelectorEventLoop raises a bare ``NotImplementedError``
    on ``create_subprocess_exec``. To stay launch-mode agnostic we run every
    Playwright coroutine on this private Proactor loop instead of the request's
    loop.
    """

    def __init__(self):
        self.loop = asyncio.ProactorEventLoop()
        self._thread = threading.Thread(
            target=self._run, name="playwright-proactor", daemon=True
        )
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def run(self, coro):
        """Schedule a coroutine on the Proactor loop and await it from the caller's loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return await asyncio.wrap_future(future)

    def shutdown(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        # Set lazily in start(): a dedicated Proactor loop thread when the running
        # loop can't spawn subprocesses (Windows + SelectorEventLoop), else None
        # and we run Playwright directly on the caller's loop.
        self._loop_thread: _ProactorLoopThread | None = None

    async def _dispatch(self, coro):
        """Run a Playwright coroutine on the right loop (private Proactor thread or current)."""
        if self._loop_thread is not None:
            return await self._loop_thread.run(coro)
        return await coro

    @staticmethod
    def _needs_proactor_thread() -> bool:
        if sys.platform != "win32":
            return False  # SelectorEventLoop supports subprocesses on POSIX
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return True
        # ProactorEventLoop already supports subprocesses — no thread needed.
        return not isinstance(running, asyncio.ProactorEventLoop)

    async def start(self):
        if self._needs_proactor_thread():
            self._loop_thread = _ProactorLoopThread()
        await self._dispatch(self._start_impl())

    async def _start_impl(self):
        self.playwright = await async_playwright().start()
        # headless=False: far less detectable than headless=True on major e-commerce sites
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        # Hide the navigator.webdriver flag that sites check for bot detection
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self.page = await self.context.new_page()

    async def stop(self):
        await self._dispatch(self._stop_impl())
        if self._loop_thread is not None:
            self._loop_thread.shutdown()
            self._loop_thread = None

    async def _stop_impl(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def navigate(self, url: str):
        await self._dispatch(self._navigate_impl(url))

    async def _navigate_impl(self, url: str):
        # networkidle waits for JS-rendered content (prices, dynamic data) to finish loading
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            # Fall back to domcontentloaded if networkidle times out (e.g. live widgets)
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def click(self, selector: str):
        await self._dispatch(self._click_impl(selector))

    async def _click_impl(self, selector: str):
        try:
            await self.page.click(selector)
        except Exception as e:
            raise Exception(f"Failed to click '{selector}': {e}")

    async def type_text(self, selector: str, text: str):
        await self._dispatch(self._type_text_impl(selector, text))

    async def _type_text_impl(self, selector: str, text: str):
        try:
            # First try direct fill (works when click is blocked by overlays).
            # If that fails, fall back to click + fill.
            try:
                await self.page.fill(selector, text)
            except Exception:
                await self.page.click(selector)
                await self.page.fill(selector, text)
        except Exception as e:
            raise Exception(f"Failed to type into '{selector}': {e}")

    async def scroll(self):
        await self._dispatch(self._scroll_impl())

    async def _scroll_impl(self):
        await self.page.evaluate("window.scrollBy(0, 500)")

    async def extract_text(self) -> str:
        return await self._dispatch(self._extract_text_impl())

    async def _extract_text_impl(self) -> str:
        text = await self.page.inner_text("body")
        return text[:8000]

    async def take_screenshot(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await self._dispatch(self._screenshot_impl(path))
        return path

    async def _screenshot_impl(self, path: str):
        await self.page.screenshot(path=path)

    async def search(self, query: str):
        # DuckDuckGo's HTML endpoint returns a clean, automation-friendly results
        # page. Google blocks headful automation and renders its search box as a
        # <textarea>, so typing/clicking there times out — DDG avoids both issues.
        encoded = query.replace(" ", "+")
        await self.navigate(f"https://duckduckgo.com/html/?q={encoded}")
