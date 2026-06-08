import os
import sys
import asyncio
import threading
from playwright.async_api import async_playwright, Error as PlaywrightError

from backend import config
from backend.logging_config import get_logger
from backend.resilience import RetryPolicy, CircuitBreaker, call_resilient

log = get_logger("agentflow.browser")

# Realistic Chrome user agent — reduces bot detection on sites like Amazon/Flipkart
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_CONTEXT_KWARGS = dict(
    user_agent=_USER_AGENT,
    viewport={"width": 1280, "height": 800},
    locale="en-US",
)
# Hide the navigator.webdriver flag that sites check for bot detection.
_STEALTH_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"

# Resilience for the NETWORK layer only (navigation). The two-tier
# networkidle->domcontentloaded fallback below is now formalized as a retried,
# breaker-protected operation. Page actions (click/type) are intentionally NOT
# retried here: Playwright already waits/auto-retries for an element, and a wrong
# selector would otherwise burn another full timeout. LLM retries live in llm.py.
_NAV_POLICY = RetryPolicy(
    attempts=int(os.getenv("NAV_RETRY_ATTEMPTS", "2")),
    base_delay=0.8,
    max_delay=5.0,
    retry_on=(PlaywrightError, asyncio.TimeoutError),
)
# Process-wide: protects a wedged browser/site from being hammered by every task.
_NAV_BREAKER = CircuitBreaker(
    "browser.navigate",
    failure_threshold=int(os.getenv("NAV_BREAKER_THRESHOLD", "8")),
    reset_timeout=float(os.getenv("NAV_BREAKER_RESET_S", "20")),
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


def _needs_proactor_thread() -> bool:
    """True when the running loop can't spawn subprocesses (Windows + Selector)."""
    if sys.platform != "win32":
        return False  # SelectorEventLoop supports subprocesses on POSIX
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        return True
    # ProactorEventLoop already supports subprocesses — no thread needed.
    return not isinstance(running, asyncio.ProactorEventLoop)


class _PageSession:
    """
    Page-level browser operations shared by the standalone ``BrowserManager`` and
    the pooled ``LeasedBrowser``.

    The owner supplies a ``self.page`` (a Playwright Page) and an async
    ``_dispatch(coro)`` that runs Playwright coroutines on the correct event loop
    (the private Proactor loop on Windows, else the caller's loop). All the public
    actions the executor uses live here, so both the per-task and pooled paths
    behave identically.
    """

    def __init__(self):
        self.page = None
        # Latest Set-of-Marks mapping {mark_id(str): {selector, tag, text, bbox}},
        # refreshed by annotate(). Used to resolve click_mark/type_mark -> element.
        self._marks: dict[str, dict] = {}

    async def _dispatch(self, coro):  # pragma: no cover - overridden by owner
        raise NotImplementedError

    # ── Navigation (resilient: retry + circuit breaker around the network) ────
    async def navigate(self, url: str):
        await call_resilient(
            lambda: self._dispatch(self._navigate_impl(url)),
            policy=_NAV_POLICY,
            breaker=_NAV_BREAKER,
            name=f"navigate:{url}",
        )

    async def _navigate_impl(self, url: str):
        # networkidle waits for JS-rendered content (prices, dynamic data) to load.
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            # Fall back to domcontentloaded if networkidle times out (e.g. live widgets).
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
    _ANNOTATE_JS = r"""
    () => {
      // A click may have just triggered a navigation; if the new document hasn't
      // parsed its <body> yet, bail with no marks instead of throwing on
      // appendChild. annotate() waits for the DOM first, this is the backstop.
      if (!document.body) return {};
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
        # A preceding click can leave the page mid-navigation, where the new
        # document has no <body> yet and the overlay injection would throw
        # "Cannot read properties of null (reading 'appendChild')". Wait for the
        # DOM to settle (and for <body> to exist) before annotating; both waits
        # are best-effort so a quiet page or already-loaded state never blocks.
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        try:
            await self.page.wait_for_selector("body", timeout=5000)
        except Exception:
            pass
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


class BrowserManager(_PageSession):
    """
    Standalone, single-context browser (one per task). Unchanged external API —
    used by the in-process path (USE_QUEUE=0) and the eval harness. The pooled
    path uses BrowserPool + LeasedBrowser instead.
    """

    def __init__(self):
        super().__init__()
        self.playwright = None
        self.browser = None
        self.context = None
        # A dedicated Proactor loop thread when the running loop can't spawn
        # subprocesses (Windows + SelectorEventLoop), else None.
        self._loop_thread: _ProactorLoopThread | None = None

    async def _dispatch(self, coro):
        if self._loop_thread is not None:
            return await self._loop_thread.run(coro)
        return await coro

    async def start(self):
        if _needs_proactor_thread():
            self._loop_thread = _ProactorLoopThread()
        await self._dispatch(self._start_impl())

    async def _start_impl(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=config.BROWSER_HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(**_CONTEXT_KWARGS)
        await self.context.add_init_script(_STEALTH_INIT)
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
