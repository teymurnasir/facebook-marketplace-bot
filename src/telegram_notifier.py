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

    def _send_one(self, chat_id: str, text: str) -> bool:
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
            data = resp.json()
            if data.get("ok"):
                return True

            # Group upgraded to supergroup → Telegram returns new chat id
            params = data.get("parameters") or {}
            migrated = params.get("migrate_to_chat_id")
            if migrated is not None:
                new_id = str(migrated)
                logger.warning("Chat %s migrated to %s — retrying", chat_id, new_id)
                if new_id not in self.chat_ids:
                    self.chat_ids = [
                        new_id if c == chat_id else c for c in self.chat_ids
                    ]
                retry = self._client.post(
                    f"{self.base}/sendMessage",
                    json={
                        "chat_id": new_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    },
                )
                retry_data = retry.json()
                if retry_data.get("ok"):
                    return True
                logger.error("Telegram API error after migrate (%s): %s", new_id, retry_data)
                return False

            logger.error("Telegram API error (%s): %s", chat_id, data)
            return False
        except Exception:
            logger.exception("Failed to send Telegram message to %s", chat_id)
            return False

    def send_text(self, text: str) -> bool:
        delivered = 0
        for chat_id in list(self.chat_ids):
            if self._send_one(chat_id, text):
                delivered += 1
        logger.info("Telegram message accepted for %d/%d chat(s)", delivered, len(self.chat_ids))
        return delivered > 0

    def send_listing(self, listing: Listing) -> bool:
        return self.send_text(listing.telegram_message())

    def send_startup(self, interval_minutes: int, search_count: int) -> bool:
        return self.send_text(
            "✅ Marketplace watcher started\n"
            f"⏱ Every {interval_minutes} min · {search_count} search(es)\n"
            "🇨🇦 Facebook Marketplace (Canada)"
        )
