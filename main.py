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
from src.scraper import FacebookSessionError, MarketplaceScraper
from src.settings_sync import (
    ack_pending_scan,
    fetch_job_config,
    get_pending_scan,
    publish_findings,
    settings_enabled,
    sync_shared_settings,
    write_config_yaml,
)
from src.storage import SeenStore
from src.telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
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

    ignore_seen = env_bool("CUSTOM_SEARCH", False)
    if ignore_seen:
        scan_name = "Custom search"
    elif env_bool("MANUAL_SCAN", False):
        scan_name = "Manual /scan"
    else:
        scan_name = "Auto scan"

    def session_active() -> None:
        if notify and telegram is not None:
            telegram.send_text(
                "✅ <b>Facebook session active</b>\n"
                "Logged-in Marketplace data verified. Scan continuing."
            )

    if notify and telegram is not None:
        telegram.send_text(
            f"🔎 <b>{scan_name} started</b>\n"
            "Checking Facebook session and Marketplace access..."
        )

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
        on_session_active=session_active,
    )

    if not scraper.session_verified and notify and telegram is not None:
        telegram.send_text(
            "⚠️ <b>Facebook status not verified</b>\n"
            "No authenticated Marketplace listing data was detected. "
            "This can mean an empty search, a loading problem, or restricted access. "
            "Open Facebook Marketplace in your browser to check."
        )

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

    if settings_enabled():
        try:
            publish_findings(store.all_findings())
        except Exception:
            logger.exception("Could not sync database findings for Telegram /cars")
            if notify and telegram is not None:
                telegram.send_text(
                    "⚠️ Saved car list could not be synced. "
                    "/cars may show the previous scan's database until the next successful sync."
                )

    logger.info("Cycle done: %d scraped, %d new", len(listings), new_count)
    if notify and telegram is not None and env_bool("TELEGRAM_SCAN_SUMMARY", True):
        prefix = f"{'✅' if scraper.session_verified else '⚠️'} {scan_name}"
        status = (
            "Facebook session active: Marketplace data verified."
            if scraper.session_verified
            else "Facebook status not verified."
        )
        if new_count:
            telegram.send_text(
                f"{prefix} finished — <b>{new_count}</b> listing(s) sent above.\n{status}"
            )
        else:
            telegram.send_text(
                f"{prefix} finished — no matching cars "
                f"(checked {len(listings)} match(es)).\n{status}"
            )
    return new_count


def _prepare_cycle(root: Path) -> tuple[dict, int, bool, dict | None]:
    """
    Sync Telegram settings / pending /scan job.
    Returns (cfg, interval_minutes, custom_search, pending_payload_or_none).
    """
    config_path = root / "config.yaml"
    custom = False
    interval = int(os.getenv("POLL_INTERVAL_MINUTES", "30"))
    pending_payload = None

    pending = None
    if settings_enabled():
        try:
            pending = get_pending_scan()
        except Exception:
            logger.exception("Could not check pending Telegram /scan")

    if pending:
        job_id = pending.get("job_id")
        try:
            if job_id:
                raw = fetch_job_config(str(job_id))
                write_config_yaml(raw, config_path)
                custom = True
                logger.info("Loaded custom Telegram job %s", job_id)
            else:
                live_interval = sync_shared_settings(config_path)
                if live_interval is not None:
                    interval = live_interval
            pending_payload = pending
        except Exception:
            logger.exception("Failed to load pending Telegram scan")
    elif settings_enabled():
        try:
            live_interval = sync_shared_settings(config_path)
            if live_interval is not None:
                interval = live_interval
        except Exception:
            logger.exception("Failed to sync Telegram /settings; using local config.yaml")

    os.environ["CUSTOM_SEARCH"] = "1" if custom else "0"
    # MANUAL_SCAN = Telegram /scan (pending without job_id), not the quiet auto timer.
    os.environ["MANUAL_SCAN"] = (
        "1" if (pending_payload is not None and not custom) else "0"
    )
    cfg = load_config(config_path)
    return cfg, interval, custom, pending_payload


def _sleep_with_pending_checks(interval_min: int) -> bool:
    """
    Sleep until the next auto scan, but wake early if Telegram queues /scan.
    Returns True if a pending scan arrived.
    """
    total = max(1, interval_min) * 60
    step = 30
    slept = 0
    logger.info("Sleeping %d minutes (checking Telegram /scan every %ds)…", interval_min, step)
    while slept < total:
        time.sleep(min(step, total - slept))
        slept += step
        if not settings_enabled():
            continue
        try:
            pending = get_pending_scan()
        except Exception:
            logger.exception("Pending-scan poll failed")
            continue
        if pending:
            logger.info("Telegram /scan queued — waking early")
            return True
    return False


def main() -> int:
    load_dotenv()
    root = Path(__file__).resolve().parent
    os.chdir(root)

    once = "--once" in sys.argv
    seed = "--seed" in sys.argv  # mark current results seen without Telegram

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not seed and (not token or not chat_id):
        logger.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return 1

    if settings_enabled():
        logger.info("Local scanner mode: Telegram /settings + /scan via Cloudflare Worker")
    else:
        logger.warning(
            "SETTINGS_CONFIG_URL / SETTINGS_CONFIG_TOKEN not set — "
            "using local config.yaml only (Telegram /settings will not sync)"
        )

    store = SeenStore(root / "data" / "seen.db")
    headless = env_bool("HEADLESS", True)
    storage_state = os.getenv("FACEBOOK_STORAGE_STATE", "storage_state.json")
    telegram = TelegramNotifier(token, chat_id) if token and chat_id else None

    cfg, interval, _custom, _pending = _prepare_cycle(root)
    scraper = MarketplaceScraper(
        storage_state_path=storage_state,
        headless=headless,
        timeout_ms=cfg["scraper"]["timeout_ms"],
    )

    # Announce only when the long-running process boots (not every --once / CI tick)
    if telegram and not seed and not once and env_bool("STARTUP_NOTIFY", True):
        if not telegram.send_startup(interval, len(cfg["searches"])):
            logger.error("Telegram startup message failed — check bot token / chat id")
            store.close()
            telegram.close()
            return 1

    logger.info(
        "Watching %d searches × %d area(s) every %d min (seed=%s once=%s local_sync=%s)",
        len(cfg["searches"]),
        len(cfg.get("market_areas") or cfg["locations"]),
        interval,
        seed,
        once,
        settings_enabled(),
    )

    try:
        while True:
            cfg, interval, custom, pending_payload = _prepare_cycle(root)
            scraper.timeout_ms = cfg["scraper"]["timeout_ms"]

            if pending_payload is not None:
                try:
                    ack_pending_scan(pending_payload.get("requested_at"))
                except Exception:
                    logger.exception("Could not ack pending Telegram /scan")
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
                    if isinstance(exc, FacebookSessionError):
                        telegram.send_text(
                            "❌ <b>Facebook session inactive - login needed</b>\n"
                            "Facebook requested login or a security checkpoint. Scan stopped.\n\n"
                            "Log in using <code>python -m src.save_session</code>, "
                            "update GitHub secret <code>FACEBOOK_STORAGE_STATE_B64</code>, "
                            "and clear the old <code>fb-session-v2-</code> GitHub Actions caches. "
                            "Then send /scan to test again."
                        )
                    else:
                        telegram.send_text(
                            "❌ <b>Marketplace scan failed</b>\n"
                            "Facebook access was not confirmed for the full scan.\n"
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
            _sleep_with_pending_checks(interval)
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
