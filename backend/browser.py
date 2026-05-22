import os
from playwright.async_api import async_playwright


class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.page = None
        self.browser = None
        self.playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def navigate(self, url: str):
        await self.page.goto(url, wait_until="load")

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
        return text[:3000]

    async def take_screenshot(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await self.page.screenshot(path=path)
        return path

    async def search(self, query: str):
        encoded = query.replace(" ", "+")
        await self.navigate(f"https://www.google.com/search?q={encoded}")
