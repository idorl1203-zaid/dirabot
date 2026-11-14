"""
server.py — DiraBot Web Server
FastAPI backend + WebSocket chat + REST API
"""
import asyncio
import json
import logging
import os
import sys
import yaml
import copy
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from db import (init_db, get_unnotified, get_stats, save_listing, mark_notified,
                cleanup_old_listings, delete_listing, get_all_listings,
                set_feedback, get_preferences, get_feedback_summary)
from scraper import Yad2Scraper, MadlanScraper, FacebookScraper
from telegram_notifier import TelegramNotifier

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.triggers import every, TriggerContext

logger = logging.getLogger("dirabot.server")
logging.basicConfig(level=logging.INFO)

BUNDLED_CONFIG = Path(__file__).parent / "config.yaml"
# נתיב config ניתן להגדרה דרך env (volume קבוע). מזרעים מברירת המחדל בהרצה ראשונה.
CONFIG_PATH = Path(os.getenv("DIRABOT_CONFIG_PATH", BUNDLED_CONFIG))
if CONFIG_PATH != BUNDLED_CONFIG and not CONFIG_PATH.exists():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(BUNDLED_CONFIG, CONFIG_PATH)

STATIC_PATH = Path(__file__).parent / "static"

# Global state
_agent = None
_ws_clients: list[WebSocket] = []
_notifier = None
_scan_running = False


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_notifier(config: dict):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = config.get("notifications", {}).get("telegram_chat_id", "")
    if not token or not chat_id:
        return None
    return TelegramNotifier(token=token, chat_id=chat_id)


async def broadcast(event: str, data: dict):
    msg = json.dumps({"event": event, "data": data})
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


def build_profile_config(base_config: dict, profile: dict) -> dict:
    """בונה config מלא עבור פרופיל ספציפי"""
    merged = copy.deepcopy(base_config)
    merged["search"] = {
        "locations": profile.get("locations", []),
        "price": profile.get("price", {"min": 0, "max": 99999}),
        "rooms": profile.get("rooms", {"min": 1, "max": 10}),
        "floor_min": profile.get("floor_min", 0),
        "require_elevator": profile.get("require_elevator", False),
        "require_parking": profile.get("require_parking", False),
        "require_balcony": profile.get("require_balcony", False),
        "require_mamad": profile.get("require_mamad", False),
        "require_pets": profile.get("require_pets", False),
        "require_renovated": profile.get("require_renovated", False),
        "blacklist_keywords": profile.get("blacklist_keywords", []),
        "bonus_keywords": profile.get("bonus_keywords", []),
    }
    return merged


