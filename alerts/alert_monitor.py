"""
Alert Monitor — watches metrics and fires alerts when thresholds are breached.

Zone: monitoring/ — read-only observation. No execution authority.

This module periodically evaluates metric values against configured
thresholds (from ``alerts.alert_rules.AlertThresholds``) and dispatches
notifications through the ``TelegramNotifier`` when conditions are met.

Designed to run as an async background task inside the engine or API service.
Uses hysteresis (cooldown) to prevent alert storms.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from alerts.alert_rules import ALERT_RULES, DEFAULT_THRESHOLDS, AlertThresholds
from alerts.telegram_notifier import TelegramNotifier
from core.metrics import (
    CIRCUIT_BREAKER_STATE,
    DAILY_LOSS_PERCENT,
    DRAWDOWN_MAX_PERCENT,
    FEED_AGE,
    FEED_STALE_TOTAL,
    KILL_SWITCH_ACTIVE,
)

logger = logging.getLogger(__name__)


@dataclass
class _AlertCooldown:
    """Tracks per-alert-key cooldown to avoid storm flooding."""

    last_fired: dict[str, float] = field(default_factory=dict)
    cooldown_seconds: float = 120.0  # 2 minutes between repeat alerts

    def should_fire(self, key: str) -> bool:
        now = time.monotonic()
        last = self.last_fired.get(key, 0.0)
        if now - last >= self.cooldown_seconds:
            self.last_fired[key] = now
            return True
        return False


class AlertMonitor:
    """
    Evaluates current metric state against thresholds and fires alerts.

    Call ``evaluate()`` periodically (e.g. every 10s) from an async loop.
    Thread-safe: reads only from the shared MetricsRegistry.
    """

    def __init__(
        self,
        notifier: TelegramNotifier | None = None,
        thresholds: AlertThresholds | None = None,
    ) -> None:
        self._notifier = notifier or TelegramNotifier()
        self._thresholds = thresholds or DEFAULT_THRESHOLDS
        self._cooldown = _AlertCooldown()

    def evaluate(self) -> list[dict]:
        """
        Run a single evaluation pass over all metric thresholds.

        Returns a list of alert dicts that were fired (for testing/logging).
        """
        fired: list[dict] = []
        fired.extend(self._check_feed_staleness())
        fired.extend(self._check_heartbeat_absence())
        fired.extend(self._check_mass_staleness())
        fired.extend(self._check_drawdown())
        fired.extend(self._check_kill_switch())
        fired.extend(self._check_circuit_breakers())
        return fired

    def _feed_age_samples(self) -> list[tuple[str, float]]:
        samples: list[tuple[str, float]] = []
        for key, child in FEED_AGE._children.items():
            labels = dict(key)
            symbol = labels.get("symbol", "UNKNOWN")
            samples.append((symbol, float(child.value)))
        return samples

    def _check_feed_staleness(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("FEED_STALE", False):
            return fired

        for symbol, age in self._feed_age_samples():

            if age > self._thresholds.feed_stale_critical_seconds:
                alert_key = f"feed_stale_critical:{symbol}"
                if self._cooldown.should_fire(alert_key):
                    FEED_STALE_TOTAL.labels(symbol=symbol).inc()
                    self._notifier.on_feed_stale(symbol, age)
                    alert = {"type": "FEED_STALE", "symbol": symbol, "age": age, "severity": "CRITICAL"}
                    fired.append(alert)
                    logger.warning("Feed stale CRITICAL: %s at %.1fs", symbol, age)

            elif age > self._thresholds.feed_stale_warning_seconds:
                alert_key = f"feed_stale_warning:{symbol}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_feed_stale(symbol, age)
                    alert = {"type": "FEED_STALE", "symbol": symbol, "age": age, "severity": "WARNING"}
                    fired.append(alert)
                    logger.info("Feed stale WARNING: %s at %.1fs", symbol, age)

        return fired

    def _check_heartbeat_absence(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("HEARTBEAT_ABSENT", False):
            return fired

        samples = self._feed_age_samples()
        if not samples:
            return fired

        freshest_age = min(age for _, age in samples)
        if freshest_age <= self._thresholds.heartbeat_absent_seconds:
            return fired

        alert_key = "heartbeat_absent"
        if self._cooldown.should_fire(alert_key):
            self._notifier.on_heartbeat_absent(freshest_age)
            fired.append(
                {
                    "type": "HEARTBEAT_ABSENT",
                    "age": freshest_age,
                    "symbols": len(samples),
                    "severity": "CRITICAL",
                }
            )
            logger.error("Heartbeat absent: freshest feed age %.1fs across %d symbols", freshest_age, len(samples))

        return fired

    def _check_mass_staleness(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("MASS_FEED_STALENESS", False):
            return fired

        samples = self._feed_age_samples()
        total_symbols = len(samples)
        if total_symbols == 0:
            return fired

        stale_count = sum(
            1
            for _, age in samples
            if age > self._thresholds.feed_stale_warning_seconds
        )

        stale_ratio = stale_count / total_symbols
        minimum_symbols_hit = stale_count >= self._thresholds.mass_staleness_min_symbols
        ratio_hit = stale_ratio >= self._thresholds.mass_staleness_ratio
        if not (minimum_symbols_hit and ratio_hit):
            return fired

        alert_key = "mass_feed_staleness"
        if self._cooldown.should_fire(alert_key):
            self._notifier.on_mass_staleness(
                stale_count=stale_count,
                total_symbols=total_symbols,
                threshold_seconds=self._thresholds.feed_stale_warning_seconds,
            )
            fired.append(
                {
                    "type": "MASS_FEED_STALENESS",
                    "stale_count": stale_count,
                    "total_symbols": total_symbols,
                    "stale_ratio": stale_ratio,
                    "severity": "CRITICAL",
                }
            )
            logger.error(
                "Mass feed staleness: %d/%d symbols stale (%.1f%%)",
                stale_count,
                total_symbols,
                stale_ratio * 100.0,
            )

        return fired

    def _check_drawdown(self) -> list[dict]:
        fired: list[dict] = []

        # Check daily loss
        for key, child in DAILY_LOSS_PERCENT._children.items():
            labels = dict(key)
            account_id = labels.get("account_id", "default")
            daily_loss = child.value

            if daily_loss > self._thresholds.daily_loss_critical_percent:
                alert_key = f"daily_loss_critical:{account_id}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_daily_loss_alert(account_id, daily_loss, "CRITICAL")
                    fired.append(
                        {
                            "type": "DAILY_LOSS_CRITICAL",
                            "account_id": account_id,
                            "daily_loss_percent": daily_loss,
                        }
                    )
                    logger.error("Daily loss CRITICAL: %s at %.2f%%", account_id, daily_loss)

            elif daily_loss > self._thresholds.daily_loss_warning_percent:
                alert_key = f"daily_loss_warning:{account_id}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_daily_loss_alert(account_id, daily_loss, "WARNING")
                    fired.append(
                        {
                            "type": "DAILY_LOSS_WARNING",
                            "account_id": account_id,
                            "daily_loss_percent": daily_loss,
                        }
                    )
                    logger.warning("Daily loss WARNING: %s at %.2f%%", account_id, daily_loss)

        # Check max drawdown
        for key, child in DRAWDOWN_MAX_PERCENT._children.items():
            labels = dict(key)
            account_id = labels.get("account_id", "default")
            dd = child.value

            if dd > self._thresholds.max_drawdown_critical_percent:
                alert_key = f"drawdown_critical:{account_id}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_drawdown_alert(account_id, dd, 0.0, "CRITICAL")
                    fired.append(
                        {
                            "type": "DRAWDOWN_CRITICAL",
                            "account_id": account_id,
                            "drawdown_percent": dd,
                        }
                    )
                    logger.error("Drawdown CRITICAL: %s at %.2f%%", account_id, dd)

            elif dd > self._thresholds.max_drawdown_warning_percent:
                alert_key = f"drawdown_warning:{account_id}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_drawdown_alert(account_id, dd, 0.0, "WARNING")
                    fired.append(
                        {
                            "type": "DRAWDOWN_WARNING",
                            "account_id": account_id,
                            "drawdown_percent": dd,
                        }
                    )
                    logger.warning("Drawdown WARNING: %s at %.2f%%", account_id, dd)

        return fired

    def _check_kill_switch(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("KILL_SWITCH_TRIPPED", False):
            return fired

        if KILL_SWITCH_ACTIVE._no_label and KILL_SWITCH_ACTIVE._no_label.value == 1.0:
            alert_key = "kill_switch"
            if self._cooldown.should_fire(alert_key):
                self._notifier.on_kill_switch("Metric-triggered kill switch")
                fired.append({"type": "KILL_SWITCH_TRIPPED"})
                logger.critical("KILL SWITCH TRIPPED")

        return fired

    def _check_circuit_breakers(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("CIRCUIT_BREAKER_OPEN", False):
            return fired

        for key, child in CIRCUIT_BREAKER_STATE._children.items():
            labels = dict(key)
            name = labels.get("name", "unknown")
            state_val = int(child.value)

            if state_val == 2:  # OPEN
                alert_key = f"cb_open:{name}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_circuit_breaker(name, "OPEN", 0)
                    fired.append({"type": "CIRCUIT_BREAKER_OPEN", "name": name})
                    logger.error("Circuit breaker OPEN: %s", name)
            elif state_val == 1:  # HALF_OPEN
                alert_key = f"cb_halfopen:{name}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_circuit_breaker(name, "HALF_OPEN", 0)
                    fired.append({"type": "CIRCUIT_BREAKER_HALF_OPEN", "name": name})

        return fired
