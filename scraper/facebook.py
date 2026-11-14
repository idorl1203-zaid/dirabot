"""
scraper/facebook.py — סורק את הפיד המאוחד של הקבוצות (/groups/feed/)
מגלגל, מחלץ פוסטים, מסנן רק דירות רלוונטיות, ומזין לאותה צנרת.

⚠️ מפר את תנאי השימוש של פייסבוק. חשבון משני בלבד.
"""
import asyncio
import logging
import re

from .base import BaseScraper, Listing
from .fb_browser import open_fb_context, is_logged_in

logger = logging.getLogger("dirabot.facebook")

JOINS_URL = "https://www.facebook.com/groups/joins/"
GROUP_URL = "https://www.facebook.com/groups/{gid}"

# מילים לזיהוי קבוצת דירות (לפי שם הקבוצה)
GROUP_KW = ["דיר", "השכר", "שכיר", "נדל", "דיור"]
# מילים שמעידות שזה פוסט של דירה להשכרה
APARTMENT_KW = ["להשכרה", "להשכיר", "משכיר", "דירה", "דירת", "שכירות", "חדרים", "חד'"]
# רעש UI לניקוי מהטקסט
UI_NOISE = ["Reply", "See translation", "Share", "See more", "Like", "Comment",
            "Follow", "Author", "Active", "· ", "Most relevant"]


