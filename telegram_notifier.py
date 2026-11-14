"""
telegram_notifier.py — שליחת התראות Telegram על דירות חדשות
"""
import logging
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


def format_listing_message(listing: dict) -> str:
    """פורמט הודעת Telegram יפה לדירה — HTML mode"""

    score = listing.get("score", 0)
    if score >= 85:
        stars = "⭐⭐⭐"
    elif score >= 70:
        stars = "⭐⭐"
    elif score >= 50:
        stars = "⭐"
    else:
        stars = ""

    source_emoji = {"yad2": "🟡", "madlan": "🔵"}.get(listing.get("source", ""), "🏠")
    source_name = listing.get("source", "").capitalize()

    lines = [
        f"🏠 <b>דירה חדשה נמצאה!</b> {stars}",
        f"{source_emoji} <i>{h(source_name)}</i>   •   📊 ציון: <b>{score}/100</b>",
        "",
    ]

    # מיקום
    city = listing.get("city", "")
    neighborhood = listing.get("neighborhood", "")
    location_str = city
    if neighborhood:
        location_str += f", {neighborhood}"
    if location_str.strip():
        lines.append(f"📍 {h(location_str)}")

    # חדרים וקומה
    rooms = listing.get("rooms")
    floor = listing.get("floor")
    room_floor = ""
    if rooms:
        room_floor += f"🛏 {rooms} חדרים"
    if floor is not None:
        room_floor += f"  •  קומה {floor}"
    if room_floor:
        lines.append(room_floor)

    # מחיר
    price = listing.get("price")
    if price:
        lines.append(f"💰 <b>{price:,} ₪/חודש</b>")

    # שטח
    size = listing.get("size_sqm")
    if size:
        lines.append(f"📐 {size} מ\"ר")

    # מאפיינים
    features = []
    if listing.get("has_elevator"):
        features.append("🛗 מעלית")
    if listing.get("has_parking"):
        features.append("🅿️ חניה")
    if listing.get("has_balcony"):
        features.append("🌿 מרפסת")
    if listing.get("has_mamad"):
        features.append("🛡 ממ\"ד")
    if features:
        lines.append("  ".join(features))

    # תיאור קצר
    description = listing.get("description", "")
    if description:
        short_desc = description[:120].replace("\n", " ")
        if len(description) > 120:
            short_desc += "..."
        lines.append(f"\n📝 <i>{h(short_desc)}</i>")

    # קישור
    url = listing.get("url", "")
    if url:
        lines.append(f"\n<a href=\"{url}\">🔗 לצפייה במודעה</a>")

    return "\n".join(lines)


def format_daily_summary(stats: dict, top_listings: list[dict]) -> str:
    """פורמט סיכום יומי"""
    lines = [
        "📊 <b>סיכום יומי — DiraBot</b>",
        "",
        f"🔍 נסרקו היום: <b>{stats.get('today', 0)}</b> דירות חדשות",
        f"📬 נשלחו התראות: <b>{stats.get('notified', 0)}</b>",
        f"🗄 סה\"כ במאגר: <b>{stats.get('total', 0)}</b>",
        "",
    ]

    if top_listings:
        lines.append("🏆 <b>הדירות המובילות היום:</b>")
        for i, listing in enumerate(top_listings[:3], 1):
            city = h(listing.get("city", ""))
            price = listing.get("price", 0) or 0
            score = listing.get("score", 0)
            url = listing.get("url", "")
            line = f"{i}. {city} — {price:,}₪ — ציון {score}"
            if url:
                line += f' <a href="{url}">🔗</a>'
            lines.append(line)

    return "\n".join(lines)


def h(text: str) -> str:
    """HTML escape בסיסי"""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def send_listing(self, listing: dict) -> bool:
        """שולח התראה על דירה אחת"""
        try:
            message = format_listing_message(listing)
            image_url = listing.get("image_url", "")

            if image_url:
                try:
                    await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=image_url,
                        caption=message,
                        parse_mode=ParseMode.HTML,
                    )
                    return True
                except TelegramError:
                    pass  # נופל לטקסט

            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
            return True

        except TelegramError as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def send_daily_summary(self, stats: dict, top_listings: list[dict]) -> bool:
        """שולח סיכום יומי"""
        try:
            message = format_daily_summary(stats, top_listings)
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
            )
            return True
        except TelegramError as e:
            logger.error(f"Telegram summary error: {e}")
            return False

    async def send_simple(self, text: str) -> bool:
        """שליחת הודעת טקסט פשוטה"""
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text)
            return True
        except TelegramError as e:
            logger.error(f"Telegram simple send error: {e}")
            return False
