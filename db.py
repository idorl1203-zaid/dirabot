"""
db.py — ניהול SQLite עם deduplication מובנה
"""
import os
import sqlite3
import hashlib
import aiosqlite
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# נתיב ה-DB ניתן להגדרה דרך env (לשמירה ב-volume קבוע בפריסת ענן)
DB_PATH = Path(os.getenv("DIRABOT_DB_PATH", Path(__file__).parent / "dirabot.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


async def init_db():
    """יצירת טבלאות אם לא קיימות"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                hash        TEXT UNIQUE NOT NULL,
                url         TEXT UNIQUE NOT NULL,
                source      TEXT NOT NULL,
                title       TEXT,
                city        TEXT,
                neighborhood TEXT,
                price       INTEGER,
                rooms       REAL,
                floor       INTEGER,
                size_sqm    INTEGER,
                has_elevator BOOLEAN DEFAULT 0,
                has_parking  BOOLEAN DEFAULT 0,
                has_balcony  BOOLEAN DEFAULT 0,
                has_mamad    BOOLEAN DEFAULT 0,
                is_renovated BOOLEAN DEFAULT 0,
                score       INTEGER DEFAULT 0,
                description TEXT,
                image_url   TEXT,
                notified    BOOLEAN DEFAULT 0,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config_profile (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # טבלת פידבק — שורדת מחיקות/סריקות, כדי ש'לא אהבתי' יחסום לתמיד
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                hash         TEXT PRIMARY KEY,
                url          TEXT,
                feedback     TEXT NOT NULL,          -- 'like' | 'dislike'
                source       TEXT,
                city         TEXT,
                neighborhood TEXT,
                price        INTEGER,
                rooms        REAL,
                is_renovated BOOLEAN DEFAULT 0,
                created_at   TEXT NOT NULL
            )
        """)
        # מיגרציות — הוספת עמודות ל-DB קיים (מתעלם אם כבר קיימות)
        for col, ddl in [
            ("is_renovated", "ALTER TABLE listings ADD COLUMN is_renovated BOOLEAN DEFAULT 0"),
            ("feedback", "ALTER TABLE listings ADD COLUMN feedback TEXT"),
        ]:
            try:
                await db.execute(ddl)
            except Exception:
                pass
        await db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_url ON feedback(url);")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_hash ON listings(hash);
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_notified ON listings(notified);
        """)
        await db.commit()
    print("✅ DB מוכן")


def make_hash(url: str, price: Optional[int], rooms: Optional[float], city: str) -> str:
    """hash ייחודי לדירה — מסנן כפילויות גם אם ה-URL שינה פרמטרים"""
    raw = f"{url}|{price}|{rooms}|{city}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def is_duplicate(url: str, listing_hash: str) -> bool:
    """בודק אם הדירה כבר קיימת ב-DB"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM listings WHERE url = ? OR hash = ?",
            (url, listing_hash)
        )
        row = await cursor.fetchone()
        if row:
            # עדכון last_seen
            await db.execute(
                "UPDATE listings SET last_seen = ? WHERE url = ? OR hash = ?",
                (datetime.now().isoformat(), url, listing_hash)
            )
            await db.commit()
            return True
        return False


async def save_listing(listing: dict) -> bool:
    """שומר דירה חדשה. מחזיר True אם נשמרה, False אם כפילות."""
    h = make_hash(
        listing.get("url", ""),
        listing.get("price"),
        listing.get("rooms"),
        listing.get("city", "")
    )
    # 'לא אהבתי' — חסום לתמיד, לא נשמר שוב לעולם
    if await is_blocked(listing.get("url", ""), h):
        return False
    if await is_duplicate(listing.get("url", ""), h):
        return False

    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().isoformat()
        await db.execute("""
            INSERT INTO listings
              (hash, url, source, title, city, neighborhood, price, rooms,
               floor, size_sqm, has_elevator, has_parking, has_balcony,
               has_mamad, is_renovated, score, description, image_url, first_seen, last_seen)
            VALUES
              (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            h,
            listing.get("url", ""),
            listing.get("source", ""),
            listing.get("title", ""),
            listing.get("city", ""),
            listing.get("neighborhood", ""),
            listing.get("price"),
            listing.get("rooms"),
            listing.get("floor"),
            listing.get("size_sqm"),
            listing.get("has_elevator", False),
            listing.get("has_parking", False),
            listing.get("has_balcony", False),
            listing.get("has_mamad", False),
            listing.get("is_renovated", False),
            listing.get("score", 0),
            listing.get("description", ""),
            listing.get("image_url", ""),
            now,
            now,
        ))
        await db.commit()
    return True


async def mark_notified(url: str):
    """מסמן שההתראה נשלחה"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE listings SET notified = 1 WHERE url = ?", (url,)
        )
        await db.commit()


