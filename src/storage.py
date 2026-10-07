from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import Listing


class SeenStore:
    """Persists listing IDs so the same post is never sent twice."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                listing_id TEXT PRIMARY KEY,
                search_name TEXT,
                title TEXT,
                url TEXT,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(seen_listings)")}
        for name, sql_type in {
            "price": "TEXT", "price_amount": "INTEGER", "year": "INTEGER",
            "mileage_km": "INTEGER", "location": "TEXT", "last_seen_at": "TIMESTAMP",
            "description": "TEXT", "safety": "TEXT", "safety_evidence": "TEXT",
            "details_checked_at": "TEXT",
        }.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE seen_listings ADD COLUMN {name} {sql_type}")
        self._conn.commit()

    def is_seen(self, listing_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
        return row is not None

    def mark_seen(
        self,
        listing_id: str,
        search_name: str = "",
        title: str = "",
        url: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO seen_listings
                (listing_id, search_name, title, url)
            VALUES (?, ?, ?, ?)
            """,
            (listing_id, search_name, title, url),
        )
        self._conn.commit()

    def update_details(self, listing: Listing) -> None:
        self._conn.execute(
            """
            UPDATE seen_listings SET
                title = COALESCE(NULLIF(?, ''), title),
                url = COALESCE(NULLIF(?, ''), url),
                price = COALESCE(NULLIF(NULLIF(?, ''), 'Price n/a'), price),
                price_amount = COALESCE(?, price_amount),
                year = COALESCE(?, year),
                mileage_km = COALESCE(?, mileage_km),
                location = COALESCE(NULLIF(?, ''), location),
                last_seen_at = CURRENT_TIMESTAMP
            WHERE listing_id = ?
            """,
            (listing.title, listing.url, listing.price, listing.price_amount, listing.year,
             listing.mileage_km, listing.location, listing.listing_id),
        )
        if listing.details_checked_at:
            self._conn.execute(
                """UPDATE seen_listings SET description = ?, safety = ?,
                   safety_evidence = ?, details_checked_at = ? WHERE listing_id = ?""",
                (listing.description, listing.safety, listing.safety_evidence,
                 listing.details_checked_at, listing.listing_id),
            )
        self._conn.commit()

    def all_findings(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT listing_id, search_name, title, url, first_seen_at,
                   price, price_amount, year, mileage_km, location, last_seen_at,
                   description, safety, safety_evidence, details_checked_at
            FROM seen_listings
            ORDER BY first_seen_at DESC, listing_id DESC
            """
        ).fetchall()
        fields = ("listing_id", "search_name", "title", "url", "first_seen_at",
                  "price", "price_amount", "year", "mileage_km", "location", "last_seen_at",
                  "description", "safety", "safety_evidence", "details_checked_at")
        return [dict(zip(fields, row)) for row in rows]

    def close(self) -> None:
        self._conn.close()
