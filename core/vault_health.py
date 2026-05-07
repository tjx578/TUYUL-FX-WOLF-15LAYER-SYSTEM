"""
Vault health checker -- replaces placeholder feed_freshness and redis_health.
Queries actual feed freshness and Redis connectivity.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from state.data_freshness import (
    FRESHNESS_LIVE_MAX_AGE_SEC,
    classify_feed_freshness,
    read_authoritative_last_seen_ts,
    stale_threshold_seconds,
)
from state.heartbeat_classifier import SERVICE_HEARTBEAT_CONFIG, classify_heartbeat

logger = logging.getLogger("tuyul.vault_health")

_SYMBOL_CLEAN_RE = re.compile(r"[^A-Z0-9]")


@dataclass
class VaultHealthReport:
    """Health report snapshot."""

    feed_freshness: float  # 0.0 = stale, 1.0 = fresh
    redis_health: float  # 0.0 = dead, 1.0 = healthy
    last_tick_age_seconds: float
    worst_symbol_age_seconds: float
    symbols_fresh: int
    symbols_total: int
    redis_latency_ms: float
    redis_roundtrip_ms: float
    context_hydration_ms: float
    bus_read_age_ms: float
    is_healthy: bool
    freshness_formula: str = ""
    freshness_formula_raw: float | None = None
    provider_state: str | None = None
    provider_age_seconds: float | None = None
    provider_last_ts: str | None = None
    process_state: str | None = None
    process_age_seconds: float | None = None
    process_last_ts: str | None = None
    freshness_state: str | None = None
    freshness_class: str | None = None
    freshness_threshold_seconds: float | None = None
    feed_last_seen_ts: float | None = None
    details: str = ""

    @property
    def should_block_analysis(self) -> bool:
        """If True, pipeline must NOT proceed."""
        return self.feed_freshness < 0.3 or self.redis_health < 0.5


class VaultHealthChecker:
    """Replaces hardcoded placeholder health values."""

    MAX_TICK_AGE_SECONDS = FRESHNESS_LIVE_MAX_AGE_SEC
    MAX_REDIS_LATENCY_MS = 100.0

    def __init__(self, redis_client=None, context_bus=None) -> None:
        self._redis = redis_client
        self._context_bus = context_bus

    def check(self, symbols: list[str] | None = None) -> VaultHealthReport:
        """Run health checks. Returns actual metrics."""
        resolved_symbols = self._resolve_symbols(symbols or [])
        process_state, process_age, process_last_ts = self._get_heartbeat_status("ingest_process")
        provider_state, provider_age, provider_last_ts = self._get_heartbeat_status("ingest_provider")
        (
            feed_freshness,
            worst_age,
            symbols_fresh,
            symbols_total,
            freshness_formula,
            formula_raw,
            context_hydration_ms,
            freshness_state,
            freshness_class,
            freshness_threshold,
            feed_last_seen_ts,
        ) = self._check_feed_freshness(resolved_symbols)
        redis_health, redis_latency = self._check_redis_health()
        tick_age = self._get_last_tick_age(resolved_symbols)
        bus_read_age_ms = float("inf") if tick_age == float("inf") else tick_age * 1000.0

        is_healthy = feed_freshness >= 0.5 and redis_health >= 0.5

        details_parts: list[str] = []
        if freshness_class == "STALE_PRESERVED":
            sync_hint = ""
            if provider_state == "ALIVE" or process_state == "ALIVE":
                sync_hint = f" while ingest_process={process_state or 'UNKNOWN'} provider={provider_state or 'UNKNOWN'}"
            details_parts.append(f"FEED STALE (freshness={feed_freshness:.2f}{sync_hint})")
        elif freshness_class == "DEGRADED_BUT_REFRESHING":
            details_parts.append(f"FEED DEGRADED_BUT_REFRESHING (freshness={feed_freshness:.2f})")
        elif freshness_class in ("NO_PRODUCER", "NO_TRANSPORT", "CONFIG_ERROR"):
            details_parts.append(f"FEED {freshness_class} (freshness={feed_freshness:.2f})")
        if redis_health < 0.5:
            details_parts.append(f"REDIS DEGRADED (latency={redis_latency:.0f}ms)")
        if not details_parts:
            details_parts.append("All vault systems nominal")

        report = VaultHealthReport(
            feed_freshness=round(feed_freshness, 3),
            redis_health=round(redis_health, 3),
            last_tick_age_seconds=round(tick_age, 2),
            worst_symbol_age_seconds=round(worst_age, 2),
            symbols_fresh=symbols_fresh,
            symbols_total=symbols_total,
            redis_latency_ms=round(redis_latency, 2),
            redis_roundtrip_ms=round(redis_latency, 2),
            context_hydration_ms=round(context_hydration_ms, 2),
            bus_read_age_ms=round(bus_read_age_ms, 2) if bus_read_age_ms != float("inf") else float("inf"),
            is_healthy=is_healthy,
            freshness_formula=freshness_formula,
            freshness_formula_raw=round(formula_raw, 4) if formula_raw is not None else None,
            provider_state=provider_state,
            provider_age_seconds=round(provider_age, 2) if provider_age is not None else None,
            provider_last_ts=provider_last_ts,
            process_state=process_state,
            process_age_seconds=round(process_age, 2) if process_age is not None else None,
            process_last_ts=process_last_ts,
            freshness_state=freshness_state,
            freshness_class=freshness_class,
            freshness_threshold_seconds=round(freshness_threshold, 2) if freshness_threshold is not None else None,
            feed_last_seen_ts=feed_last_seen_ts,
            details="; ".join(details_parts),
        )

        if not report.is_healthy:
            logger.warning("Vault health degraded: %s", report.details)

        return report

    def _resolve_symbols(self, symbols: list[str]) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()

        for symbol in symbols:
            normalized = self._normalize_symbol(symbol)
            if normalized and normalized not in seen:
                seen.add(normalized)
                resolved.append(normalized)

        if resolved:
            return resolved

        try:
            from config_loader import get_enabled_symbols  # noqa: PLC0415

            for symbol in get_enabled_symbols():
                normalized = self._normalize_symbol(symbol)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    resolved.append(normalized)
        except Exception as exc:
            logger.debug("Enabled symbol fallback failed: %s", exc)

        return resolved

    @staticmethod
    def _normalize_symbol(symbol: object) -> str:
        raw = str(symbol or "").strip().upper()
        if ":" in raw:
            raw = raw.rsplit(":", 1)[-1]
        cleaned = _SYMBOL_CLEAN_RE.sub("", raw)
        if len(cleaned) > 6 and cleaned[:6].isalpha():
            return cleaned[:6]
        return cleaned

    def _read_last_seen_ts(self, symbol: str) -> float | None:
        samples: list[float] = []

        redis_ts = read_authoritative_last_seen_ts(symbol, self._redis)
        if redis_ts is not None and redis_ts > 0:
            samples.append(redis_ts)

        if self._context_bus is not None:
            for method_name in ("get_last_tick_time", "get_feed_timestamp"):
                method = getattr(self._context_bus, method_name, None)
                if method is None:
                    continue
                try:
                    bus_ts = method(symbol)
                except Exception:
                    continue
                try:
                    bus_ts_float = float(bus_ts)
                except (TypeError, ValueError):
                    continue
                if bus_ts_float > 0:
                    samples.append(bus_ts_float)

        return max(samples) if samples else None

    def _check_feed_freshness(
        self, symbols: list[str]
    ) -> tuple[float, float, int, int, str, float | None, float, str | None, str | None, float | None, float | None]:
        started = time.monotonic()
        live_window = self.MAX_TICK_AGE_SECONDS
        stale_threshold = stale_threshold_seconds()

        def _elapsed_ms() -> float:
            return (time.monotonic() - started) * 1000

        def _empty_result(
            freshness: float,
            worst_age: float,
            fresh_count: int,
            total: int,
            formula: str,
            formula_raw: float | None,
            state: str | None,
            freshness_class: str | None,
            last_seen_ts: float | None = None,
        ) -> tuple[float, float, int, int, str, float | None, float, str | None, str | None, float | None, float | None]:
            return (
                freshness,
                worst_age,
                fresh_count,
                total,
                formula,
                formula_raw,
                _elapsed_ms(),
                state,
                freshness_class,
                stale_threshold,
                last_seen_ts,
            )

        if not symbols:
            return _empty_result(
                0.0,
                float("inf"),
                0,
                len(symbols),
                "no symbols provided -> freshness=0.0000",
                None,
                "no_producer",
                "NO_PRODUCER",
            )
        try:
            ages: list[float] = []
            fresh_count = 0
            now_ts = time.time()
            worst_last_seen_ts: float | None = None
            for symbol in symbols:
                last_ts = self._read_last_seen_ts(symbol)
                if last_ts is None or last_ts == 0:
                    ages.append(float("inf"))
                else:
                    worst_last_seen_ts = last_ts if worst_last_seen_ts is None else min(worst_last_seen_ts, last_ts)
                    age = max(0.0, now_ts - last_ts)
                    ages.append(age)
                    if age <= live_window:
                        fresh_count += 1
            if not ages:
                return _empty_result(
                    0.0,
                    float("inf"),
                    0,
                    0,
                    "no feed age samples -> freshness=0.0000",
                    None,
                    "no_producer",
                    "NO_PRODUCER",
                )

            finite_ages = [age for age in ages if age != float("inf")]
            if finite_ages and len(finite_ages) < len(ages):
                missing_count = len(ages) - len(finite_ages)
                best_age = min(finite_ages)
                known_ratio = len(finite_ages) / len(ages)
                if best_age <= stale_threshold:
                    snapshot = classify_feed_freshness(
                        transport_ok=self._redis is not None,
                        has_producer_signal=True,
                        staleness_seconds=max(live_window + 1.0, best_age),
                        threshold_seconds=stale_threshold,
                        now_ts=now_ts,
                    )
                    raw_freshness = max(0.5, min(1.0, known_ratio))
                    formula = (
                        f"{len(finite_ages)}/{len(ages)} symbols have feed timestamps, "
                        f"{missing_count} missing; freshest age {best_age:.2f}s <= stale threshold "
                        f"{stale_threshold:.1f}s -> freshness={raw_freshness:.4f}"
                    )
                    return _empty_result(
                        raw_freshness,
                        max(finite_ages),
                        fresh_count,
                        len(symbols),
                        formula,
                        raw_freshness,
                        snapshot.state,
                        snapshot.freshness_class.value,
                        worst_last_seen_ts,
                    )

            worst_age = max(ages)
            if worst_age == float("inf"):
                snapshot = classify_feed_freshness(
                    transport_ok=self._redis is not None,
                    has_producer_signal=False,
                    threshold_seconds=stale_threshold,
                )
                return _empty_result(
                    0.0,
                    float("inf"),
                    fresh_count,
                    len(symbols),
                    "missing last_seen_ts -> freshness=0.0000",
                    None,
                    snapshot.state,
                    snapshot.freshness_class.value,
                )

            snapshot = classify_feed_freshness(
                transport_ok=self._redis is not None,
                has_producer_signal=True,
                staleness_seconds=worst_age,
                threshold_seconds=stale_threshold,
                last_seen_ts=worst_last_seen_ts,
                now_ts=now_ts,
            )
            if snapshot.state == "stale_preserved":
                if len(ages) > 1:
                    fresh_enough_count = sum(1 for age in ages if age <= stale_threshold)
                    if fresh_enough_count > 0:
                        fleet_ratio = fresh_enough_count / len(ages)
                        raw_freshness = max(0.5, min(1.0, fleet_ratio))
                        formula = (
                            f"{fresh_enough_count}/{len(ages)} symbols <= stale threshold "
                            f"{stale_threshold:.1f}s; worst age {worst_age:.2f}s "
                            f"-> fleet freshness={raw_freshness:.4f}"
                        )
                        degraded_snapshot = classify_feed_freshness(
                            transport_ok=self._redis is not None,
                            has_producer_signal=True,
                            staleness_seconds=max(live_window + 1.0, min(ages)),
                            threshold_seconds=stale_threshold,
                            now_ts=now_ts,
                        )
                        return _empty_result(
                            raw_freshness,
                            worst_age,
                            fresh_count,
                            len(symbols),
                            formula,
                            raw_freshness,
                            degraded_snapshot.state,
                            degraded_snapshot.freshness_class.value,
                            worst_last_seen_ts,
                        )
                formula = (
                    f"age {worst_age:.2f}s > stale threshold {stale_threshold:.1f}s "
                    "-> freshness=0.0000"
                )
                return _empty_result(
                    0.0,
                    worst_age,
                    fresh_count,
                    len(symbols),
                    formula,
                    None,
                    snapshot.state,
                    snapshot.freshness_class.value,
                    worst_last_seen_ts,
                )

            if worst_age <= live_window:
                formula = f"age {worst_age:.2f}s <= live window {live_window:.1f}s -> freshness=1.0000"
                return _empty_result(
                    1.0,
                    worst_age,
                    fresh_count,
                    len(symbols),
                    formula,
                    1.0,
                    snapshot.state,
                    snapshot.freshness_class.value,
                    worst_last_seen_ts,
                )

            decay_span = max(1.0, stale_threshold - live_window)
            decay = min(1.0, max(0.0, (worst_age - live_window) / decay_span))
            raw_freshness = 1.0 - (0.5 * decay)
            clamped = max(0.5, min(1.0, raw_freshness))
            formula = (
                f"1.0 - 0.5 * (({worst_age:.2f} - {live_window:.1f}) / "
                f"{decay_span:.1f}) = {raw_freshness:.4f} -> clamped to {clamped:.4f}"
            )
            return _empty_result(
                clamped,
                worst_age,
                fresh_count,
                len(symbols),
                formula,
                raw_freshness,
                snapshot.state,
                snapshot.freshness_class.value,
                worst_last_seen_ts,
            )
        except Exception as e:
            logger.error("Feed freshness check failed: %s", e)
            return _empty_result(
                0.0,
                float("inf"),
                0,
                len(symbols),
                "feed freshness error -> freshness=0.0000",
                None,
                "config_error",
                "CONFIG_ERROR",
            )

    def _check_redis_health(self) -> tuple[float, float]:
        if self._redis is None:
            return 0.0, float("inf")
        try:
            start = time.monotonic()
            pong = self._redis.ping()
            latency_ms = (time.monotonic() - start) * 1000
            if not pong:
                return 0.0, latency_ms
            health = max(0.0, 1.0 - (latency_ms / self.MAX_REDIS_LATENCY_MS))
            return health, latency_ms
        except Exception as e:
            logger.error("Redis health check failed: %s", e)
            return 0.0, float("inf")

    def _get_last_tick_age(self, symbols: list[str]) -> float:
        if not symbols:
            return float("inf")
        try:
            worst = 0.0
            for symbol in symbols:
                ts = self._read_last_seen_ts(symbol)
                if ts is None or ts == 0:
                    return float("inf")
                age = time.time() - ts
                worst = max(worst, age)
            return worst
        except Exception:
            return float("inf")

    def _get_heartbeat_status(self, heartbeat_name: str) -> tuple[str | None, float | None, str | None]:
        if self._redis is None:
            return None, None, None
        try:
            redis_reader = getattr(self._redis, "client", self._redis)
            heartbeat_key, max_age = SERVICE_HEARTBEAT_CONFIG[heartbeat_name]
            status = classify_heartbeat(redis_reader.get(heartbeat_key), max_age, service=heartbeat_name)
            last_ts_iso = self._iso_ts(status.last_ts)
            return status.state.value, status.age_seconds, last_ts_iso
        except Exception as exc:
            logger.debug("%s heartbeat read failed: %s", heartbeat_name, exc)
            return None, None, None

    @staticmethod
    def _iso_ts(value: float | None) -> str | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OverflowError, OSError, TypeError, ValueError):
            return None
