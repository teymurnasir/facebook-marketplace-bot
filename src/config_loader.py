from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import SearchConfig


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    default_max_mileage = data.get("max_mileage_km", 250_000)
    if default_max_mileage is not None:
        default_max_mileage = int(default_max_mileage)

    searches = []
    for raw in data.get("searches", []):
        max_mileage = raw.get("max_mileage_km", default_max_mileage)
        if max_mileage is not None:
            max_mileage = int(max_mileage)
        searches.append(
            SearchConfig(
                name=raw["name"],
                query=raw["query"],
                queries=list(raw.get("queries") or []),
                min_year=int(raw["min_year"]),
                max_year=int(raw["max_year"]),
                min_price=int(raw["min_price"]),
                max_price=int(raw["max_price"]),
                max_mileage_km=max_mileage,
                must_include_any=list(raw.get("must_include_any") or []),
                must_include_all=list(raw.get("must_include_all") or []),
                powertrain_any=list(raw.get("powertrain_any") or []),
                body_styles=list(raw.get("body_styles") or []),
                require_body_style=bool(raw.get("require_body_style", False)),
                require_mileage=bool(raw.get("require_mileage", False)),
            )
        )

    scraper = data.get("scraper") or {}
    url_modes = list(scraper.get("url_modes") or ["vehicles", "search"])
    url_modes = [m for m in url_modes if m in {"vehicles", "search"}] or ["search"]
    search_mode_locations = list(scraper.get("search_mode_locations") or [])

    market_areas = []
    for raw_area in data.get("market_areas") or []:
        if not isinstance(raw_area, dict):
            continue
        slug = str(raw_area.get("slug") or "").strip()
        if not slug:
            continue
        try:
            radius_km = int(raw_area.get("radius_km", 65))
        except (TypeError, ValueError):
            radius_km = 65
        market_areas.append(
            {
                "slug": slug,
                "label": str(raw_area.get("label") or slug),
                "radius_km": radius_km,
            }
        )

    locations = list(data.get("locations") or [])
    # Legacy migrate: only keep the first location — user adds more in Telegram
    if not market_areas and locations:
        slug = str(locations[0])
        market_areas = [
            {
                "slug": slug,
                "label": slug.replace("-", " ").title() + ", ON",
                "radius_km": 65,
            }
        ]
    if market_areas:
        locations = [a["slug"] for a in market_areas]
    # Empty locations allowed in file; Telegram /scan blocks until user adds one

    if search_mode_locations and locations:
        active = set(locations)
        if not any(slug in active for slug in search_mode_locations):
            search_mode_locations = [locations[0]]

    return {
        "country": data.get("country") or "CA",
        "locations": locations,
        "market_areas": market_areas,
        "location_keywords": list(data.get("location_keywords") or []),
        "searches": searches,
        "scraper": {
            "sort_by": scraper.get("sort_by", "creation_time_descend"),
            "max_scrolls": int(scraper.get("max_scrolls", 6)),
            "delay_between_searches_sec": float(
                scraper.get("delay_between_searches_sec", 2)
            ),
            "timeout_ms": int(scraper.get("timeout_ms", 60000)),
            "url_modes": url_modes,
            "search_mode_locations": search_mode_locations,
        },
    }