async def get_unnotified(min_score: int = 0) -> list[dict]:
    """מחזיר דירות שטרם נשלחה עליהן התראה"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM listings
            WHERE notified = 0 AND score >= ?
            ORDER BY score DESC, first_seen DESC
        """, (min_score,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_stats() -> dict:
    """סטטיסטיקות כלליות"""
    async with aiosqlite.connect(DB_PATH) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM listings")).fetchone())[0]
        notified = (await (await db.execute("SELECT COUNT(*) FROM listings WHERE notified=1")).fetchone())[0]
        today = (await (await db.execute(
            "SELECT COUNT(*) FROM listings WHERE first_seen >= ?",
            (datetime.now().replace(hour=0, minute=0, second=0).isoformat(),)
        )).fetchone())[0]
        return {"total": total, "notified": notified, "today": today}


async def cleanup_old_listings(ttl_days: int = 60):
    """מחיקת מודעות ישנות"""
    cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute(
            "DELETE FROM listings WHERE last_seen < ?", (cutoff,)
        )
        await db.commit()
        print(f"🧹 נמחקו {result.rowcount} מודעות ישנות")


async def delete_listing(listing_id: int):
    """מוחק דירה לפי ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        await db.commit()

async def is_blocked(url: str, listing_hash: str) -> bool:
    """האם הדירה סומנה 'לא אהבתי' (חסומה לתמיד)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM feedback WHERE feedback='dislike' AND (url = ? OR hash = ?) LIMIT 1",
            (url, listing_hash),
        )
        return (await cur.fetchone()) is not None


async def set_feedback(listing_id: int, verdict: str) -> Optional[dict]:
    """
    מתעד פידבק על דירה. verdict ∈ {'like','dislike','clear'}.
    'dislike' → נרשם בטבלת feedback (חסימה לתמיד) והשורה נמחקת מ-listings.
    'like'    → מסומן בשורה + נרשם ללמידה.
    'clear'   → מבטל את הפידבק.
    מחזיר את פרטי הדירה שעליה ניתן הפידבק, או None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
        row = await cur.fetchone()
        if not row:
            return None
        l = dict(row)
        now = datetime.now().isoformat()

        if verdict == "clear":
            await db.execute("DELETE FROM feedback WHERE hash = ? OR url = ?", (l["hash"], l["url"]))
            await db.execute("UPDATE listings SET feedback = NULL WHERE id = ?", (listing_id,))
            await db.commit()
            return l

        # upsert לטבלת הפידבק (שורדת מחיקה) — שומר מאפיינים ללמידה
        await db.execute("""
            INSERT INTO feedback (hash, url, feedback, source, city, neighborhood, price, rooms, is_renovated, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hash) DO UPDATE SET feedback=excluded.feedback, created_at=excluded.created_at
        """, (
            l["hash"], l["url"], verdict, l.get("source"), l.get("city"),
            l.get("neighborhood"), l.get("price"), l.get("rooms"),
            l.get("is_renovated", 0), now,
        ))

        if verdict == "dislike":
            # נעלמת מהפאנל ולא תחזור לעולם
            await db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        else:  # like
            await db.execute("UPDATE listings SET feedback = 'like' WHERE id = ?", (listing_id,))
        await db.commit()
        return l


async def get_preferences() -> dict:
    """
    מחשב פרופיל העדפות מצטבר מהפידבק — כמה נטו (like−dislike) לכל שכונה/מקור,
    והעדפה למצב-נכס. משמש את הסקורינג כדי 'להתמקד יותר/פחות' מסריקה לסריקה.
    """
    prefs = {"neighborhood": {}, "source": {}, "renovated_net": 0}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT feedback, source, neighborhood, is_renovated FROM feedback")
        for r in await cur.fetchall():
            delta = 1 if r["feedback"] == "like" else -1
            hood = (r["neighborhood"] or "").strip()
            if hood:
                prefs["neighborhood"][hood] = prefs["neighborhood"].get(hood, 0) + delta
            src = (r["source"] or "").strip()
            if src:
                prefs["source"][src] = prefs["source"].get(src, 0) + delta
            if r["is_renovated"]:
                prefs["renovated_net"] += delta
    return prefs


async def get_feedback_summary() -> dict:
    """סיכום קצר לתצוגה/לוג — מה אוהבים ומה לא."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        likes = (await (await db.execute("SELECT COUNT(*) c FROM feedback WHERE feedback='like'")).fetchone())["c"]
        dislikes = (await (await db.execute("SELECT COUNT(*) c FROM feedback WHERE feedback='dislike'")).fetchone())["c"]
        return {"likes": likes, "dislikes": dislikes}


async def get_all_listings(min_score: int = 0, limit: int = 100) -> list[dict]:
    """מחזיר את כל הדירות לפי ציון"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM listings
            WHERE score >= ?
            ORDER BY score DESC, first_seen DESC
            LIMIT ?
        """, (min_score, limit))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
