#!/usr/bin/env python3
"""Poll Telegram for /scan and signal GitHub Actions to start a Marketplace run."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

COMMANDS = {"/scan", "/search", "/run"}
HELP_COMMANDS = {"/start", "/help"}


def main() -> int:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = str(os.environ["TELEGRAM_CHAT_ID"])
    offset_path = Path(os.environ.get("TELEGRAM_OFFSET_PATH", "data/telegram_offset.txt"))
    offset_path.parent.mkdir(parents=True, exist_ok=True)

    offset = 0
    if offset_path.exists():
        raw = offset_path.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            offset = int(raw)

    base = f"https://api.telegram.org/bot{token}"
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{base}/getUpdates",
            params={"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message"])},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            print(f"Telegram error: {data}", file=sys.stderr)
            return 1

        updates = data.get("result") or []
        trigger = False
        max_update_id = offset - 1 if offset else 0

        for upd in updates:
            uid = int(upd.get("update_id", 0))
            max_update_id = max(max_update_id, uid)
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            if str(chat.get("id")) != chat_id:
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            cmd = text.split()[0].split("@")[0].lower()

            if cmd in HELP_COMMANDS:
                client.post(
                    f"{base}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": (
                            "🇨🇦 Marketplace bot commands:\n"
                            "/scan — run a search now (GitHub Actions)\n"
                            "/help — show this message\n\n"
                            "Automatic scans also run every 30 minutes."
                        ),
                    },
                )
                continue

            if cmd in COMMANDS:
                trigger = True
                client.post(
                    f"{base}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": "🔎 Got it — starting a Marketplace scan on GitHub now…",
                    },
                )

        if updates:
            # Advance offset so the same messages are not handled again
            offset_path.write_text(str(max_update_id + 1), encoding="utf-8")
        elif not offset_path.exists():
            offset_path.write_text("0", encoding="utf-8")

    # GitHub Actions expression-friendly outputs
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"should_scan={'true' if trigger else 'false'}\n")

    next_offset = offset_path.read_text(encoding="utf-8").strip() if offset_path.exists() else "0"
    print(f"updates={len(updates)} trigger={trigger} next_offset={next_offset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
