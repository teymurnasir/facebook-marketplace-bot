from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import SearchConfig


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    searches = []
    for raw in data.get("searches", []):
        searches.append(
            SearchConfig(
                name=raw["name"],
                query=raw["query"],
                min_year=int(raw["min_year"]),
                max_year=int(raw["max_year"]),
                min_price=int(raw["min_price"]),
                max_price=int(raw["max_price"]),
                must_include_any=list(raw.get("must_include_any") or []),
                must_include_all=list(raw.get("must_include_all") or []),
                body_styles=list(raw.get("body_styles") or []),
                require_body_style=bool(raw.get("require_body_style", False)),
            )
        )

    scraper = data.get("scraper") or {}
    return {
        "locations": list(data.get("locations") or ["toronto"]),
        "location_keywords": list(data.get("location_keywords") or []),
        "searches": searches,
        "scraper": {
            "sort_by": scraper.get("sort_by", "creation_time_descend"),
            "max_scrolls": int(scraper.get("max_scrolls", 3)),
            "delay_between_searches_sec": float(
                scraper.get("delay_between_searches_sec", 4)
            ),
            "timeout_ms": int(scraper.get("timeout_ms", 45000)),
        },
    }
