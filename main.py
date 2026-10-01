#!/usr/bin/env python3
"""Poll Canadian Facebook Marketplace and Telegram new car listings."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.config_loader import load_config
from src.scraper import MarketplaceScraper
from src.storage import SeenStore
from src.telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("marketplace-bot")


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def run_once(
    scraper: MarketplaceScraper,
    store: SeenStore,
    telegram: TelegramNotifier | None,
    cfg: dict,
    *,
    notify: bool,
) -> int:
    areas = cfg.get("market_areas") or []
    if not cfg.get("searches"):
        logger.error("No car searches configured — aborting")
        if notify and telegram is not None:
            telegram.send_text(
                "⚠️ Scan skipped — no cars in settings. Use /settings to add a car."
            )
        return 0
    if not areas and not cfg.get("locations"):
        logger.error("No locations configured — aborting")
        if notify and telegram is not None:
            telegram.send_text(
                "⚠️ Scan skipped — no locations in settings. "
                "Use /settings → Locations to add a city + km radius."
            )
        return 0

    listings = scraper.run_cycle(
        searches=cfg["searches"],
        locations=cfg["locations"],
        location_keywords=cfg["location_keywords"],
        sort_by=cfg["scraper"]["sort_by"],
        max_scrolls=cfg["scraper"]["max_scrolls"],
        delay_between_searches_sec=cfg["scraper"]["delay_between_searches_sec"],
        url_modes=cfg["scraper"].get("url_modes"),
        search_mode_locations=cfg["scraper"].get("search_mode_locations"),
        market_areas=areas,
    )

    # Custom one-off searches re-send matches even if already in seen.db
    ignore_seen = env_bool("CUSTOM_SEARCH", False)

    new_count = 0
    for listing in listings:
        if not ignore_seen and store.is_seen(listing.listing_id):
            continue
        new_count += 1
        logger.info("NEW: %s | %s | %s", listing.title, listing.price, listing.url)
        if notify and telegram is not None:
            ok = telegram.send_listing(listing)
            if not ok:
                logger.warning("Telegram send failed; will retry next cycle")
                continue
        store.mark_seen(
            listing.listing_id,
            search_name=listing.search_name,
            title=listing.title,
            url=listing.url,
        )

    logger.info("Cycle done: %d scraped, %d new", len(listings), new_count)
    if notify and telegram is not None and env_bool("TELEGRAM_SCAN_SUMMARY", True):
        prefix = "🔎 Custom search" if ignore_seen else "✅ Scan"
        if new_count:
            telegram.send_text(
                f"{prefix} finished — <b>{new_count}</b> listing(s) sent above."
            )
        else:
            telegram.send_text(
                f"{prefix} finished — no matching cars "
                f"(checked {len(listings)} raw match(es))."
            )
    return new_count


def main() -> int:
    load_dotenv()
    root = Path(__file__).resolve().parent
    os.chdir(root)

    cfg = load_config(root / "config.yaml")
    interval = int(os.getenv("POLL_INTERVAL_MINUTES", "30"))
    headless = env_bool("HEADLESS", True)
    storage_state = os.getenv("FACEBOOK_STORAGE_STATE", "storage_state.json")
    once = "--once" in sys.argv
    seed = "--seed" in sys.argv  # mark current results seen without Telegram

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not seed and (not token or not chat_id):
        logger.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return 1

    store = SeenStore(root / "data" / "seen.db")
    scraper = MarketplaceScraper(
        storage_state_path=storage_state,
        headless=headless,
        timeout_ms=cfg["scraper"]["timeout_ms"],
    )
    telegram = TelegramNotifier(token, chat_id) if token and chat_id else None

    # Announce only when the long-running process boots (not every --once / CI tick)
    if telegram and not seed and not once and env_bool("STARTUP_NOTIFY", True):
        if not telegram.send_startup(interval, len(cfg["searches"])):
            logger.error("Telegram startup message failed — check bot token / chat id")
            store.close()
            telegram.close()
            return 1

    logger.info(
        "Watching %d searches × %d area(s) every %d min (seed=%s once=%s custom=%s)",
        len(cfg["searches"]),
        len(cfg.get("market_areas") or cfg["locations"]),
        interval,
        seed,
        once,
        env_bool("CUSTOM_SEARCH", False),
    )

    try:
        while True:
            if telegram and once and not seed:
                telegram.send_text(
                    "🚀 Marketplace scan is running now…\n"
                    "Please wait — results will arrive in this chat."
                )
            try:
                run_once(
                    scraper,
                    store,
                    telegram,
                    cfg,
                    notify=bool(telegram) and not seed,
                )
            except Exception as exc:
                logger.exception("Scan failed")
                if telegram and not seed:
                    telegram.send_text(
                        "❌ <b>Marketplace scan failed</b>\n"
                        f"<code>{type(exc).__name__}: {_escape_tg(str(exc)[:500])}</code>\n\n"
                        "See GUIDE.html → Errors for what to do."
                    )
                if once or seed:
                    return 1
            if seed:
                logger.info("Seed complete — existing listings marked seen, no Telegram spam")
                break
            if once:
                break
            logger.info("Sleeping %d minutes…", interval)
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    finally:
        store.close()
        if telegram:
            telegram.close()

    return 0


def _escape_tg(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


if __name__ == "__main__":
    raise SystemExit(main())
