"""
scraper/yad2.py — Scraper ליד2 מבוסס Playwright (stealth)
עובר את אנטי-הבוט של Radware דרך דפדפן אמיתי, ואז קורא ל-feed API
הפנימי מתוך הקונטקסט (עם ה-cookies התקינים).
מזהה ערים דינמית דרך autocomplete — בלי מיפוי קשיח שמתיישן.
"""
import asyncio
import json
import logging
import urllib.parse
from typing import Optional

from .base import BaseScraper, Listing
from .browser import BrowserManager, human_delay

logger = logging.getLogger("dirabot.yad2")

AUTOCOMPLETE_URL = "https://gw.yad2.co.il/address-autocomplete/realestate/v2"
FEED_URL = "https://gw.yad2.co.il/realestate-feed/rent/feed"
ITEM_BASE = "https://www.yad2.co.il/realestate/item"

# מטמון זיהוי ערים לכל התהליך
_city_cache: dict[str, dict] = {}


class Yad2Scraper(BaseScraper):
    name = "yad2"

    async def fetch_listings(self) -> list[Listing]:
        locations = self.search_config.get("locations", ["תל אביב יפו"])
        bm = await BrowserManager.get()
        context, page = await bm.new_page()
        listings: list[Listing] = []
        try:
            # warmup — מעבר אתגר Radware וקבלת cookies
            await page.goto("https://www.yad2.co.il/", wait_until="domcontentloaded", timeout=45000)
            await human_delay(3, 5)

            for location in locations:
                try:
                    geo = await self._resolve_location(page, location)
                    if not geo:
                        logger.warning(f"Yad2: לא זוהה המיקום '{location}'")
                        continue
                    items = await self._fetch_feed(page, geo)
                    for raw in items:
                        lst = self._parse_item(raw)
                        if lst and self._in_range(lst):
                            listings.append(lst)
                    await human_delay(1.5, 3.0)
                except Exception as e:
                    logger.error(f"Yad2 error for {location}: {e}")
        finally:
            await context.close()

        logger.info(f"Yad2: {len(listings)} מודעות רלוונטיות")
        return listings[:self.max_listings]

    async def _resolve_location(self, page, location: str) -> Optional[dict]:
        """
        שם מיקום → פרמטרי feed דרך autocomplete (עם מטמון).
        מזהה אוטומטית אם זו עיר או אזור:
        - עיר מדויקת (הרצליה)  → {'city': cityId, 'region': regionId}
        - אזור (עמק חפר)        → {'area': areaId, 'region': regionId}
        """
        if location in _city_cache:
            return _city_cache[location]
        url = f"{AUTOCOMPLETE_URL}?text={urllib.parse.quote(location)}"
        data = await self._page_json(page, url)
        if not data:
            return None

        norm = location.strip()
        geo: Optional[dict] = None

        # 1) עיר מדויקת — שם העיר זהה בדיוק לשאילתה (הרצליה → city, לא area)
        for c in data.get("cities", []):
            if c.get("fullTitleText", "").strip() == norm:
                geo = {"city": c.get("cityId"), "region": c.get("regionId")}
                break

        # 2) אזור מפורש שתואם בדיוק לשאילתה
        if not geo:
            for a in data.get("areas", []):
                if a.get("fullTitleText", "").strip() == norm:
                    geo = {"area": a.get("areaId"), "region": a.get("regionId")}
                    break

        # 3) גיבוי — אין התאמה מדויקת (כמו 'עמק חפר'/'לב שרון'): חיפוש ברמת
        #    האזור לפי ה-areaId המשותף לתוצאות הקרובות ביותר
        if not geo:
            ref = (data.get("cities") or data.get("hoods") or [])
            if ref:
                r0 = ref[0]
                if r0.get("areaId"):
                    geo = {"area": r0.get("areaId"), "region": r0.get("regionId")}
                elif r0.get("cityId"):
                    geo = {"city": r0.get("cityId"), "region": r0.get("regionId")}

        if geo and geo.get("region"):
            _city_cache[location] = geo
            level = "אזור" if "area" in geo else "עיר"
            logger.info(f"Yad2: '{location}' זוהה כ{level} ({geo})")
            return geo
        return None

    async def _fetch_feed(self, page, geo: dict) -> list[dict]:
        """מושך עד max_listings מודעות (עם דפדוף). הסינון לפי מחיר/חדרים
        נעשה קשיח בצד הלקוח (ה-feed מתעלם מפרמטרי price/rooms)."""
        results: list[dict] = []
        pages_needed = max(1, (self.max_listings // 40) + 1)
        for pg in range(1, pages_needed + 1):
            params = {**geo, "page": pg}  # city/area + region
            url = f"{FEED_URL}?{urllib.parse.urlencode(params)}"
            data = await self._page_json(page, url)
            if not data:
                break
            d = data.get("data", {})
            batch = (d.get("private", []) or []) + (d.get("agency", []) or [])
            if not batch:
                break
            results.extend(batch)
            if len(results) >= self.max_listings:
                break
            await human_delay(1.0, 2.0)
        return results

    @staticmethod
    async def _page_json(page, url: str) -> Optional[dict]:
        """fetch same-origin מתוך הדפדפן (נושא cookies), מחזיר JSON או None."""
        res = await page.evaluate(
            """async (u) => {
                try {
                    const r = await fetch(u, {headers: {'accept': 'application/json'}, credentials: 'include'});
                    if (r.status !== 200) return {__err: r.status};
                    return await r.json();
                } catch (e) { return {__err: String(e)}; }
            }""",
            url,
        )
        if isinstance(res, dict) and "__err" in res:
            logger.debug(f"Yad2 fetch {url[:60]} → {res['__err']}")
            return None
        return res

    def _in_range(self, l: Listing) -> bool:
        """סינון קשיח: מחיר בטווח, חדרים בטווח (± חצי חדר), ומצב הנכס אם נדרש."""
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
        # דרישת חובה: דירה חדשה/משופצת בלבד
        if self.search_config.get("require_renovated", False) and not l.is_renovated:
            return False
        return True

    def _parse_item(self, item: dict) -> Optional[Listing]:
        try:
            addr = item.get("address", {})
            details = item.get("additionalDetails", {})
            meta = item.get("metaData", {})
            house = addr.get("house", {})

            token = item.get("token", "")
            if not token:
                return None
            url = f"{ITEM_BASE}/{token}"

            # מאפיינים + טקסט לחיפוש מילות מפתח מתוך התגים
            tag_names = [t.get("name", "") for t in item.get("tags", [])]
            tags_text = " ".join(tag_names)
            prop = details.get("property", {}).get("text", "דירה")
            street = addr.get("street", {}).get("text", "")
            neighborhood = addr.get("neighborhood", {}).get("text", "")
            title = f"{prop} ב{street}".strip() if street else prop
            description = " • ".join(filter(None, [neighborhood, tags_text]))

            # מצב הנכס: 1=חדש מקבלן, 2=חדש, 3=משופץ → נחשב "חדשה/משופצת"
            cond_id = details.get("propertyCondition", {}).get("id")
            is_renovated = cond_id in (1, 2, 3)

            listing = Listing(
                url=url,
                source="yad2",
                title=title,
                city=addr.get("city", {}).get("text", ""),
                neighborhood=neighborhood,
                price=item.get("price"),
                rooms=details.get("roomsCount"),
                floor=house.get("floor"),
                size_sqm=details.get("squareMeter") or meta.get("squareMeterBuild"),
                has_elevator="מעלית" in tags_text,
                has_parking="חניה" in tags_text or "חנייה" in tags_text,
                has_balcony="מרפסת" in tags_text,
                has_mamad='ממ"ד' in tags_text or "ממד" in tags_text,
                is_renovated=is_renovated,
                description=description,
                image_url=meta.get("coverImage", ""),
                location_matched=True,  # סוננה כבר לפי city/area ב-API
            )
            listing.score = self.score_listing(listing)
            return listing
        except Exception as e:
            logger.debug(f"Yad2 parse error: {e}")
            return None
