from __future__ import annotations

import logging

import httpx

from .models import Listing

logger = logging.getLogger(__name__)


def parse_chat_ids(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        ids = parse_chat_ids(chat_id)
        if not bot_token or not ids:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        self.bot_token = bot_token
        self.chat_ids = ids
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self._client = httpx.Client(timeout=30, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def send_text(self, text: str) -> bool:
        ok_any = False
        for chat_id in self.chat_ids:
            try:
                resp = self._client.post(
                    f"{self.base}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    logger.error("Telegram API error (%s): %s", chat_id, data)
                    continue
                ok_any = True
            except Exception:
                logger.exception("Failed to send Telegram message to %s", chat_id)
        return ok_any

    def send_listing(self, listing: Listing) -> bool:
        return self.send_text(listing.telegram_message())

    def send_startup(self, interval_minutes: int, search_count: int) -> bool:
        return self.send_text(
            "✅ Marketplace watcher started\n"
            f"⏱ Every {interval_minutes} min · {search_count} search(es)\n"
            "🇨🇦 Facebook Marketplace (Canada)"
        )