async def run_scan():
    global _scan_running
    if _scan_running:
        await broadcast("log", {"msg": "⏳ סריקה כבר פועלת...", "level": "warn"})
        return
    _scan_running = True
    config = load_config()
    profiles = [p for p in config.get("profiles", []) if p.get("enabled", True)]

    await broadcast("log", {"msg": f"🔍 מתחיל סריקה — {len(profiles)} פרופילים פעילים...", "level": "info"})
    await broadcast("scan_started", {})

    total_new = 0
    # סף ציון קשיח — דירות מתחת אליו לא נשמרות/מוצגות/נשלחות כלל
    min_score = config.get("notifications", {}).get("min_score_to_notify", 70)

    # העדפות נלמדות מפידבק — הסוכן מתמקד יותר במה שאהבת, פחות במה שלא
    preferences = await get_preferences()
    fb = await get_feedback_summary()
    if fb["likes"] or fb["dislikes"]:
        await broadcast("log", {"msg": f"🧠 לומד מפידבק: {fb['likes']} 👍 / {fb['dislikes']} 👎", "level": "info"})

    async def scan_profile(profile: dict):
        nonlocal total_new
        profile_config = build_profile_config(config, profile)
        profile_config["preferences"] = preferences
        profile_name = profile.get("name", "ללא שם")
        await broadcast("log", {"msg": f"  📌 פרופיל: {profile_name}", "level": "info"})

        scrapers = []
        if config.get("sources", {}).get("yad2", True):
            scrapers.append(Yad2Scraper(profile_config))
        if config.get("sources", {}).get("madlan", False):
            scrapers.append(MadlanScraper(profile_config))

        for scraper in scrapers:
            try:
                listings = await scraper.fetch_listings()
                qualified = [l for l in listings if l.score >= min_score]
                new = 0
                for l in qualified:
                    d = l.to_dict()
                    d["profile"] = profile_name
                    if await save_listing(d):
                        new += 1
                        total_new += 1
                await broadcast("log", {"msg": f"    [{scraper.name}] {len(listings)} נסרקו, {len(qualified)} עברו סף {min_score}, {new} חדשות", "level": "info"})
            except Exception as e:
                await broadcast("log", {"msg": f"    [{scraper.name}] שגיאה: {e}", "level": "error"})

    # הרצה מקבילית של כל הפרופילים
    await asyncio.gather(*[scan_profile(p) for p in profiles])

    # פייסבוק — רץ פעם אחת לכל הקבוצות (לא פר-פרופיל, כי הפרופיל נעול לתהליך אחד).
    # כבוי כברירת מחדל; מדליקים כשהחשבון המשני "מחומם".
    if config.get("sources", {}).get("facebook", False) and profiles:
        try:
            all_locs = sorted({l for p in profiles for l in p.get("locations", [])})
            prices = [p.get("price", {}) for p in profiles if p.get("price")]
            rooms = [p.get("rooms", {}) for p in profiles if p.get("rooms")]
            fb_search = {
                "locations": all_locs,
                "price": {"min": min((pr.get("min", 0) for pr in prices), default=0),
                          "max": max((pr.get("max", 99999) for pr in prices), default=99999)},
                "rooms": {"min": min((r.get("min", 1) for r in rooms), default=1),
                          "max": max((r.get("max", 10) for r in rooms), default=10)},
                "blacklist_keywords": sorted({k for p in profiles for k in p.get("blacklist_keywords", [])}),
                "bonus_keywords": sorted({k for p in profiles for k in p.get("bonus_keywords", [])}),
            }
            fb_config = {**config, "search": fb_search, "preferences": preferences}
            fb_listings = await FacebookScraper(fb_config).fetch_listings()
            new = 0
            for l in fb_listings:
                if l.score >= min_score:
                    d = l.to_dict()
                    d["profile"] = "פייסבוק"
                    if await save_listing(d):
                        total_new += 1
                        new += 1
            await broadcast("log", {"msg": f"    [facebook] {len(fb_listings)} דירות, {new} חדשות", "level": "info"})
        except Exception as e:
            await broadcast("log", {"msg": f"    [facebook] שגיאה: {e}", "level": "error"})

    unnotified = await get_unnotified(min_score=min_score)
    for listing in unnotified:
        if _notifier:
            await _notifier.send_listing(listing)
        await mark_notified(listing["url"])
        await broadcast("new_listing", listing)
        await asyncio.sleep(0.3)

    await cleanup_old_listings(config.get("scan", {}).get("listing_ttl_days", 60))
    stats = await get_stats()
    await broadcast("scan_done", {"new": total_new, "stats": stats})
    await broadcast("log", {"msg": f"✅ סריקה הסתיימה — {total_new} דירות חדשות", "level": "success"})
    _scan_running = False


