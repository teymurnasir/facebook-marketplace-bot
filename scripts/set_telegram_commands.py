#!/usr/bin/env python3
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv


COMMANDS = [
    {"command": "scan", "description": "Run Marketplace search now"},
    {"command": "settings", "description": "View/change shared search filters"},
    {"command": "filters", "description": "Same as /settings"},
    {"command": "customsearch", "description": "One-off: city, radius, car, years, price, km"},
    {"command": "help", "description": "How this bot works"},
    {"command": "id", "description": "Show this chat id"},
    {"command": "cancel", "description": "Cancel settings wizard"},
]


def main() -> int:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Missing TELEGRAM_BOT_TOKEN")
        return 1

    with httpx.Client(timeout=20.0) as client:
        set_res = client.post(
            f"https://api.telegram.org/bot{token}/setMyCommands",
            json={"commands": COMMANDS},
        ).json()
        print("setMyCommands ok:", set_res.get("ok"), set_res.get("description"))

        get_res = client.get(
            f"https://api.telegram.org/bot{token}/getMyCommands"
        ).json()
        print("Current commands:")
        for cmd in get_res.get("result") or []:
            print(f"  /{cmd['command']} - {cmd['description']}")
    return 0 if set_res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
