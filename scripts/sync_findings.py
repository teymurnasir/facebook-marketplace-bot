"""Publish the existing scan database to Telegram without contacting Facebook."""

from __future__ import annotations

import logging
from pathlib import Path

from src.settings_sync import publish_findings, settings_enabled
from src.storage import SeenStore


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    path = Path(__file__).resolve().parents[1] / "data" / "seen.db"
    if not path.is_file():
        raise RuntimeError("Saved scan database missing; refusing to publish an empty replacement")
    if not settings_enabled():
        raise RuntimeError("Shared settings credentials are required to sync /cars")
    store = SeenStore(path)
    try:
        publish_findings(store.all_findings())
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
