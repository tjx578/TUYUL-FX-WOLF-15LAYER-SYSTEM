"""
Vault health checker -- replaces placeholder feed_freshness and redis_health.
Queries actual feed freshness and Redis connectivity.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from state.data_freshness import read_authoritative_last_seen_ts
from state.heartbeat_classifier import SERVICE_HEARTBEAT_CONFIG, classify_heartbeat

logger = logging.getLogger("tuyul.vault_health")


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
    details: str = ""

    @property
    def should_block_analysis(self) -> bool:
        """If True, pipeline must NOT proceed."""
        return self.feed_freshness < 0.3 or self.redis_health < 0.5


class VaultHealthChecker:
    """Replaces hardcoded placeholder health values."""

    MAX_TICK_AGE_SECONDS = 10.0
    MAX_REDIS_LATENCY_MS = 100.0

    def __init__(self, redis_client=None, context_bus=None) -> None:
        self._redis = redis_client
        self._context_bus = context_bus

    def check(self, symbols: list[str] | None = None) -> VaultHealthReport:
        """Run health checks. Returns actual metrics."""
        (
            feed_freshness,
            worst_age,
            symbols_fresh,
            symbols_total,
            freshness_formula,
            formula_raw,
            context_hydration_ms,
        ) = self._check_feed_freshness(symbols or [])
        redis_health, redis_latency = self._check_redis_health()
        tick_age = self._get_last_tick_age(symbols or [])
        provider_state, provider_age, provider_last_ts = self._get_provider_status()
        bus_read_age_ms = float("inf") if tick_age == float("inf") else tick_age * 1000.0

        is_healthy = feed_freshness >= 0.5 and redis_health >= 0.5

        details_parts: list[str] = []
        if feed_freshness < 0.5:
            details_parts.append(f"FEED STALE (freshness={feed_freshness:.2f})")
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
            details="; ".join(details_parts),
        )

        if not report.is_healthy:
            logger.warning("Vault health degraded: %s", report.details)

        return report

    def _check_feed_freshness(self, symbols: list[str]) -> tuple[float, float, int, int, str, float | None, float]:
        started = time.monotonic()
        if not symbols:
            elapsed_ms = (time.monotonic() - started) * 1000
            return 0.0, float("inf"), 0, len(symbols), "1.0 - (inf / 10.0) = -inf -> clamped to 0.0", None, elapsed_ms
        try:
            ages: list[float] = []
            fresh_count = 0
            for symbol in symbols:
                last_ts = read_authoritative_last_seen_ts(symbol, self._redis)
                if last_ts is None or last_ts == 0:
                    ages.append(float("inf"))
                else:
                    age = time.time() - last_ts
                    ages.append(age)
                    if age <= self.MAX_TICK_AGE_SECONDS:
                        fresh_count += 1
            if not ages:
                elapsed_ms = (time.monotonic() - started) * 1000
                return 0.0, float("inf"), 0, 0, "1.0 - (inf / 10.0) = -inf -> clamped to 0.0", None, elapsed_ms
            worst_age = max(ages)
            if worst_age == float("inf"):
                elapsed_ms = (time.monotonic() - started) * 1000
                return (
                    0.0,
                    float("inf"),
                    fresh_count,
                    len(symbols),
                    "1.0 - (inf / 10.0) = -inf -> clamped to 0.0",
                    None,
                    elapsed_ms,
                )
            raw_freshness = 1.0 - (worst_age / self.MAX_TICK_AGE_SECONDS)
            clamped = max(0.0, raw_freshness)
            formula = (
                f"1.0 - ({worst_age:.2f} / {self.MAX_TICK_AGE_SECONDS:.1f}) = {raw_freshness:.4f} "
                f"-> clamped to {clamped:.4f}"
            )
            elapsed_ms = (time.monotonic() - started) * 1000
            return clamped, worst_age, fresh_count, len(symbols), formula, raw_freshness, elapsed_ms
        except Exception as e:
            logger.error("Feed freshness check failed: %s", e)
            elapsed_ms = (time.monotonic() - started) * 1000
            return 0.0, float("inf"), 0, len(symbols), "1.0 - (error / 10.0) = n/a -> clamped to 0.0", None, elapsed_ms

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
                ts = read_authoritative_last_seen_ts(symbol, self._redis)
                if ts is None or ts == 0:
                    return float("inf")
                age = time.time() - ts
                worst = max(worst, age)
            return worst
        except Exception:
            return float("inf")

    def _get_provider_status(self) -> tuple[str | None, float | None, str | None]:
        if self._redis is None:
            return None, None, None
        try:
            redis_reader = getattr(self._redis, "client", self._redis)
            provider_key, max_age = SERVICE_HEARTBEAT_CONFIG["ingest_provider"]
            status = classify_heartbeat(redis_reader.get(provider_key), max_age, service="ingest_provider")
            last_ts_iso = self._iso_ts(status.last_ts)
            return status.state.value, status.age_seconds, last_ts_iso
        except Exception as exc:
            logger.debug("Provider heartbeat read failed: %s", exc)
            return None, None, None

    @staticmethod
    def _iso_ts(value: float | None) -> str | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OverflowError, OSError, TypeError, ValueError):
            return None