async def scan_trigger(ctx: TriggerContext):
    await run_scan()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent, _notifier
    await init_db()
    config = load_config()
    _notifier = get_notifier(config)
    interval_hours = config.get("scan", {}).get("interval_hours", 2.5)

    agent_config = LocalAgentConfig(
        system_instructions="""אתה DiraBot — עוזר חכם למציאת דירות להשכרה בישראל.
אתה עוזר לזוג למצוא את הדירה המושלמת.
יש לך גישה לנתוני הדירות, סטטיסטיקות, וקריטריוני חיפוש.
ענה תמיד בעברית, בצורה חמה ומקצועית.
כשמישהו שואל על דירות — ספר על הדירות שנמצאו, הציונים, המחירים.
היה יוזמה — הצע תובנות וטיפים.""",
        triggers=[every(int(interval_hours * 3600), scan_trigger)],
    )

    async with Agent(agent_config) as agent:
        _agent = agent
        logger.info("✅ DiraBot Agent מוכן")
        asyncio.create_task(run_scan())
        yield

    _agent = None


app = FastAPI(title="DiraBot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(STATIC_PATH / "index.html")


@app.get("/api/listings")
async def api_listings(limit: int = 100, min_score: int = 0):
    return await get_all_listings(min_score=min_score, limit=limit)


@app.delete("/api/listings/{listing_id}")
async def api_delete_listing(listing_id: int):
    await delete_listing(listing_id)
    return {"status": "deleted", "id": listing_id}


@app.post("/api/listings/{listing_id}/feedback")
async def api_feedback(listing_id: int, body: dict):
    """👍/👎 על דירה. verdict ∈ {'like','dislike','clear'}."""
    verdict = body.get("feedback", "")
    if verdict not in ("like", "dislike", "clear"):
        raise HTTPException(status_code=400, detail="feedback must be like/dislike/clear")
    result = await set_feedback(listing_id, verdict)
    if result is None:
        raise HTTPException(status_code=404, detail="listing not found")
    return {"status": "ok", "feedback": verdict, "summary": await get_feedback_summary()}


@app.get("/api/stats")
async def api_stats():
    return await get_stats()


@app.get("/api/config")
async def api_config():
    return load_config()


@app.put("/api/config")
async def api_update_config(body: dict):
    try:
        save_config(body)
        global _notifier
        _notifier = get_notifier(body)
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/profiles")
async def api_profiles():
    config = load_config()
    return config.get("profiles", [])


@app.put("/api/profiles")
async def api_update_profiles(profiles: list[dict]):
    config = load_config()
    config["profiles"] = profiles
    save_config(config)
    return {"status": "saved", "count": len(profiles)}


@app.post("/api/scan")
async def api_scan():
    asyncio.create_task(run_scan())
    return {"status": "started"}


@app.get("/api/listings/top")
async def api_top_listings(limit: int = 5):
    from db import DB_PATH
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM listings ORDER BY score DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    stats = await get_stats()
    config = load_config()
    await ws.send_text(json.dumps({"event": "connected", "data": {"stats": stats, "config": config}}))

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            if data.get("type") == "chat":
                user_msg = data.get("message", "")
                if not user_msg:
                    continue
                if _agent:
                    await ws.send_text(json.dumps({"event": "typing", "data": {}}))
                    try:
                        stats = await get_stats()
                        from db import DB_PATH
                        import aiosqlite
                        async with aiosqlite.connect(DB_PATH) as db:
                            db.row_factory = aiosqlite.Row
                            cur = await db.execute(
                                "SELECT city, price, rooms, score, url FROM listings ORDER BY score DESC LIMIT 5"
                            )
                            top = [dict(r) for r in await cur.fetchall()]

                        context = f"[הקשר]\nסטטיסטיקות: {json.dumps(stats, ensure_ascii=False)}\n5 דירות מובילות: {json.dumps(top, ensure_ascii=False)}\n\nשאלה: {user_msg}"
                        response = await _agent.chat(context)
                        agent_text = await response.text()
                        await ws.send_text(json.dumps({"event": "chat_response", "data": {"message": agent_text}}))
                    except Exception as e:
                        await ws.send_text(json.dumps({"event": "chat_response", "data": {"message": f"שגיאה: {e}"}}))

            elif data.get("type") == "scan":
                asyncio.create_task(run_scan())

    except WebSocketDisconnect:
        if ws in _ws_clients:
            _ws_clients.remove(ws)
