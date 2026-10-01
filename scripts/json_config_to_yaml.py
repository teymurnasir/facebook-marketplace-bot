#!/usr/bin/env python3
"""Convert live settings JSON (from Telegram webhook) into config.yaml."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: json_config_to_yaml.py input.json output.yaml", file=sys.stderr)
        return 1
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    data = json.loads(src.read_text(encoding="utf-8"))
    # Keep key order readable
    ordered = {
        "max_mileage_km": data.get("max_mileage_km", 250000),
        "locations": data.get("locations") or [],
        "location_keywords": data.get("location_keywords") or [],
        "searches": data.get("searches") or [],
        "scraper": data.get("scraper") or {},
    }
    dst.write_text(
        yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Wrote {dst} ({len(ordered['searches'])} searches, {len(ordered['locations'])} hubs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
