#!/usr/bin/env python3
"""Convert live settings JSON (from Telegram webhook) into config.yaml."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def normalize(data: dict) -> dict:
    fallback_km = int(data.get("max_mileage_km") or 250000)
    searches = []
    for s in data.get("searches") or []:
        s = dict(s)
        if s.get("max_mileage_km") is None:
            s["max_mileage_km"] = fallback_km
        searches.append(s)

    market_areas = list(data.get("market_areas") or [])
    if not market_areas and data.get("locations"):
        # Migrate old list → only first city (user adds more in Telegram)
        slug = data["locations"][0]
        market_areas.append(
            {
                "slug": slug,
                "label": str(slug).replace("-", " ").title() + ", ON",
                "radius_km": 65,
            }
        )

    locations = [a["slug"] for a in market_areas]

    return {
        "country": data.get("country") or "CA",
        "max_mileage_km": fallback_km,
        "market_areas": market_areas,
        "locations": locations,
        "location_keywords": data.get("location_keywords") or [],
        "searches": searches,
        "scraper": data.get("scraper") or {},
    }


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: json_config_to_yaml.py input.json output.yaml", file=sys.stderr)
        return 1
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    data = normalize(json.loads(src.read_text(encoding="utf-8")))
    dst.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        f"Wrote {dst} ({len(data['searches'])} searches, "
        f"{len(data['market_areas'])} areas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
