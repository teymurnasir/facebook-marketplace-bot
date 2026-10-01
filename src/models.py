from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchConfig:
    name: str
    query: str
    min_year: int
    max_year: int
    min_price: int
    max_price: int
    must_include_any: list[str] = field(default_factory=list)
    must_include_all: list[str] = field(default_factory=list)
    body_styles: list[str] = field(default_factory=list)
    require_body_style: bool = False


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
    raw: dict[str, Any] = field(default_factory=dict)

    def telegram_message(self) -> str:
        year_bit = f" ({self.year})" if self.year else ""
        safe_url = _escape_attr(self.url)
        lines = [
            f"🚗 <b>{_escape(self.search_name)}</b>{year_bit}",
            f"<b>{_escape(self.title)}</b>",
            f"💰 {_escape(self.price)}",
        ]
        if self.location:
            lines.append(f"📍 {_escape(self.location)}")
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
