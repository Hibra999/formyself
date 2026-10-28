"""Optional, outbound-only backtest notifications."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class TelegramNotifications:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self._token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        if bool(self._token) != bool(self._chat_id):
            raise ValueError("Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def _post(self, method: str, **kwargs) -> bool:
        if not self.enabled:
            return False
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self._token}/{method}",
                timeout=20,
                **kwargs,
            )
            if response.ok and response.json().get("ok") is True:
                return True
        except (requests.RequestException, ValueError):
            pass
        # Do not log the request exception: its URL includes the bot token.
        logger.warning("Telegram notification failed (%s)", method)
        return False

    def message(self, text: str) -> bool:
        return self._post("sendMessage", data={"chat_id": self._chat_id, "text": text[:4096]})

    def document(self, path: str | Path, caption: str = "") -> bool:
        if not self.enabled:
            return False
        with Path(path).open("rb") as report:
            return self._post(
                "sendDocument",
                data={"chat_id": self._chat_id, "caption": caption[:1024]},
                files={"document": report},
            )
