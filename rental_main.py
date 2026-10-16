#!/usr/bin/env python3
"""Rental watcher using the existing Telegram environment, with separate state."""
from __future__ import annotations

import argparse
from html import escape
import logging
import os
from pathlib import Path
import sqlite3
import time

from dotenv import load_dotenv
import yaml

from src.rentals import scrape, search_url
from src.telegram_notifier import TelegramNotifier

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger('rental-bot')


def deliver(matches, db, telegram, *, seed=False, dry_run=False):
    """Track each recipient separately so a partial Telegram failure is retryable."""
    sent = 0
    db.execute('CREATE TABLE IF NOT EXISTS deliveries (listing_id TEXT, chat_id TEXT, PRIMARY KEY (listing_id, chat_id))')
    for listing in matches:
        if dry_run:
            print(listing.telegram_message())
            continue
        for chat_id in telegram.chat_ids:
            if db.execute('SELECT 1 FROM deliveries WHERE listing_id=? AND chat_id=?', (listing.listing_id, chat_id)).fetchone():
                continue
            if not seed and not telegram._send_one(chat_id, listing.telegram_message()):
                raise RuntimeError('Telegram delivery failed; unsent rentals will be retried')
            db.execute('INSERT INTO deliveries VALUES (?, ?)', (listing.listing_id, chat_id))
            db.commit()
            sent += 1
    return sent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--seed', action='store_true', help='Mark current matches seen without sending them')
    parser.add_argument('--dry-run', action='store_true', help='One scan; print matches without Telegram or saved history')
    parser.add_argument('--config', type=Path, default=ROOT / 'rental-config.yaml')
    args = parser.parse_args(argv)
    load_dotenv(ROOT / '.env')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    with args.config.open() as f:
        cfg = yaml.safe_load(f)
    search_url(cfg)  # Fail before sending messages or opening the browser.
    interval = int(cfg.get('poll_interval_minutes', 180))
    if interval <= 0:
        raise ValueError('poll_interval_minutes must be positive')
    telegram = None
    if not args.dry_run:
        telegram = TelegramNotifier(os.getenv('TELEGRAM_BOT_TOKEN', ''), os.getenv('TELEGRAM_CHAT_ID', ''))
    db_path = ROOT / 'data' / 'rentals.db'
    db_path.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(':memory:' if args.dry_run else db_path)
    try:
        while True:
            try:
                matches, rejected = scrape(cfg, headless=os.getenv('HEADLESS', 'true').lower() not in {'0', 'false', 'no'})
                sent = deliver(matches, db, telegram, seed=args.seed, dry_run=args.dry_run)
                logger.info('Rental scan verified: %d matches, %d deliveries; excluded: %s', len(matches), sent, rejected)
                if telegram and not args.seed and (sent or (args.once and os.getenv('RENTAL_SCAN_SUMMARY', 'true').lower() in {'true', '1', 'yes'})):
                    reasons = '\n'.join(f'{escape(reason)}: {count}' for reason, count in rejected.items())
                    telegram.send_text(f'🏠 Rental scan finished ({escape(cfg.get("source", "royallepage"))}): {len(matches)} matches, {sent} new deliveries.' + ('\nExcluded:\n' + reasons if reasons else ''))
            except Exception as exc:
                # Stop after access failures; never report a blocked request as zero matches.
                logger.error('Rental scan failed: %s', exc)
                if telegram and not args.seed:
                    telegram.send_text('⚠️ <b>Rental scan failed</b>\n' + escape(str(exc)[:600]))
                return 1
            if args.once or args.seed or args.dry_run:
                return 0
            time.sleep(interval * 60)
    except KeyboardInterrupt:
        return 0
    finally:
        db.close()
        if telegram:
            telegram.close()


if __name__ == '__main__':
    raise SystemExit(main())
