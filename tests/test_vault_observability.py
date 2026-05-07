from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.vault_health import VaultHealthChecker
from pipeline.phases.vault import compute_vault_sync


class _FakeContextBus:
    def __init__(self, timestamps: dict[str, float | None]) -> None:
        self._timestamps = timestamps

    def get_last_tick_time(self, symbol: str) -> float | None:
        return self._timestamps.get(symbol)


class _FakeRedis:
    def __init__(self, heartbeat_payload: bytes, *, symbol: str = "EURUSD", last_seen_ts: float = 65.04) -> None:
        self._heartbeat_payload = heartbeat_payload
        self.client = self
        self._last_seen: dict[tuple[str, str], bytes] = {
            (f"wolf15:latest_tick:{symbol}", "last_seen_ts"): str(last_seen_ts).encode()
        }

    def ping(self) -> bool:
        return True

    def get(self, _key: str) -> bytes:
        return self._heartbeat_payload

    def hget(self, key: str, field: str) -> bytes | None:
        return self._last_seen.get((key, field))


@pytest.mark.parametrize("symbol", ["EURUSD"])
def test_vault_health_treats_live_window_as_nominal(monkeypatch: pytest.MonkeyPatch, symbol: str) -> None:
    now_ts = 100.0
    last_seen_ts = now_ts - 7.4
    context_bus = _FakeContextBus({symbol: last_seen_ts})
    redis_client = _FakeRedis(
        f'{{"ts": {last_seen_ts}, "producer": "finnhub"}}'.encode(),
        symbol=symbol,
        last_seen_ts=last_seen_ts,
    )
    checker = VaultHealthChecker(redis_client=redis_client, context_bus=context_bus)

    monotonic_values = iter([1.0, 1.001, 2.0, 2.001])
    monkeypatch.setattr("core.vault_health.time.time", lambda: now_ts)
    monkeypatch.setattr("core.vault_health.time.monotonic", lambda: next(monotonic_values))

    report = checker.check(symbols=[symbol])

    assert report.feed_freshness == 1.0
    assert report.freshness_state == "fresh"
    assert report.freshness_class == "LIVE"
    assert report.worst_symbol_age_seconds == pytest.approx(7.4, abs=0.01)
    assert report.symbols_fresh == 1
    assert report.symbols_total == 1
    assert report.details == "All vault systems nominal"
    assert report.is_healthy is True
    assert report.should_block_analysis is False


@pytest.mark.parametrize("symbol", ["EURUSD"])
def test_vault_health_keeps_degraded_refreshing_nonblocking(
    monkeypatch: pytest.MonkeyPatch, symbol: str
) -> None:
    now_ts = 200.0
    last_seen_ts = now_ts - 60.0
    context_bus = _FakeContextBus({symbol: last_seen_ts})
    redis_client = _FakeRedis(
        f'{{"ts": {last_seen_ts}, "producer": "finnhub"}}'.encode(),
        symbol=symbol,
        last_seen_ts=last_seen_ts,
    )
    checker = VaultHealthChecker(redis_client=redis_client, context_bus=context_bus)

    monotonic_values = iter([1.0, 1.001, 2.0, 2.001])
    monkeypatch.setattr("core.vault_health.time.time", lambda: now_ts)
    monkeypatch.setattr("core.vault_health.time.monotonic", lambda: next(monotonic_values))

    report = checker.check(symbols=[symbol])

    assert report.feed_freshness > 0.5
    assert report.freshness_state == "fresh"
    assert report.freshness_class == "DEGRADED_BUT_REFRESHING"
    assert report.details == "FEED DEGRADED_BUT_REFRESHING (freshness=0.94)"
    assert report.is_healthy is True
    assert report.should_block_analysis is False


@pytest.mark.parametrize("symbol", ["OANDA:EUR_USD", "EUR/USD", "EURUSDm"])
def test_vault_health_normalizes_symbol_aliases(monkeypatch: pytest.MonkeyPatch, symbol: str) -> None:
    now_ts = 100.0
    last_seen_ts = now_ts - 5.0
    context_bus = _FakeContextBus({"EURUSD": last_seen_ts})
    redis_client = _FakeRedis(
        f'{{"ts": {last_seen_ts}, "producer": "finnhub"}}'.encode(),
        symbol="EURUSD",
        last_seen_ts=last_seen_ts,
    )
    checker = VaultHealthChecker(redis_client=redis_client, context_bus=context_bus)

    monotonic_values = iter([1.0, 1.001, 2.0, 2.001])
    monkeypatch.setattr("core.vault_health.time.time", lambda: now_ts)
    monkeypatch.setattr("core.vault_health.time.monotonic", lambda: next(monotonic_values))

    report = checker.check(symbols=[symbol])

    assert report.feed_freshness == 1.0
    assert report.freshness_class == "LIVE"
    assert report.should_block_analysis is False


