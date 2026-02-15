"""
Vault health checker — replaces placeholder values in pipeline.
Queries actual feed freshness and Redis connectivity.
"""

from __future__ import annotations

import logging
import time

from dataclasses import dataclass

logger = logging.getLogger("tuyul.vault_health")


@dataclass
class VaultHealthReport:
    feed_freshness: float         # 0.0 = completely stale, 1.0 = perfectly fresh
    redis_health: float           # 0.0 = dead, 1.0 = healthy
    last_tick_age_seconds: float  # Age of most recent tick
    redis_latency_ms: float      # Redis PING round-trip
    is_healthy: bool              # Overall go/no-go
    details: str = ""

    @property
    def should_block_analysis(self) -> bool:
        """If True, pipeline must NOT proceed with analysis."""
        return self.feed_freshness < 0.3 or self.redis_health < 0.5


class VaultHealthChecker:
    """
    Replaces hardcoded placeholder health values.
    Must be called at pipeline start before any analysis runs.
    """

    # Max acceptable tick age before declaring feed stale
    MAX_TICK_AGE_SECONDS = 10.0
    # Max acceptable Redis latency
    MAX_REDIS_LATENCY_MS = 100.0

    def __init__(self, redis_client=None, context_bus=None):
        """
        Args:
            redis_client: Redis connection (from context bus or standalone)
            context_bus: LiveContextBus instance for feed freshness queries
        """
        self._redis = redis_client
        self._context_bus = context_bus

    def check(self, symbols: list[str] | None = None) -> VaultHealthReport:
        """
        Run health checks against real infrastructure.
        Returns actual metrics instead of placeholder 1.0 values.
        """
        feed_freshness = self._check_feed_freshness(symbols or [])
        redis_health, redis_latency = self._check_redis_health()
        tick_age = self._get_last_tick_age(symbols or [])

        is_healthy = feed_freshness >= 0.5 and redis_health >= 0.5

        details_parts = []
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
            redis_latency_ms=round(redis_latency, 2),
            is_healthy=is_healthy,
            details="; ".join(details_parts),
        )

        if not report.is_healthy:
            logger.warning(f"Vault health degraded: {report.details}")
        else:
            logger.debug(f"Vault health OK: feed={feed_freshness:.2f}, redis={redis_health:.2f}")

        return report

    def _check_feed_freshness(self, symbols: list[str]) -> float:
        """
        Query LiveContextBus for last tick timestamp per symbol.
        Returns 0.0–1.0 score.
        """
        if self._context_bus is None:
            logger.warning("No context bus configured — feed freshness unknown")
            return 0.0

        if not symbols:
            return 0.0

        try:
            ages = []
            for symbol in symbols:
                last_ts = self._context_bus.get_last_tick_time(symbol)
                if last_ts is None or last_ts == 0:
                    ages.append(float("inf"))
                else:
                    ages.append(time.time() - last_ts)

            if not ages:
                return 0.0

            # Worst age across all symbols
            worst_age = max(ages)
            if worst_age == float("inf"):
                return 0.0

            # Score: 1.0 if age < 1s, linearly degrades, 0.0 if age > MAX
            freshness = max(0.0, 1.0 - (worst_age / self.MAX_TICK_AGE_SECONDS))
            return freshness

        except Exception as e:
            logger.error(f"Feed freshness check failed: {e}")
            return 0.0

    def _check_redis_health(self) -> tuple[float, float]:
        """
        PING Redis, measure latency.
        Returns (health_score 0-1, latency_ms).
        """
        if self._redis is None:
            logger.warning("No Redis client configured — health unknown")
            return 0.0, float("inf")

        try:
            start = time.monotonic()
            pong = self._redis.ping()
            latency_ms = (time.monotonic() - start) * 1000

            if not pong:
                return 0.0, latency_ms

            # Score: 1.0 if latency < 10ms, degrades linearly, 0.0 if > MAX
            health = max(0.0, 1.0 - (latency_ms / self.MAX_REDIS_LATENCY_MS))
            return health, latency_ms

        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return 0.0, float("inf")

    def _get_last_tick_age(self, symbols: list[str]) -> float:
        """Get oldest tick age across symbols."""
        if self._context_bus is None or not symbols:
            return float("inf")

        try:
            worst = 0.0
            for symbol in symbols:
                ts = self._context_bus.get_last_tick_time(symbol)
                if ts is None or ts == 0:
                    return float("inf")
                age = time.time() - ts
                worst = max(worst, age)
            return worst
        except Exception:
            return float("inf")
