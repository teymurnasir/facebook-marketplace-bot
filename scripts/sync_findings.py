"""Publish saved findings, optionally refreshing seller descriptions first."""

from __future__ import annotations

import logging
import os
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
        if os.environ.get("REFRESH_CAR_DETAILS") == "true":
            refresh_details(store)
        publish_findings(store.all_findings())
    finally:
        store.close()
    return 0


def refresh_details(store: SeenStore) -> None:
    import time

    from playwright.sync_api import sync_playwright
    from src.models import Listing
    from src.scraper import FacebookSessionError, MarketplaceScraper

    scraper = MarketplaceScraper("storage_state.json")
    verified = False
    with sync_playwright() as playwright:
        browser, context, _ = scraper._launch(playwright)
        try:
            for row in store.all_findings()[:30]:
                car = Listing(
                    row["listing_id"], row["title"] or "", row["price"] or "Price n/a",
                    row["price_amount"], row["location"] or "", row["url"] or "",
                    row["search_name"] or "", year=row["year"], mileage_km=row["mileage_km"],
                )
                try:
                    scraper._read_details(context, car)
                except FacebookSessionError:
                    verified = False
                    raise
                except Exception:
                    logging.exception("Description refresh failed for %s", car.listing_id)
                    continue
                if car.details_checked_at:
                    verified = True
                    store.update_details(car)
                time.sleep(2)
        finally:
            if verified:
                scraper._save_storage_state(context)
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
