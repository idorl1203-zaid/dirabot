"""
scraper/base.py — Base class משותף לכל ה-scrapers
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class Listing:
    """מודל אחיד לדירה מכל מקור"""
    url: str
    source: str
    title: str = ""
    city: str = ""
    neighborhood: str = ""
    price: Optional[int] = None
    rooms: Optional[float] = None
    floor: Optional[int] = None
    size_sqm: Optional[int] = None
    has_elevator: bool = False
    has_parking: bool = False
    has_balcony: bool = False
    has_mamad: bool = False
    is_renovated: bool = False  # חדש מקבלן / חדש / משופץ (propertyCondition 1-3)
    description: str = ""
    image_url: str = ""
    score: int = 0
    location_matched: bool = False  # הדירה הגיעה מחיפוש עיר/אזור תקין → זכאית לנקודות מיקום

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class BaseScraper(ABC):
    """Base class לכל ה-scrapers"""

    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.search_config = config.get("search", {})
        self.scan_config = config.get("scan", {})
        self.max_listings = self.scan_config.get("max_listings_per_source", 60)

    @abstractmethod
    async def fetch_listings(self) -> list[Listing]:
        """סורק ומחזיר רשימת דירות"""
        pass

    def score_listing(self, listing: Listing) -> int:
        """
        מחשב ציון התאמה (0-100) לדירה לפי הקריטריונים
        """
        score = 0
        scoring = self.config.get("scoring", {})
        search = self.search_config

        # --- מחיר (30 נקודות) ---
        price_weight = scoring.get("price_weight", 30)
        price_min = search.get("price", {}).get("min", 0)
        price_max = search.get("price", {}).get("max", 99999)
        if listing.price and price_min <= listing.price <= price_max:
            # ציון יותר גבוה לדירות במרכז הטווח
            mid = (price_min + price_max) / 2
            distance = abs(listing.price - mid) / ((price_max - price_min) / 2)
            score += int(price_weight * (1 - distance * 0.5))
        elif listing.price and listing.price < price_min * 0.9:
            score += int(price_weight * 0.5)  # זול מאוד — חשוד אבל עדיין נקודות

        # --- חדרים (20 נקודות) ---
        rooms_weight = scoring.get("rooms_weight", 20)
        rooms_min = search.get("rooms", {}).get("min", 1)
        rooms_max = search.get("rooms", {}).get("max", 10)
        if listing.rooms and rooms_min <= listing.rooms <= rooms_max:
            score += rooms_weight
        elif listing.rooms:
            score += int(rooms_weight * 0.3)

        # --- מאפיינים (15 נקודות) ---
        features_weight = scoring.get("features_weight", 15)
        features_score = 0
        features_total = 0

        required_features = {
            "require_elevator": listing.has_elevator,
            "require_parking": listing.has_parking,
            "require_balcony": listing.has_balcony,
            "require_mamad": listing.has_mamad,
        }
        for key, has_feature in required_features.items():
            if search.get(key, False):
                features_total += 1
                if has_feature:
                    features_score += 1
            elif has_feature:
                features_score += 0.5  # בונוס על מאפיין שלא דרשנו

        if features_total > 0:
            score += int(features_weight * (features_score / features_total))
        else:
            score += int(features_weight * 0.7)  # בסיס אם אין דרישות חובה

        # --- מילות מפתח (10 נקודות) ---
        keywords_weight = scoring.get("keywords_weight", 10)
        bonus_kw = search.get("bonus_keywords", [])
        blacklist_kw = search.get("blacklist_keywords", [])
        # כולל עיר+שכונה — כדי שחסימת עיר (כפר יונה/עפולה) תעבוד גם בחיפוש אזורי
        text = f"{listing.title} {listing.description} {listing.city} {listing.neighborhood}".lower()

        # בלאקליסט — ציון 0 מיידי
        for kw in blacklist_kw:
            if kw.lower() in text:
                return 0

        kw_hits = sum(1 for kw in bonus_kw if kw.lower() in text)
        if bonus_kw:
            score += int(keywords_weight * min(kw_hits / len(bonus_kw), 1.0))

        # מיקום (25 נקודות)
        # דירה שהגיעה מחיפוש עיר/אזור תקין כבר סוננה גאוגרפית ע"י ה-API,
        # ולכן זכאית לנקודות מיקום — גם אם שם האזור לא מופיע בטקסט (למשל 'עמק חפר').
        location_weight = scoring.get("location_weight", 25)
        locations = [loc.lower() for loc in search.get("locations", [])]
        listing_loc = f"{listing.city} {listing.neighborhood}".lower()
        if listing.location_matched or any(loc in listing_loc for loc in locations):
            score += location_weight

        # --- העדפות נלמדות מפידבק (👍/👎) — מזיז את הציון, חסום ±, לא משתלט ---
        prefs = self.config.get("preferences", {})
        if prefs:
            hood = (listing.neighborhood or "").strip()
            if hood:
                score += max(-12, min(12, prefs.get("neighborhood", {}).get(hood, 0) * 4))
            src = (listing.source or "").strip()
            if src:
                score += max(-6, min(6, prefs.get("source", {}).get(src, 0) * 2))
            if listing.is_renovated:
                score += max(-4, min(4, prefs.get("renovated_net", 0) * 2))

        return max(0, min(score, 100))

    @staticmethod
    def clean_price(text: str) -> Optional[int]:
        """חילוץ מחיר ממחרוזת"""
        if not text:
            return None
        digits = re.sub(r"[^\d]", "", str(text))
        return int(digits) if digits else None

    @staticmethod
    def clean_rooms(text: str) -> Optional[float]:
        """חילוץ מספר חדרים"""
        if not text:
            return None
        match = re.search(r"(\d+\.?\d*)", str(text))
        return float(match.group(1)) if match else None