class FacebookScraper(BaseScraper):
    name = "facebook"

    async def fetch_listings(self) -> list[Listing]:
        scroll_count = self.scan_config.get("fb_scroll_count", 4)
        max_groups = self.scan_config.get("fb_max_groups", 8)
        pw, ctx = await open_fb_context(headless=True)
        listings: list[Listing] = []
        seen_posts: set[str] = set()
        try:
            if not await is_logged_in(ctx):
                logger.warning("Facebook: לא מחובר — הרץ python fb_login.py")
                return []
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            # קבוצות מוגדרות ידנית, או גילוי אוטומטי של קבוצות דירות
            groups = self.scan_config.get("fb_groups") or await self._discover_groups(page)
            groups = groups[:max_groups]
            logger.info(f"Facebook: סורק {len(groups)} קבוצות")

            for g in groups:
                gid = g["id"] if isinstance(g, dict) else g
                gname = g.get("name", "") if isinstance(g, dict) else ""
                try:
                    await page.goto(GROUP_URL.format(gid=gid), wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(6)  # פייסבוק טוען פוסטים לאט
                    for _ in range(scroll_count):
                        await page.mouse.wheel(0, 2200)
                        await asyncio.sleep(3.0)
                    raw = await page.evaluate(self._EXTRACT_JS)
                    new = 0
                    for p in raw:
                        if p["postId"] in seen_posts:
                            continue
                        seen_posts.add(p["postId"])
                        lst = self._parse_post(p, gname)
                        if lst and self._in_range(lst):
                            listings.append(lst)
                            new += 1
                    logger.info(f"  [{gname[:25] or gid}] {len(raw)} פוסטים, {new} דירות")
                    await asyncio.sleep(2)  # נשימה בין קבוצות
                except Exception as e:
                    logger.error(f"  קבוצה {gid} נכשלה: {e}")
        except Exception as e:
            logger.error(f"Facebook error: {e}")
        finally:
            await ctx.close()
            await pw.stop()

        logger.info(f"Facebook: {len(listings)} דירות רלוונטיות מ-{len(seen_posts)} פוסטים")
        return listings[:self.max_listings]

    async def _discover_groups(self, page) -> list[dict]:
        """גילוי אוטומטי של קבוצות הדירות שהמשתמש חבר בהן."""
        await page.goto(JOINS_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(4)
        for _ in range(5):
            await page.mouse.wheel(0, 2200)
            await asyncio.sleep(1.6)
        groups = await page.evaluate("""() => {
            const seen = {}, out = [];
            document.querySelectorAll('a[href*="/groups/"]').forEach(a => {
                const m = (a.getAttribute('href') || '').match(/\\/groups\\/(\\d+)(?:\\/|$|\\?)/);
                let name = (a.innerText || '').trim();
                if (m && name && name.length > 2 && !seen[m[1]]) {
                    seen[m[1]] = 1;
                    out.push({ id: m[1], name });
                }
            });
            return out;
        }""")
        apt = [g for g in groups if any(k in g["name"] for k in GROUP_KW)]
        logger.info(f"Facebook: זוהו {len(apt)} קבוצות דירות (מתוך {len(groups)})")
        return apt

    # חילוץ מבוסס קישורי-פוסט (עמיד יותר מ-[role=article] שמתרנדר עצל).
    # מוצא כל קישור /posts/{id}, מטפס למצוא את גוף הפוסט, מחלץ טקסט+תמונה.
    _EXTRACT_JS = r"""
    () => {
      const out = [];
      const seen = new Set();
      document.querySelectorAll('a[href*="/posts/"]').forEach(a => {
        const h = a.getAttribute('href') || '';
        const m = h.match(/\/groups\/(\d+)\/posts\/(\d+)/);
        if (!m) return;
        const groupId = m[1], postId = m[2];
        if (seen.has(postId)) return;
        // מטפס למעלה עד מיכל הפוסט (role=article) או הכי גדול עם טקסט
        let node = a, article = null;
        for (let i = 0; i < 15 && node; i++) {
          if (node.getAttribute && node.getAttribute('role') === 'article') { article = node; break; }
          node = node.parentElement;
        }
        const box = article || a.closest('div');
        const text = box ? (box.innerText || '') : '';
        if (text.length < 25) return;   // מדלג על קישורים ריקים
        seen.add(postId);
        const img = box ? box.querySelector('img[src*="scontent"]') : null;
        out.push({
          postId, groupId,
          url: 'https://www.facebook.com/groups/' + groupId + '/posts/' + postId + '/',
          text: text,
          img: img ? img.getAttribute('src') : ''
        });
      });
      return out;
    }
    """

    def _parse_post(self, p: dict, group_name: str = "") -> Listing | None:
        text = p.get("text", "")

        # רלוונטיות — חייב מילת דירה
        if not any(kw in text for kw in APARTMENT_KW):
            return None

        price = self._extract_price(text)
        rooms = self._extract_rooms(text)
        # דירה אמיתית = מילת דירה + (מחיר או חדרים)
        if price is None and rooms is None:
            return None

        # מיקום — התאמה לרשימת המיקומים בפרופיל (בטקסט או בשם הקבוצה)
        locations = self.search_config.get("locations", [])
        hay = f"{text} {group_name}"
        city = ""
        matched = False
        for loc in locations:
            if loc in hay:
                city = loc
                matched = True
                break

        clean = self._clean_text(text)
        listing = Listing(
            url=p["url"],
            source="facebook",
            title=clean[:60],
            city=city,
            neighborhood="",
            price=price,
            rooms=rooms,
            description=clean[:280],
            image_url=p.get("img", ""),
            location_matched=matched,
        )
        listing.score = self.score_listing(listing)
        return listing

    @staticmethod
    def _extract_price(text: str) -> int | None:
        # מספר 3500-15000 ליד ₪/ש"ח, או "מחיר: X"
        for m in re.finditer(r"([\d,]{3,6})\s*(?:₪|ש\"ח|שח|שקל)", text):
            v = int(m.group(1).replace(",", ""))
            if 1500 <= v <= 30000:
                return v
        m = re.search(r"מחיר[:\s]+([\d,]{3,6})", text)
        if m:
            v = int(m.group(1).replace(",", ""))
            if 1500 <= v <= 30000:
                return v
        return None

    @staticmethod
    def _extract_rooms(text: str) -> float | None:
        m = re.search(r"(\d+\.?\d*)\s*חדר", text)
        return float(m.group(1)) if m else None

    @staticmethod
    def _clean_text(text: str) -> str:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        out = []
        for ln in lines:
            if ln in UI_NOISE or ln in ("Reply", "Share", "Like"):
                continue
            if re.fullmatch(r"\d+[hmdw]", ln):  # חותמת זמן 1h/2d
                continue
            out.append(ln)
        return " • ".join(out[1:]) if len(out) > 1 else (out[0] if out else "")

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
