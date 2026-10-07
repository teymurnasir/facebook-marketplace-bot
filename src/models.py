from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .search_queries import expand_queries, hybrid_requested, model_query


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
        return expand_queries(self.query, self.queries, self.powertrain_any)

    def keyword_filters(self) -> tuple[list[str], list[str]]:
        base = model_query(self.query, hybrid_requested(self.query, self.powertrain_any))
        legacy_any = {base, base.replace(" ", "")}
        # Older Telegram wizards duplicated the primary query as keyword rules.
        # Replace only that exact generated pair; retain genuine custom constraints.
        if base and {v.lower() for v in self.must_include_any} == legacy_any and (
            [v.lower() for v in self.must_include_all] == base.split()
            or (len(base.split()) == 1 and not self.must_include_all)
        ):
            return [], []
        return self.must_include_any, self.must_include_all


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
