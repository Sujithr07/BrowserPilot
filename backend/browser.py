import os
from playwright.async_api import async_playwright

# Realistic Chrome user agent — reduces bot detection on sites like Amazon/Flipkart
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
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
        # networkidle waits for JS-rendered content (prices, dynamic data) to finish loading
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            # Fall back to domcontentloaded if networkidle times out (e.g. live widgets)
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def click(self, selector: str):
        try:
            await self.page.click(selector)
        except Exception as e:
            raise Exception(f"Failed to click '{selector}': {e}")

    async def type_text(self, selector: str, text: str):
        try:
            await self.page.click(selector)
            await self.page.fill(selector, text)
        except Exception as e:
            raise Exception(f"Failed to type into '{selector}': {e}")

    async def scroll(self):
        await self.page.evaluate("window.scrollBy(0, 500)")

    async def extract_text(self) -> str:
        text = await self.page.inner_text("body")
        return text[:8000]

    async def take_screenshot(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await self.page.screenshot(path=path)
        return path

    async def search(self, query: str):
        encoded = query.replace(" ", "+")
        await self.navigate(f"https://www.google.com/search?q={encoded}")
