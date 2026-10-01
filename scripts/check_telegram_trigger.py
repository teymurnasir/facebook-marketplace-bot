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
ID_COMMANDS = {"/id", "/chatid"}


def _authorized_ids() -> set[str]:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _send(client: httpx.Client, base: str, chat_id: str | int, text: str) -> None:
    client.post(
        f"{base}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def main() -> int:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    allowed = _authorized_ids()
    if not allowed:
        print("TELEGRAM_CHAT_ID missing", file=sys.stderr)
        return 1

    offset_path = Path(os.environ.get("TELEGRAM_OFFSET_PATH", "data/telegram_offset.txt"))
    offset_path.parent.mkdir(parents=True, exist_ok=True)

    offset = 0
    if offset_path.exists():
        raw = offset_path.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            offset = int(raw)

    base = f"https://api.telegram.org/bot{token}"
    with httpx.Client(timeout=30, trust_env=False) as client:
        # Make /scan show in Telegram command menu
        client.post(
            f"{base}/setMyCommands",
            json={
                "commands": [
                    {"command": "scan", "description": "Run saved Marketplace filters"},
                    {"command": "settings", "description": "Shared cars, km, locations+radius"},
                    {"command": "customsearch", "description": "One-off custom car search (not saved)"},
                    {"command": "filters", "description": "Same as /settings"},
                    {"command": "help", "description": "How this Canada bot works"},
                    {"command": "id", "description": "Show this chat's Telegram id"},
                    {"command": "cancel", "description": "Cancel current wizard"},
                ]
            },
        )

        resp = client.get(
            f"{base}/getUpdates",
            params={
                "offset": offset,
                "timeout": 0,
                "allowed_updates": json.dumps(["message"]),
            },
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
            chat_id = chat.get("id")
            if chat_id is None:
                continue
            chat_id_s = str(chat_id)
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            cmd = text.split()[0].split("@")[0].lower()

            if cmd in ID_COMMANDS:
                _send(
                    client,
                    base,
                    chat_id,
                    (
                        f"Chat id: `{chat_id}`\n"
                        f"Type: {chat.get('type')}\n"
                        f"Title: {chat.get('title') or chat.get('first_name') or 'n/a'}\n\n"
                        "Put this value in GitHub secret TELEGRAM_CHAT_ID "
                        "(comma-separated if several chats)."
                    ).replace("`", ""),
                )
                continue

            if cmd in HELP_COMMANDS:
                _send(
                    client,
                    base,
                    chat_id,
                    (
                        "🇨🇦 Canada Marketplace car alerts\n\n"
                        "Commands:\n"
                        "/scan — start a search now\n"
                        "/id — show this chat’s id\n"
                        "/help — this message\n\n"
                        "Also runs automatically every 30 minutes.\n"
                        "Same cars are never sent twice."
                    ),
                )
                continue

            if cmd in COMMANDS:
                if chat_id_s not in allowed:
                    _send(
                        client,
                        base,
                        chat_id,
                        (
                            "⚠️ This chat is not authorized for /scan yet.\n\n"
                            f"This chat id is: {chat_id}\n"
                            "Add it to GitHub secret TELEGRAM_CHAT_ID, then try /scan again."
                        ),
                    )
                    continue

                trigger = True
                _send(
                    client,
                    base,
                    chat_id,
                    (
                        "🔎 Scan request received!\n"
                        "⏳ Starting Marketplace search on GitHub…\n"
                        "⏱ Usually 3–10 minutes.\n"
                        "📬 Only NEW cars will be posted (no duplicates)."
                    ),
                )

        if updates:
            offset_path.write_text(str(max_update_id + 1), encoding="utf-8")
        elif not offset_path.exists():
            offset_path.write_text("0", encoding="utf-8")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"should_scan={'true' if trigger else 'false'}\n")

    next_offset = (
        offset_path.read_text(encoding="utf-8").strip() if offset_path.exists() else "0"
    )
    print(f"updates={len(updates)} trigger={trigger} next_offset={next_offset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
