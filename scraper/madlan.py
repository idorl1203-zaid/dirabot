"""
scraper/madlan.py — Scraper למדלן מבוסס Playwright (stealth)
מדלן מוגן ב-PerimeterX ולעיתים חוסם — לכן זהו מקור *משני* best-effort:
מנסה עם retry/reload, מחלץ מה-DOM המרונדר, ומתדרדר בחן (מחזיר [])
אם נחסם, כדי לא לשבור את הצנרת. yad2 הוא המקור הראשי האמין.
"""
import asyncio
import logging
import re
import urllib.parse

from .base import BaseScraper, Listing
from .browser import BrowserManager, human_delay

logger = logging.getLogger("dirabot.madlan")

CARD_SEL = "[data-auto=listed-bulletin]"
SEARCH_BASE = "https://www.madlan.co.il/for-rent"


class MadlanScraper(BaseScraper):
    name = "madlan"

    async def fetch_listings(self) -> list[Listing]:
        locations = self.search_config.get("locations", ["תל אביב יפו"])
        bm = await BrowserManager.get()
        context, page = await bm.new_page()
        listings: list[Listing] = []
        try:
            # warmup — דף הבית קודם לקבלת cookies ומעבר אתגר PerimeterX
            try:
                await page.goto("https://www.madlan.co.il/", wait_until="domcontentloaded", timeout=45000)
                await human_delay(4, 6)
            except Exception:
                pass

            for location in locations:
                try:
                    items = await self._fetch_location(page, location)
                    for raw in items:
                        lst = self._parse_card(raw, location)
                        if lst and self._in_range(lst):
                            listings.append(lst)
                    await human_delay(2.0, 4.0)
                except Exception as e:
                    logger.error(f"Madlan error for {location}: {e}")
        finally:
            await context.close()

        logger.info(f"Madlan: {len(listings)} מודעות רלוונטיות")
        return listings[:self.max_listings]

    async def _fetch_location(self, page, location: str) -> list[dict]:
        """טוען דף חיפוש, עם עד 3 ניסיונות לעבור את אתגר PerimeterX."""
        slug = urllib.parse.quote(f"{location}-ישראל")
        url = f"{SEARCH_BASE}/{slug}"
        for attempt in range(3):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            try:
                await page.wait_for_selector(CARD_SEL, timeout=15000)
                break  # כרטיסים נטענו
            except Exception:
                title = await page.title()
                logger.debug(f"Madlan attempt {attempt}: '{title}' — לא נטענו כרטיסים")
                await human_delay(2.0, 4.0)
        else:
            logger.warning(f"Madlan: נחסם עבור '{location}' (PerimeterX) — מדלג")
            return []

        # חילוץ הכרטיסים מה-DOM המרונדר
        cards = await page.evaluate(
            """(sel) => Array.from(document.querySelectorAll(sel)).slice(0, 60).map(c => {
                const a = c.querySelector('a[href]');
                const img = c.querySelector('img');
                return {
                    id: c.getAttribute('data-auto-bulletin-id'),
                    href: a ? a.getAttribute('href') : null,
                    img: img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '',
                    text: c.textContent.trim().replace(/\\s+/g, ' '),
                };
            })""",
            CARD_SEL,
        )
        return cards

    def _parse_card(self, card: dict, location: str) -> Listing | None:
        text = card.get("text", "")
        if not text:
            return None

        cid = card.get("id") or ""
        href = card.get("href") or ""
        if href.startswith("/"):
            url = "https://www.madlan.co.il" + href
        elif href.startswith("http"):
            url = href
        elif cid:
            url = f"https://www.madlan.co.il/listings/{cid}"
        else:
            return None

        # מחיר: המספר שלפני ₪
        price = None
        m = re.search(r"([\d,]{3,})\s*₪", text)
        if m:
            price = int(m.group(1).replace(",", ""))

        # חדרים: "X חדרים" / "X חד'"
        rooms = None
        m = re.search(r"(\d+\.?\d*)\s*חדר", text)
        if m:
            rooms = float(m.group(1))

        # שטח: "X מ״ר" / "X מ\"ר"
        size = None
        m = re.search(r"(\d{2,3})\s*מ[\"״'ר]", text)
        if m:
            size = int(m.group(1))

        listing = Listing(
            url=url,
            source="madlan",
            title=text[:60],
            city=location,
            neighborhood="",
            price=price,
            rooms=rooms,
            floor=None,
            size_sqm=size,
            has_elevator="מעלית" in text,
            has_parking="חניה" in text or "חנייה" in text,
            has_balcony="מרפסת" in text,
            has_mamad='ממ"ד' in text or "ממד" in text,
            description=text[:200],
            image_url=card.get("img", ""),
            location_matched=True,  # סוננה כבר לפי location בחיפוש
        )
        listing.score = self.score_listing(listing)
        return listing

    def _in_range(self, l: Listing) -> bool:
        price = self.search_config.get("price", {})
        rooms = self.search_config.get("rooms", {})
        if l.price is not None:
            if price.get("min") and l.price < price["min"]:
                return False
            if price.get("max") and l.price > price["max"]:
                return False
        if l.rooms is not None:
            if rooms.get("min") and l.rooms < rooms["min"] - 0.5:
                return False
            if rooms.get("max") and l.rooms > rooms["max"] + 0.5:
                return False
        return True