def test_vault_health_empty_symbol_uses_enabled_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    now_ts = 100.0
    last_seen_ts = now_ts - 4.0
    context_bus = _FakeContextBus({"EURUSD": last_seen_ts})
    redis_client = _FakeRedis(
        f'{{"ts": {last_seen_ts}, "producer": "finnhub"}}'.encode(),
        symbol="EURUSD",
        last_seen_ts=last_seen_ts,
    )
    checker = VaultHealthChecker(redis_client=redis_client, context_bus=context_bus)

    monotonic_values = iter([1.0, 1.001, 2.0, 2.001])
    monkeypatch.setattr("config_loader.get_enabled_symbols", lambda: ["EURUSD"])
    monkeypatch.setattr("core.vault_health.time.time", lambda: now_ts)
    monkeypatch.setattr("core.vault_health.time.monotonic", lambda: next(monotonic_values))

    report = checker.check(symbols=[])

    assert report.feed_freshness == 1.0
    assert report.symbols_total == 1
    assert report.freshness_class == "LIVE"
    assert report.should_block_analysis is False


@pytest.mark.parametrize("symbol", ["EURUSD"])
def test_vault_health_report_exposes_freshness_and_provider_breakdown(
    monkeypatch: pytest.MonkeyPatch, symbol: str
) -> None:
    now_ts = 1000.0
    last_seen_ts = now_ts - 334.96
    context_bus = _FakeContextBus({symbol: last_seen_ts})
    redis_client = _FakeRedis(
        f'{{"ts": {last_seen_ts}, "producer": "finnhub"}}'.encode(),
        symbol=symbol,
        last_seen_ts=last_seen_ts,
    )
    checker = VaultHealthChecker(redis_client=redis_client, context_bus=context_bus)

    monotonic_values = iter([1.0, 1.001, 2.0, 3.003])
    monkeypatch.setattr("core.vault_health.time.time", lambda: now_ts)
    monkeypatch.setattr("core.vault_health.time.monotonic", lambda: next(monotonic_values))

    report = checker.check(symbols=[symbol])

    assert report.feed_freshness == 0.0
    assert report.freshness_state == "stale_preserved"
    assert report.freshness_class == "STALE_PRESERVED"
    assert report.freshness_threshold_seconds == pytest.approx(300.0)
    assert report.feed_last_seen_ts == pytest.approx(last_seen_ts)
    assert report.worst_symbol_age_seconds == pytest.approx(334.96, abs=0.01)
    assert report.last_tick_age_seconds == pytest.approx(334.96, abs=0.01)
    assert report.symbols_fresh == 0
    assert report.symbols_total == 1
    assert report.provider_state == "STALE"
    assert report.provider_age_seconds == pytest.approx(334.96, abs=0.01)
    assert report.provider_last_ts is not None
    assert "age 334.96s > stale threshold 300.0s" in report.freshness_formula
    assert report.redis_latency_ms == pytest.approx(1003.0, abs=0.1)
    assert report.redis_roundtrip_ms == pytest.approx(1003.0, abs=0.1)
    assert report.context_hydration_ms >= 0.0
    assert report.bus_read_age_ms == pytest.approx(334960.0, abs=20.0)
    assert report.should_block_analysis is True


def test_compute_vault_sync_logs_structured_vault_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    vault_report = MagicMock()
    vault_report.feed_freshness = 0.0
    vault_report.redis_health = 0.0
    vault_report.should_block_analysis = True
    vault_report.is_healthy = False
    vault_report.details = "FEED STALE (freshness=0.00); REDIS DEGRADED (latency=1003ms)"
    vault_report.freshness_formula = "1.0 - (34.96 / 10.0) = -2.4960 -> clamped to 0.0000"
    vault_report.worst_symbol_age_seconds = 34.96
    vault_report.symbols_fresh = 0
    vault_report.symbols_total = 30
    vault_report.provider_state = "STALE"
    vault_report.provider_age_seconds = 34.96
    vault_report.provider_last_ts = "2026-04-22T19:21:07.739065+00:00"
    vault_report.redis_latency_ms = 1003.0
    vault_report.redis_roundtrip_ms = 1003.0
    vault_report.context_hydration_ms = 1.0
    vault_report.bus_read_age_ms = 34960.0

    vault_checker = MagicMock()
    vault_checker.check.return_value = vault_report

    warning = MagicMock()
    monkeypatch.setattr("pipeline.phases.vault.logger.warning", warning)

    compute_vault_sync({"pair": "EURUSD"}, vault_checker)

    warning.assert_called_once()
    log_line = warning.call_args.args[0]
    assert "[VaultSync] Vault health CRITICAL for EURUSD" in log_line
    assert "freshness_formula=1.0 - (34.96 / 10.0) = -2.4960 -> clamped to 0.0000" in log_line
    assert "worst_symbol_age_seconds=34.96" in log_line
    assert "symbols_fresh=0/30" in log_line
    assert "provider_state=STALE" in log_line
    assert "provider_age_seconds=34.96" in log_line
    assert "provider_last_ts=2026-04-22T19:21:07.739065+00:00" in log_line
    assert "redis_latency_ms=1003" in log_line
    assert "redis_roundtrip_ms=1003" in log_line
    assert "context_hydration_ms=" in log_line
    assert "bus_read_age_ms=" in log_line
    assert "should_block_analysis=True" in log_line
