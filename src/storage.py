from __future__ import annotations

import sqlite3
from pathlib import Path


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

    def close(self) -> None:
        self._conn.close()
