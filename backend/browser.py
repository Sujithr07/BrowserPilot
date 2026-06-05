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
        # Latest Set-of-Marks mapping {mark_id(str): {selector, tag, text, bbox}},
        # refreshed by annotate(). Used to resolve click_mark/type_mark -> element.
        self._marks: dict[str, dict] = {}

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

    # ── Set-of-Marks (SoM) grounding ─────────────────────────────────────────
    # Instead of asking the model to invent a CSS selector blind, we tag every
    # interactable element with a number, draw that number on the page, screenshot
    # it, then let the model pick a number. annotate() does the inject→shoot→clean
    # cycle; click_mark()/type_mark() resolve a number back to its element.

    # JS run in the page: tag interactable elements with data-som-mark, draw a
    # numbered box over each visible one, and return {id: {selector,tag,text,bbox}}.
    # The data-som-mark attributes are left in place (they back the selectors);
    # only the visual overlay container is removed afterwards by _DESELECT_JS.
    _ANNOTATE_JS = r"""
    () => {
      const SEL = 'a, button, input, textarea, select, [role=button], [onclick]';
      // Remove any stale overlay/attributes from a previous annotate() pass.
      const old = document.getElementById('__som_overlay__');
      if (old) old.remove();
      document.querySelectorAll('[data-som-mark]').forEach(
        e => e.removeAttribute('data-som-mark'));

      const box = document.createElement('div');
      box.id = '__som_overlay__';
      box.style.cssText =
        'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;';
      document.body.appendChild(box);

      const marks = {};
      let id = 0;
      for (const el of document.querySelectorAll(SEL)) {
        const r = el.getBoundingClientRect();
        // Skip zero-size, off-screen, or hidden elements — not clickable.
        if (r.width < 4 || r.height < 4) continue;
        if (r.bottom < 0 || r.right < 0 ||
            r.top > innerHeight || r.left > innerWidth) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none' ||
            cs.opacity === '0') continue;

        el.setAttribute('data-som-mark', id);
        const rect = document.createElement('div');
        rect.style.cssText =
          `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;` +
          `height:${r.height}px;border:2px solid #FF0080;box-sizing:border-box;`;
        const tag = document.createElement('div');
        tag.textContent = id;
        tag.style.cssText =
          `position:fixed;left:${r.left}px;top:${Math.max(0, r.top - 15)}px;` +
          'background:#FF0080;color:#fff;font:bold 12px monospace;padding:0 3px;';
        box.appendChild(rect);
        box.appendChild(tag);

        marks[id] = {
          selector: `[data-som-mark="${id}"]`,
          tag: el.tagName.toLowerCase(),
          text: (el.innerText || el.value || el.getAttribute('aria-label') ||
                 el.getAttribute('placeholder') || '').trim().slice(0, 80),
          bbox: [Math.round(r.left), Math.round(r.top),
                 Math.round(r.width), Math.round(r.height)],
        };
        id++;
      }
      return marks;
    }
    """

    _DESELECT_JS = (
        "() => { const o = document.getElementById('__som_overlay__');"
        " if (o) o.remove(); }"
    )

    async def annotate(self, path: str) -> dict:
        """
        Draw a numbered Set-of-Marks overlay, screenshot it to `path`, then strip
        the overlay. Returns (and caches on self._marks) the mark mapping
        {mark_id: {selector, tag, text, bbox}} for click_mark/type_mark to resolve.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # One dispatch keeps inject→shoot→clean atomic on the Proactor loop.
        marks = await self._dispatch(self._annotate_impl(path))
        self._marks = marks
        return marks

    async def _annotate_impl(self, path: str) -> dict:
        marks = await self.page.evaluate(self._ANNOTATE_JS)
        try:
            await self.page.screenshot(path=path)
        finally:
            # Always remove the overlay, even if the screenshot failed, so the
            # boxes never leak into a later real interaction.
            await self.page.evaluate(self._DESELECT_JS)
        return marks

    def _selector_for_mark(self, mark_id) -> str:
        """Resolve a mark number to its CSS selector, or raise a helpful error."""
        mark = self._marks.get(str(mark_id))
        if not mark:
            raise Exception(
                f"Unknown mark id {mark_id} — re-observe the page before using it"
            )
        return mark["selector"]

    async def click_mark(self, mark_id):
        await self.click(self._selector_for_mark(mark_id))

    async def type_mark(self, mark_id, text: str):
        await self.type_text(self._selector_for_mark(mark_id), text)
