from __future__ import annotations

import logging

import httpx

from .models import Listing

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self._client = httpx.Client(timeout=30)

    def close(self) -> None:
        self._client.close()

    def send_text(self, text: str) -> bool:
        try:
            resp = self._client.post(
                f"{self.base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error("Telegram API error: %s", data)
                return False
            return True
        except Exception:
            logger.exception("Failed to send Telegram message")
            return False

    def send_listing(self, listing: Listing) -> bool:
        return self.send_text(listing.telegram_message())

    def send_startup(self, interval_minutes: int, search_count: int) -> bool:
        return self.send_text(
            "✅ Marketplace watcher started\n"
            f"⏱ Every {interval_minutes} min · {search_count} search(es)\n"
            "🇨🇦 Facebook Marketplace (Canada)"
        )
