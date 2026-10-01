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

    return {
        "locations": list(data.get("locations") or ["toronto"]),
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
