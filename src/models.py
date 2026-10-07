from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass
class SearchConfig:
    name: str
    query: str
    min_year: int
    max_year: int
    min_price: int
    max_price: int
    max_mileage_km: int | None = 250_000
    queries: list[str] = field(default_factory=list)
    must_include_any: list[str] = field(default_factory=list)
    must_include_all: list[str] = field(default_factory=list)
    powertrain_any: list[str] = field(default_factory=list)
    body_styles: list[str] = field(default_factory=list)
    require_body_style: bool = False
    # If True, drop listings with no mileage shown
    require_mileage: bool = False

    def all_queries(self) -> list[str]:
        seen: list[str] = []
        for q in [*(self.queries or []), self.query]:
            q = (q or "").strip()
            if q and q.lower() not in {value.lower() for value in seen}:
                seen.append(q)
        if re.search(r"\boptima\b", self.query, re.IGNORECASE) and (
            re.search(r"\b(?:hybrid|hev|phev|huv)\b", self.query, re.IGNORECASE)
            or self.powertrain_any
        ):
            for query in ("kia optima hybrid", "optima hybrid", "kia optima hev",
                          "optima hev", "kia optima phev", "kia optima huv",
                          "kiaoptima hybrid", "kia optima"):
                if query not in {value.lower() for value in seen}:
                    seen.append(query)
        return seen or [self.query]


@dataclass
class Listing:
    listing_id: str
    title: str
    price: str
    price_amount: int | None
    location: str
    url: str
    search_name: str
    year: int | None = None
    mileage_km: int | None = None
    card_text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    safety: str = "unknown"
    safety_evidence: str = ""
    details_checked_at: str = ""

    def haystack(self) -> str:
        return " ".join(
            part
            for part in (self.title, self.location, self.card_text, self.description, str(self.mileage_km or ""))
            if part
        )

    def telegram_message(self) -> str:
        year_bit = f" ({self.year})" if self.year else ""
        safe_url = _escape_attr(self.url)
        lines = [
            f"🚗 <b>{_escape(self.search_name)}</b>{year_bit}",
            f"<b>{_escape(self.title)}</b>",
            f"💰 {_escape(self.price)}",
        ]
        if self.mileage_km is not None:
            lines.append(f"⏱ {self.mileage_km:,} km")
        if self.location:
            lines.append(f"📍 {_escape(self.location)}")
        lines.append(f"Safety: <b>{_escape(self.safety)}</b> (seller description)")
        if self.safety_evidence:
            lines.append(f"Seller: {_escape(self.safety_evidence)}")
        lines.append(f'🔗 <a href="{safe_url}">Open on Marketplace</a>')
        return "\n".join(lines)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_attr(text: str) -> str:
    return _escape(text).replace('"', "&quot;")
