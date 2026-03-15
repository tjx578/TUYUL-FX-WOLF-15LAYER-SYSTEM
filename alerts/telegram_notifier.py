"""
Telegram Notifier
READ-ONLY alert delivery — multi-channel notification system.
"""

from __future__ import annotations

import os

import requests
from loguru import logger

from alerts.alert_formatter import AlertFormatter
from alerts.alert_rules import ALERT_RULES


class TelegramNotifier:
    def __init__(self) -> None:
        self.enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        # Optional separate channel for critical alerts
        self.critical_chat_id = os.getenv("TELEGRAM_CRITICAL_CHAT_ID") or self.chat_id

    def _send(self, text: str, critical: bool = False) -> None:
        if not self.enabled:
            return

        chat_id = self.critical_chat_id if critical else self.chat_id
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as exc:
            logger.error(f"Telegram send error: {exc}")

    # =========================
    # ORIGINAL EVENTS
    # =========================

    def on_l12_verdict(self, verdict: dict) -> None:
        if not ALERT_RULES["L12_PASSED"] and verdict.get("verdict", "").startswith("EXECUTE"):
            return

        text = AlertFormatter.format_l12_verdict(verdict)
        self._send(text)

    def on_order_event(self, event: str, state: dict) -> None:
        if not ALERT_RULES.get(event, False):
            return

        text = AlertFormatter.format_order_event(event, state)
        self._send(text)

    def on_violation(self, symbol: str, gate: str, reason: str) -> None:
        if not ALERT_RULES["SYSTEM_VIOLATION"]:
            return

        text = AlertFormatter.format_violation(symbol, gate, reason)
        self._send(text, critical=True)

    # =========================
    # NEW COMPREHENSIVE ALERTS
    # =========================

    def on_feed_stale(self, symbol: str, age_seconds: float) -> None:
        """Alert when a symbol feed has not received ticks beyond threshold."""
        if not ALERT_RULES.get("FEED_STALE", False):
            return

        text = AlertFormatter.format_feed_stale(symbol, age_seconds)
        critical = age_seconds > 30
        self._send(text, critical=critical)

    def on_drawdown_alert(
        self,
        account_id: str,
        drawdown_percent: float,
        daily_loss_percent: float,
        severity: str = "WARNING",
    ) -> None:
        """Alert on drawdown threshold breach."""
        rule_key = "DRAWDOWN_CRITICAL" if severity == "CRITICAL" else "DRAWDOWN_WARNING"
        if not ALERT_RULES.get(rule_key, False):
            return

        text = AlertFormatter.format_drawdown_alert(account_id, drawdown_percent, daily_loss_percent, severity)
        self._send(text, critical=(severity == "CRITICAL"))

    def on_daily_loss_alert(
        self,
        account_id: str,
        daily_loss_percent: float,
        severity: str = "WARNING",
    ) -> None:
        """Alert when daily loss approaches or exceeds prop firm limit."""
        rule_key = "DAILY_LOSS_CRITICAL" if severity == "CRITICAL" else "DAILY_LOSS_WARNING"
        if not ALERT_RULES.get(rule_key, False):
            return

        text = AlertFormatter.format_drawdown_alert(
            account_id,
            drawdown_percent=0.0,
            daily_loss_percent=daily_loss_percent,
            severity=severity,
        )
        self._send(text, critical=(severity == "CRITICAL"))

    def on_kill_switch(self, reason: str) -> None:
        """Alert when kill switch is tripped — multi-channel critical."""
        if not ALERT_RULES.get("KILL_SWITCH_TRIPPED", False):
            return

        text = AlertFormatter.format_kill_switch(reason)
        # Always send to critical channel
        self._send(text, critical=True)

    def on_circuit_breaker(self, name: str, state: str, failures: int) -> None:
        """Alert on circuit breaker state transitions."""
        if not ALERT_RULES.get("CIRCUIT_BREAKER_OPEN", False):
            return

        text = AlertFormatter.format_circuit_breaker(name, state, failures)
        critical = state == "OPEN"
        self._send(text, critical=critical)

    def on_pipeline_latency(self, latency_seconds: float, stage: str) -> None:
        """Alert when pipeline latency exceeds threshold."""
        if not ALERT_RULES.get("PIPELINE_LATENCY_HIGH", False):
            return

        text = AlertFormatter.format_pipeline_latency(latency_seconds, stage)
        self._send(text)
