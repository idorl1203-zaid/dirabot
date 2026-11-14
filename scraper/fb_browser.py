"""
scraper/fb_browser.py — session קבוע לפייסבוק (חשבון משני)
מתחברים פעם אחת בחלון אמיתי (fb_login.py), וה-session נשמר בתיקיית פרופיל
קבועה. הסקרייפר משתמש חוזר באותו פרופיל — בלי צורך להתחבר שוב.

⚠️ מפר את תנאי השימוש של פייסבוק. להשתמש רק בחשבון משני/נפרד.
"""
import logging
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext
from playwright_stealth import Stealth

logger = logging.getLogger("dirabot.fb")

# תיקיית הפרופיל הקבוע (מכילה cookies/session — רגיש, לא עולה ל-git)
FB_PROFILE_DIR = Path(__file__).parent.parent / ".fb_profile"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_stealth = Stealth(
    navigator_languages_override=("he-IL", "he"),
    navigator_platform_override="MacIntel",
    navigator_user_agent_override=UA,
    init_scripts_only=True,
)


async def open_fb_context(headless: bool = True):
    """
    פותח קונטקסט קבוע (persistent) של פייסבוק עם ה-session השמור.
    מחזיר (playwright, context). סגור את שניהם אחרי השימוש.
    שים לב: הפרופיל נעול לתהליך אחד בכל רגע — אל תריץ login וסריקה במקביל.
    """
    FB_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    ctx: BrowserContext = await pw.chromium.launch_persistent_context(
        user_data_dir=str(FB_PROFILE_DIR),
        headless=headless,
        user_agent=UA,
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
        viewport={"width": 1440, "height": 900},
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    await _stealth.apply_stealth_async(ctx)
    return pw, ctx


async def is_logged_in(ctx: BrowserContext) -> bool:
    """בודק אם ה-session מחובר (יש cookie של c_user)."""
    cookies = await ctx.cookies("https://www.facebook.com")
    return any(c["name"] == "c_user" for c in cookies)
