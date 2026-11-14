"""
scraper/browser.py — מנהל דפדפן Playwright משותף (stealth)
דפדפן אמיתי עובר את PerimeterX/אנטי-בוט של yad2 ומדלן.
Singleton: דפדפן אחד חי לכל אורך התהליך, קונטקסט חדש לכל סריקה.
"""
import asyncio
import logging
import random
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

logger = logging.getLogger("dirabot.browser")

# UA אמיתי ועדכני של Chrome על macOS
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class BrowserManager:
    """מנהל singleton לדפדפן stealth יחיד."""

    _instance: Optional["BrowserManager"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._stealth: Optional[Stealth] = None
        self._pw = None
        self._browser: Optional[Browser] = None

    @classmethod
    async def get(cls) -> "BrowserManager":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = BrowserManager()
                await cls._instance._start()
            return cls._instance

    async def _start(self):
        # stealth מותאם לישראל — עברית + פלטפורמת Mac
        self._stealth = Stealth(
            navigator_languages_override=("he-IL", "he"),
            navigator_platform_override="MacIntel",
            navigator_user_agent_override=USER_AGENT,
            init_scripts_only=True,  # רק הזרקת סקריפטים, בלי לעטוף את launch
        )
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        logger.info("🌐 Playwright chromium מוכן (stealth)")

    async def new_page(self) -> tuple[BrowserContext, Page]:
        """קונטקסט + עמוד חדש עם stealth מוזרק. סגור את הקונטקסט אחרי השימוש."""
        # עמידות: אם הדפדפן מת (קריסת דרייבר בשרת ארוך-טווח) — הקם מחדש
        if self._browser is None or not self._browser.is_connected():
            logger.warning("🔄 הדפדפן לא מחובר — מקים מחדש")
            await self._restart()
        context = await self._browser.new_context(
            user_agent=USER_AGENT,
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "he-IL,he;q=0.9,en;q=0.8"},
        )
        # הזרקת סקריפטי ה-stealth לכל עמוד בקונטקסט
        await self._stealth.apply_stealth_async(context)
        page = await context.new_page()
        return context, page

    async def _restart(self):
        """סוגר שרידים מתים ומקים דפדפן חדש (התאוששות מקריסת דרייבר)."""
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None
        await self._start()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = None
        self._pw = None
        BrowserManager._instance = None


async def human_delay(a: float = 1.0, b: float = 2.5):
    """השהיה אקראית שמחקה התנהגות אנושית."""
    await asyncio.sleep(random.uniform(a, b))
