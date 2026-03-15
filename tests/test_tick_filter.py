"""Tests for analysis/tick_filter.py — spike filter, dedup cache, price store."""

import threading

from analysis.tick_filter import (
    DedupCache,
    LastPriceStore,
    SpikeFilter,
    TickFilterConfig,
)


class TestLastPriceStore:
    def test_get_returns_none_for_unknown_symbol(self) -> None:
        store = LastPriceStore()
        assert store.get("EURUSD") is None

    def test_update_and_get(self) -> None:
        store = LastPriceStore()
        store.update("EURUSD", 1.1050, timestamp=1000.0)
        entry = store.get("EURUSD")
        assert entry is not None
        assert entry.price == 1.1050
        assert entry.timestamp == 1000.0

    def test_thread_safety(self) -> None:
        """Concurrent writes should not raise or corrupt."""
        store = LastPriceStore()
        errors: list[Exception] = []

        def writer(symbol: str, start: float) -> None:
            try:
                for i in range(1000):
                    store.update(symbol, start + i * 0.0001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("EURUSD", 1.1)),
            threading.Thread(target=writer, args=("EURUSD", 1.2)),
            threading.Thread(target=writer, args=("GBPUSD", 1.3)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert store.get("EURUSD") is not None
        assert store.get("GBPUSD") is not None


class TestSpikeFilter:
    def _make_filter(self, threshold_pct: float = 3.0, staleness: float = 300.0) -> SpikeFilter:
        config = TickFilterConfig(
            spike_threshold_pct=threshold_pct,
            staleness_seconds=staleness,
        )
        return SpikeFilter(config)

    def test_first_tick_always_accepted(self) -> None:
        sf = self._make_filter()
        result = sf.check("EURUSD", 1.1050, timestamp=1000.0)
        assert result.accepted is True
        assert result.is_spike is False
        assert result.reason == "first_tick"

    def test_normal_tick_within_threshold(self) -> None:
        sf = self._make_filter(threshold_pct=3.0)
        sf.check("EURUSD", 1.1000, timestamp=1000.0)
        result = sf.check("EURUSD", 1.1020, timestamp=1001.0)
        assert result.accepted is True
        assert result.is_spike is False

    def test_spike_rejected(self) -> None:
        sf = self._make_filter(threshold_pct=1.0)
        sf.check("EURUSD", 1.1000, timestamp=1000.0)
        # 5% move — should be rejected
        result = sf.check("EURUSD", 1.1550, timestamp=1001.0)
        assert result.accepted is False
        assert result.is_spike is True
        assert result.reason == "spike_rejected"
        assert result.pct_change is not None
        assert result.pct_change > 1.0

    def test_spike_does_not_update_last_price(self) -> None:
        sf = self._make_filter(threshold_pct=1.0)
        sf.check("EURUSD", 1.1000, timestamp=1000.0)
        sf.check("EURUSD", 1.2000, timestamp=1001.0)  # rejected spike
        entry = sf.price_store.get("EURUSD")
        assert entry is not None
        assert entry.price == 1.1000  # unchanged

    def test_stale_override_breaks_rejection_loop(self) -> None:
        sf = self._make_filter(threshold_pct=1.0, staleness=60.0)
        sf.check("EURUSD", 1.1000, timestamp=1000.0)

        # Spike at t=1001 — rejected
        result1 = sf.check("EURUSD", 1.2000, timestamp=1001.0)
        assert result1.accepted is False

        # Same price at t=1061 (staleness exceeded) — force accepted
        result2 = sf.check("EURUSD", 1.2000, timestamp=1061.0)
        assert result2.accepted is True
        assert result2.is_spike is True
        assert result2.stale_override is True
        assert result2.reason == "stale_override_accepted"

        # Now last_prices is updated; normal tick near 1.2000 should work
        result3 = sf.check("EURUSD", 1.2010, timestamp=1062.0)
        assert result3.accepted is True
        assert result3.is_spike is False

    def test_zero_price_rejected(self) -> None:
        sf = self._make_filter()
        result = sf.check("EURUSD", 0.0, timestamp=1000.0)
        assert result.accepted is False
        assert result.reason == "invalid_price_zero_or_negative"

    def test_negative_price_rejected(self) -> None:
        sf = self._make_filter()
        result = sf.check("EURUSD", -1.5, timestamp=1000.0)
        assert result.accepted is False


class TestDedupCache:
    def _make_cache(self, ttl: float = 60.0, max_size: int = 100) -> DedupCache:
        config = TickFilterConfig(
            dedup_ttl_seconds=ttl,
            dedup_max_size=max_size,
            dedup_evict_batch=20,
        )
        return DedupCache(config)

    def test_first_seen_not_duplicate(self) -> None:
        cache = self._make_cache()
        assert cache.is_duplicate("key1", now=1000.0) is False

    def test_second_seen_is_duplicate(self) -> None:
        cache = self._make_cache()
        cache.is_duplicate("key1", now=1000.0)
        assert cache.is_duplicate("key1", now=1001.0) is True

    def test_ttl_expiry(self) -> None:
        cache = self._make_cache(ttl=10.0)
        cache.is_duplicate("key1", now=1000.0)

        # Within TTL — duplicate
        assert cache.is_duplicate("key1", now=1005.0) is True

        # After TTL from last access (1005 + 10 + 1 = 1016) — no longer duplicate
        assert cache.is_duplicate("key1", now=1016.0) is False

    def test_hard_cap_eviction(self) -> None:
        cache = self._make_cache(ttl=3600.0, max_size=50)

        # Insert 60 entries
        for i in range(60):
            cache.is_duplicate(f"key_{i}", now=1000.0 + i)

        # Size should be at or below max_size
        assert cache.size() <= 50

    def test_eviction_removes_oldest(self) -> None:
        cache = self._make_cache(ttl=3600.0, max_size=30)

        # Insert 35 entries
        for i in range(35):
            cache.is_duplicate(f"key_{i}", now=1000.0 + i)

        # Oldest should have been evicted; newest should remain
        # key_0 through key_19 (oldest batch) should be evicted
        # key_34 (newest) should still be present
        assert cache.is_duplicate("key_34", now=1100.0) is True

    def test_thread_safety(self) -> None:
        cache = self._make_cache(ttl=60.0, max_size=5000)
        errors: list[Exception] = []

        def writer(prefix: str) -> None:
            try:
                for i in range(500):
                    cache.is_duplicate(f"{prefix}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"t{t}",)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cache.size() <= 5000
