"""
agent.py — הסוכן הראשי של DiraBot
מריץ סריקות תקופתיות, שומר דירות ב-SQLite, ושולח התראות Telegram
"""
import asyncio
import logging
import sys
import os
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig, types
from google.antigravity.triggers import every, TriggerContext

from db import init_db, save_listing, mark_notified, get_unnotified, get_stats, cleanup_old_listings, get_all_listings
from scraper import Yad2Scraper, MadlanScraper
from telegram_notifier import TelegramNotifier

# ─── Setup ────────────────────────────────────────────────────────────────────
load_dotenv()
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, console=console)]
)
logger = logging.getLogger("dirabot")

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_notifier(config: dict) -> TelegramNotifier | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = config.get("notifications", {}).get("telegram_chat_id", "")
    if not token or not chat_id:
        logger.warning("⚠️  Telegram לא מוגדר — רק לוג מקומי")
        return None
    return TelegramNotifier(token=token, chat_id=chat_id)


# ─── Scan Logic ───────────────────────────────────────────────────────────────

async def run_scan(config: dict, notifier: TelegramNotifier | None):
    """מחזור סריקה מלא אחד"""
    logger.info("🔍 מתחיל סריקה...")

    scrapers = []
    sources = config.get("sources", {})
    if sources.get("yad2", True):
        scrapers.append(Yad2Scraper(config))
    if sources.get("madlan", True):
        scrapers.append(MadlanScraper(config))

    all_listings = []
    for scraper in scrapers:
        try:
            listings = await scraper.fetch_listings()
            all_listings.extend(listings)
            logger.info(f"  [{scraper.name}] {len(listings)} מודעות נסרקו")
        except Exception as e:
            logger.error(f"  [{scraper.name}] שגיאה: {e}")

    # שמירה ב-DB עם dedup
    new_count = 0
    min_score = config.get("notifications", {}).get("min_score_to_notify", 50)

    for listing in all_listings:
        listing_dict = listing.to_dict()
        is_new = await save_listing(listing_dict)
        if is_new:
            new_count += 1

    logger.info(f"✅ {new_count} דירות חדשות נשמרו (מתוך {len(all_listings)} שנסרקו)")

    # שליחת התראות על דירות חדשות שלא דווחו
    unnotified = await get_unnotified(min_score=min_score)
    if unnotified:
        logger.info(f"📬 שולח {len(unnotified)} התראות...")
        for listing in unnotified:
            if notifier:
                success = await notifier.send_listing(listing)
                if success:
                    await mark_notified(listing["url"])
                    await asyncio.sleep(0.5)  # throttle
            else:
                _print_listing_cli(listing)
                await mark_notified(listing["url"])
    else:
        logger.info("💤 אין דירות חדשות מתאימות כרגע")


def _print_listing_cli(listing: dict):
    """הדפסת דירה יפה בטרמינל (כשאין Telegram)"""
    table = Table(title=f"🏠 {listing.get('city')} | ציון: {listing.get('score')}/100")
    table.add_column("שדה", style="cyan")
    table.add_column("ערך", style="green")
    table.add_row("מחיר", f"{listing.get('price', 0):,} ₪")
    table.add_row("חדרים", str(listing.get("rooms", "")))
    table.add_row("קומה", str(listing.get("floor", "")))
    table.add_row("מקור", listing.get("source", ""))
    table.add_row("קישור", listing.get("url", ""))
    console.print(table)


# ─── Daily Summary ────────────────────────────────────────────────────────────

async def send_daily_summary(config: dict, notifier: TelegramNotifier | None):
    """שליחת סיכום יומי"""
    stats = await get_stats()
    top_listings = await get_all_listings(min_score=0, limit=5)  # המובילות, כולל שנשלחו
    if notifier:
        await notifier.send_daily_summary(stats, top_listings[:5])
    else:
        console.print(Panel(
            f"📊 סיכום יומי\n"
            f"היום: {stats['today']} | נשלחו: {stats['notified']} | סה\"כ: {stats['total']}",
            border_style="blue"
        ))


# ─── AGY Triggers ─────────────────────────────────────────────────────────────

config_global = {}
notifier_global = None


async def scan_trigger(ctx: TriggerContext):
    """טריגר תקופתי לסריקה"""
    config = load_config()  # קורא מחדש כל פעם — תומך בשינויים חיים!
    await run_scan(config, notifier_global)
    await cleanup_old_listings(config.get("scan", {}).get("listing_ttl_days", 60))


async def daily_summary_trigger(ctx: TriggerContext):
    """טריגר לסיכום יומי"""
    now = datetime.now()
    summary_hour = config_global.get("notifications", {}).get("daily_summary_hour", 9)
    if now.hour == summary_hour:
        await send_daily_summary(config_global, notifier_global)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    global config_global, notifier_global

    # הגדרות
    config_global = load_config()
    notifier_global = get_notifier(config_global)

    # init DB
    await init_db()

    # בדיקת סריקה ראשונה מיידית
    interval_hours = config_global.get("scan", {}).get("interval_hours", 2.5)
    interval_seconds = int(interval_hours * 3600)

    console.print(Panel(
        f"[bold cyan]🚀 DiraBot מופעל![/bold cyan]\n"
        f"סריקה כל [yellow]{interval_hours}[/yellow] שעות\n"
        f"Telegram: {'✅' if notifier_global else '❌ לא מוגדר'}\n"
        f"מקורות: {[k for k,v in config_global.get('sources', {}).items() if v]}",
        border_style="cyan"
    ))

    # סריקה ראשונה מיידית
    logger.info("▶️  סריקה ראשונה...")
    await run_scan(config_global, notifier_global)

    # הגדרת טריגרים תקופתיים
    scan_t = every(interval_seconds, scan_trigger)
    summary_t = every(3600, daily_summary_trigger)  # בדיקה כל שעה אם צריך לשלוח סיכום

    agy_config = LocalAgentConfig(
        system_instructions=(
            "אתה DiraBot — עוזר למציאת דירות להשכרה. "
            "אתה מריץ סריקות תקופתיות ושולח התראות על דירות מתאימות."
        ),
        triggers=[scan_t, summary_t],
    )

    async with Agent(agy_config) as agent:
        logger.info("✅ הסוכן פועל. לחץ Ctrl+C לעצירה.")
        # keep alive — הסוכן ממשיך עם הטריגרים
        while True:
            await asyncio.sleep(60)


# ─── CLI Entry Points ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--setup" in sys.argv:
        # מצב הגדרת פרופיל
        from profile_builder import run_profile_setup
        asyncio.run(run_profile_setup())
    elif "--scan-now" in sys.argv:
        # סריקה חד-פעמית
        async def one_shot():
            await init_db()
            config = load_config()
            notifier = get_notifier(config)
            await run_scan(config, notifier)
        asyncio.run(one_shot())
    else:
        # הרצה רגילה עם טריגרים
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            console.print("\n[yellow]👋 DiraBot עצר. להתראות![/yellow]")
