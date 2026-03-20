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
        fired.extend(self._check_v11_latency_budget())
        fired.extend(self._check_exec_latency_budget())
        fired.extend(self._check_anomaly_rates())
        fired.extend(self._check_reconnect_storm())
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

        stale_count = sum(1 for _, age in samples if age > self._thresholds.feed_stale_warning_seconds)

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

    # ═══════════════════════════════════════════════════════════════════════
    #  P2-8: Latency budget + anomaly rate checks
    # ═══════════════════════════════════════════════════════════════════════

    def _check_v11_latency_budget(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("V11_LATENCY_BUDGET", False):
            return fired

        try:
            from monitoring.v11_metrics import v11_all_latency_summaries  # noqa: PLC0415

            for symbol, summary in v11_all_latency_summaries().items():
                if summary.count < self._thresholds.rate_alert_min_samples:
                    continue

                p95_budget = self._thresholds.v11_latency_p95_budget_ms
                p99_budget = self._thresholds.v11_latency_p99_budget_ms

                if summary.p99 > p99_budget:
                    severity = "CRITICAL"
                elif summary.p95 > p95_budget:
                    severity = "WARNING"
                else:
                    continue

                alert_key = f"v11_latency:{symbol}:{severity}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_v11_latency_budget(symbol, summary.p95, summary.p99, p95_budget, severity)
                    fired.append(
                        {
                            "type": "V11_LATENCY_BUDGET",
                            "symbol": symbol,
                            "p95_ms": summary.p95,
                            "p99_ms": summary.p99,
                            "severity": severity,
                        }
                    )
                    logger.warning(
                        "V11 latency %s: %s p95=%.1fms p99=%.1fms",
                        severity,
                        symbol,
                        summary.p95,
                        summary.p99,
                    )
        except ImportError:
            pass
        return fired

    def _check_exec_latency_budget(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("EXEC_LATENCY_BUDGET", False):
            return fired

        try:
            from monitoring.execution_metrics import exec_all_stage_summaries  # noqa: PLC0415

            budgets = {
                "guard_check": self._thresholds.exec_guard_p95_budget_ms,
                "broker_call": self._thresholds.exec_broker_p95_budget_ms,
                "dispatch_total": self._thresholds.exec_dispatch_p95_budget_ms,
            }

            for stage, summary in exec_all_stage_summaries().items():
                if summary.count < self._thresholds.rate_alert_min_samples:
                    continue
                budget = budgets.get(stage)
                if budget is None:
                    continue
                if summary.p95 <= budget:
                    continue

                alert_key = f"exec_latency:{stage}"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_exec_latency_budget(stage, summary.p95, summary.p99, budget)
                    fired.append(
                        {
                            "type": "EXEC_LATENCY_BUDGET",
                            "stage": stage,
                            "p95_ms": summary.p95,
                            "p99_ms": summary.p99,
                            "budget_ms": budget,
                        }
                    )
                    logger.warning(
                        "Exec latency breach: %s p95=%.1fms budget=%.0fms",
                        stage,
                        summary.p95,
                        budget,
                    )
        except ImportError:
            pass
        return fired

    def _check_anomaly_rates(self) -> list[dict]:
        fired: list[dict] = []
        min_samples = self._thresholds.rate_alert_min_samples

        # V11 veto rate
        if ALERT_RULES.get("V11_VETO_RATE_HIGH", False):
            try:
                from monitoring.v11_metrics import v11_veto_rate, v11_veto_window_count  # noqa: PLC0415

                if v11_veto_window_count() >= min_samples:
                    rate = v11_veto_rate()
                    if rate >= self._thresholds.v11_veto_rate_critical:
                        severity = "CRITICAL"
                    elif rate >= self._thresholds.v11_veto_rate_warning:
                        severity = "WARNING"
                    else:
                        severity = None
                    if severity:
                        alert_key = f"v11_veto_rate:{severity}"
                        if self._cooldown.should_fire(alert_key):
                            self._notifier.on_anomaly_rate(
                                "v11_veto_rate",
                                rate,
                                self._thresholds.v11_veto_rate_warning,
                                severity,
                                v11_veto_window_count(),
                            )
                            fired.append(
                                {
                                    "type": "V11_VETO_RATE_HIGH",
                                    "rate": rate,
                                    "severity": severity,
                                }
                            )
                            logger.warning("V11 veto rate %s: %.1f%%", severity, rate * 100)
            except ImportError:
                pass

        # L12 reject rate
        if ALERT_RULES.get("L12_REJECT_RATE_HIGH", False):
            try:
                from monitoring.execution_metrics import l12_rate_window_count, l12_reject_rate  # noqa: PLC0415

                if l12_rate_window_count() >= min_samples:
                    rate = l12_reject_rate()
                    if rate >= self._thresholds.l12_reject_rate_critical:
                        severity = "CRITICAL"
                    elif rate >= self._thresholds.l12_reject_rate_warning:
                        severity = "WARNING"
                    else:
                        severity = None
                    if severity:
                        alert_key = f"l12_reject_rate:{severity}"
                        if self._cooldown.should_fire(alert_key):
                            self._notifier.on_anomaly_rate(
                                "l12_reject_rate",
                                rate,
                                self._thresholds.l12_reject_rate_warning,
                                severity,
                                l12_rate_window_count(),
                            )
                            fired.append(
                                {
                                    "type": "L12_REJECT_RATE_HIGH",
                                    "rate": rate,
                                    "severity": severity,
                                }
                            )
                            logger.warning("L12 reject rate %s: %.1f%%", severity, rate * 100)
            except ImportError:
                pass

        # L12 ambiguity rate
        if ALERT_RULES.get("L12_AMBIGUITY_RATE_HIGH", False):
            try:
                from monitoring.execution_metrics import l12_ambiguity_rate, l12_rate_window_count  # noqa: PLC0415

                if l12_rate_window_count() >= min_samples:
                    rate = l12_ambiguity_rate()
                    if rate >= self._thresholds.l12_ambiguity_rate_warning:
                        alert_key = "l12_ambiguity_rate"
                        if self._cooldown.should_fire(alert_key):
                            self._notifier.on_anomaly_rate(
                                "l12_ambiguity_rate",
                                rate,
                                self._thresholds.l12_ambiguity_rate_warning,
                                "WARNING",
                                l12_rate_window_count(),
                            )
                            fired.append(
                                {
                                    "type": "L12_AMBIGUITY_RATE_HIGH",
                                    "rate": rate,
                                    "severity": "WARNING",
                                }
                            )
                            logger.warning("L12 ambiguity rate WARNING: %.1f%%", rate * 100)
            except ImportError:
                pass

        return fired

    def _check_reconnect_storm(self) -> list[dict]:
        fired: list[dict] = []
        if not ALERT_RULES.get("RECONNECT_STORM", False):
            return fired

        try:
            from monitoring.execution_metrics import is_reconnect_storm  # noqa: PLC0415

            if is_reconnect_storm():
                alert_key = "reconnect_storm"
                if self._cooldown.should_fire(alert_key):
                    self._notifier.on_reconnect_storm()
                    fired.append({"type": "RECONNECT_STORM", "severity": "CRITICAL"})
                    logger.error("Reconnect storm detected — latency and freshness may be degraded")
        except ImportError:
            pass
        return fired
