"""
Tick/price filtering utilities — **single source of truth**.

Used by both analysis pipeline and ingest runtime.
Handles spike detection, deduplication, and price reference tracking.

Zone: analysis/ — no execution side-effects.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field


def _default_per_symbol_spike_pct() -> dict[str, float]:
    return {}


@dataclass
class TickFilterConfig:
    """Configuration for tick filtering thresholds."""
    spike_threshold_pct: float = 3.0       # Default max % move before flagging as spike
    staleness_seconds: float = 300.0       # After this many seconds, force-accept new price
    dedup_ttl_seconds: float = 60.0        # TTL for dedup cache entries
    dedup_max_size: int = 5000             # Hard cap on dedup cache size
    dedup_evict_batch: int = 500           # Number of oldest entries to evict when cap hit
    # Per-symbol spike thresholds override spike_threshold_pct when set.
    # e.g. {"XAUUSD": 2.0, "GBPJPY": 1.0}
    per_symbol_spike_pct: dict[str, float] = field(default_factory=_default_per_symbol_spike_pct)


@dataclass
class PriceEntry:
    """Thread-safe price reference with timestamp."""
    price: float
    timestamp: float


class LastPriceStore:
    """
    Thread-safe store for last accepted prices per symbol.

    Even in async single-thread, this protects against:
    - Future run_in_executor usage
    - Mixed threading in test harnesses
    - Accidental concurrent access
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._prices: dict[str, PriceEntry] = {}

    def get(self, symbol: str) -> PriceEntry | None:
        with self._lock:
            return self._prices.get(symbol)

    def update(self, symbol: str, price: float, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            self._prices[symbol] = PriceEntry(price=price, timestamp=ts)

    def clear(self) -> None:
        with self._lock:
            self._prices.clear()


class DedupCache:
    """
    Bounded dedup cache with TTL-based eviction.

    Uses OrderedDict for O(1) insertion-order eviction.
    Evicts expired entries on every check, plus batch eviction at hard cap.
    """

    def __init__(self, config: TickFilterConfig | None = None) -> None:
        super().__init__()
        self._config = config or TickFilterConfig()
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, float] = OrderedDict()

    def _evict_expired(self, now: float) -> None:
        """Remove entries older than TTL. Must be called under lock."""
        cutoff = now - self._config.dedup_ttl_seconds
        # Evict from oldest (front of OrderedDict)
        while self._cache:
            _, ts = next(iter(self._cache.items()))
            if ts < cutoff:
                self._cache.popitem(last=False)
            else:
                break

    def _evict_overflow(self) -> None:
        """Hard cap enforcement. Must be called under lock."""
        if len(self._cache) > self._config.dedup_max_size:
            for _ in range(min(self._config.dedup_evict_batch, len(self._cache))):
                if self._cache:
                    self._cache.popitem(last=False)

    def is_duplicate(self, key: str, now: float | None = None) -> bool:
        """
        Check if key is a duplicate (seen within TTL window).
        If not duplicate, registers it.

        Returns True if duplicate, False if new.
        """
        ts = now if now is not None else time.time()
        with self._lock:
            # Always evict expired entries first
            self._evict_expired(ts)

            if key in self._cache:
                # Refresh timestamp (move to end)
                self._cache.move_to_end(key)
                self._cache[key] = ts
                return True

            # New entry
            self._cache[key] = ts
            self._evict_overflow()
            return False

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


@dataclass
class SpikeCheckResult:
    """Result of spike filter check."""
    is_spike: bool
    accepted: bool
    reason: str
    pct_change: float | None = None
    stale_override: bool = False


class SpikeFilter:
    """
    Spike filter with staleness decay.

    Design decisions:
    - Normal case: reject ticks that move > threshold_pct from last accepted price.
    - Staleness override: if last accepted price is older than staleness_seconds,
      force-accept the new tick. This prevents legitimate large moves (flash crashes,
      gap opens) from being permanently rejected.
    - On reject: _last_prices is NOT updated (by design — preserves reference).
    - On stale override: _last_prices IS updated (breaks the rejection loop).
    """

    def __init__(self, config: TickFilterConfig | None = None) -> None:
        super().__init__()
        self._config = config or TickFilterConfig()
        self._store = LastPriceStore()

    @property
    def price_store(self) -> LastPriceStore:
        return self._store

    def check(self, symbol: str, price: float, timestamp: float | None = None) -> SpikeCheckResult:
        """
        Check if a price tick is a spike.

        Returns SpikeCheckResult with acceptance decision and reasoning.
        """
        now = timestamp if timestamp is not None else time.time()

        if price <= 0:
            return SpikeCheckResult(
                is_spike=False,
                accepted=False,
                reason="invalid_price_zero_or_negative"
            )

        last = self._store.get(symbol)

        # First tick for symbol — always accept
        if last is None:
            self._store.update(symbol, price, now)
            return SpikeCheckResult(
                is_spike=False,
                accepted=True,
                reason="first_tick"
            )

        # Calculate percentage change
        pct_change = abs(price - last.price) / last.price * 100.0
        age_seconds = now - last.timestamp

        # Resolve per-symbol threshold (falls back to global default)
        threshold = self._config.per_symbol_spike_pct.get(
            symbol, self._config.spike_threshold_pct
        )

        # Within threshold — normal accept
        if pct_change <= threshold:
            self._store.update(symbol, price, now)
            return SpikeCheckResult(
                is_spike=False,
                accepted=True,
                reason="within_threshold",
                pct_change=pct_change
            )

        # Exceeds threshold — check staleness
        if age_seconds >= self._config.staleness_seconds:
            # Stale reference: force-accept to break rejection loop
            self._store.update(symbol, price, now)
            return SpikeCheckResult(
                is_spike=True,
                accepted=True,
                reason="stale_override_accepted",
                pct_change=pct_change,
                stale_override=True
            )

        # Spike detected, reference still fresh — reject
        # Intentionally do NOT update _last_prices here
        return SpikeCheckResult(
            is_spike=True,
            accepted=False,
            reason="spike_rejected",
            pct_change=pct_change
        )

    def clear(self) -> None:
        self._store.clear()


# --- Module-level convenience (backward compatible) ---
# These provide the old module-global interface but backed by proper classes.

_default_config = TickFilterConfig()
_spike_filter = SpikeFilter(_default_config)
_dedup_cache = DedupCache(_default_config)


def check_spike(symbol: str, price: float, timestamp: float | None = None) -> SpikeCheckResult:
    """Module-level spike check using default filter instance."""
    return _spike_filter.check(symbol, price, timestamp)


def is_duplicate_tick(key: str, now: float | None = None) -> bool:
    """Module-level dedup check using default cache instance."""
    return _dedup_cache.is_duplicate(key, now)


def reset_filters() -> None:
    """Reset all module-level filter state. Useful for testing."""
    _spike_filter.clear()
    _dedup_cache.clear()
