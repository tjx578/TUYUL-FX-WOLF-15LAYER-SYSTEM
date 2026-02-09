"""
Telegram Notifier
READ-ONLY alert delivery.
"""

import os

import requests
from loguru import logger

from alerts.alert_formatter import AlertFormatter
from alerts.alert_rules import ALERT_RULES


class TelegramNotifier:
    def __init__(self):
        self.enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def _send(self, text: str):
        if not self.enabled:
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as exc:
            logger.error(f"Telegram send error: {exc}")

    # =========================
    # PUBLIC EVENTS
    # =========================

    def on_l12_verdict(self, verdict: dict):
        if not ALERT_RULES["L12_PASSED"] and verdict.get("verdict", "").startswith(
            "EXECUTE"
        ):
            return

        text = AlertFormatter.format_l12_verdict(verdict)
        self._send(text)

    def on_order_event(self, event: str, state: dict):
        if not ALERT_RULES.get(event, False):
            return

        text = AlertFormatter.format_order_event(event, state)
        self._send(text)

    def on_violation(self, symbol: str, gate: str, reason: str):
        if not ALERT_RULES["SYSTEM_VIOLATION"]:
            return

        text = AlertFormatter.format_violation(symbol, gate, reason)
        self._send(text)
