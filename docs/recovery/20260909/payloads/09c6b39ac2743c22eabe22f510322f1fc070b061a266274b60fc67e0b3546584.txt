"""Pressure prices retain the timestamp of the exact tick snapshot carrying them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import pipeline.wolf_constitutional_pipeline as pipeline_module
from analysis.frozen_quote_detector import FrozenQuoteDetector
from analysis.signal_decision_source_guard import convert_to_signal_pressure_state
from context.live_context_bus import LiveContextBus
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(at.timestamp(), tz=tz)

    monkeypatch.setattr(pipeline_module, "datetime", FixedDateTime)
    monkeypatch.setattr("context.live_context_bus.time.time", lambda: at.timestamp())
    monkeypatch.setattr("state.data_freshness.FRESHNESS_LIVE_MAX_AGE_SEC", 30.0)
    monkeypatch.setenv("SIGNAL_PRICE_MAX_FUTURE_SKEW_SECONDS", "1")
    return at


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> WolfConstitutionalPipeline:
    bus = LiveContextBus()
    bus.reset_state()
    instance = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    instance._context_bus = bus
    instance._frozen_quote_detector = FrozenQuoteDetector()
    # Only unrelated context providers are replaced. Tick storage, context
    # construction, source matching, freshness and quote assessment remain real.
    for name in ("_derive_price_structure", "_derive_counter_entry_structure", "_resolve_htf_structure_context"):
        monkeypatch.setattr(instance, name, lambda *args, **kwargs: {})
    monkeypatch.setattr(instance, "_basket_direction_validation_snapshot", lambda **kwargs: {})
    monkeypatch.setattr(
        instance,
        "_spread_quality",
        lambda *args: {
            "spread_normal": None,
            "spread_pips": None,
            "max_allowed_spread_pips": None,
        },
    )
    for name in (
        "_derive_timeframe_phase",
        "_derive_daily_phase_feed",
        "_derive_market_bias",
        "_market_theme_alignment_snapshot",
        "_is_market_theme_aligned",
    ):
        monkeypatch.setattr(instance, name, lambda *args, **kwargs: None)
    return instance


def build_context(pipeline: WolfConstitutionalPipeline):
    return pipeline._build_market_context(symbol="EURCHF", synthesis={}, l12_verdict={})


def lineage(pipeline: WolfConstitutionalPipeline, context) -> dict[str, Any]:
    value = pipeline._pressure_reference_price_lineage(
        symbol="EURCHF",
        context=context,
        synthesis={},
        l12_verdict={},
        allow_payload_fallback=False,
    )
    assert value is not None
    return value


def tick(at: datetime, *, bid: float = 0.94) -> dict[str, Any]:
    return {"symbol": "EURCHF", "bid": bid, "ask": bid + 0.0002, "last_seen_ts": at.timestamp()}


def test_candle_activity_cannot_refresh_old_tick(pipeline, clock):
    bus = pipeline._context_bus
    old = clock - timedelta(seconds=120)
    bus.update_tick(tick(old))
    bus.record_feed_update("EURCHF", clock.timestamp())
    context = build_context(pipeline)
    payload = lineage(pipeline, context)

    assert context.tick_snapshot_timestamp_epoch == old.timestamp()
    assert payload["price_snapshot_time_utc"] == old.isoformat()
    assert payload["price_age_seconds"] == 120.0
    assert payload["price_freshness_status"] == "LIVE"
    assert payload["price_snapshot_status"] == "STALE"
    assert payload["reference_price_is_live"] is False
    assessed = pipeline._decision_price_lineage_payload(payload, symbol="EURCHF")
    assert assessed["quote_health_reason"] == "QUOTE_SNAPSHOT_TIMESTAMP_STALE"
    assert assessed["quote_health_execution_blocked"] is True
    assert assessed["price_freshness_status"] == "LIVE"
    pressure = convert_to_signal_pressure_state({"source_stage": "PRESSURE_BLOCK", "symbol": "EURCHF", **assessed})
    assert pressure["observed_price_status"] != "LIVE"


def test_context_keeps_its_price_timestamp_after_new_tick_arrives(pipeline, clock):
    bus = pipeline._context_bus
    old = clock - timedelta(seconds=4)
    bus.update_tick(tick(old))
    context = build_context(pipeline)
    bus.update_tick(tick(clock, bid=0.95))

    original = lineage(pipeline, context)
    latest = lineage(pipeline, build_context(pipeline))
    assert original["price"] == pytest.approx(0.9401)
    assert original["price_snapshot_time_utc"] == old.isoformat()
    assert original["price_age_seconds"] == 4.0
    assert latest["price"] == pytest.approx(0.9501)
    assert latest["price_snapshot_time_utc"] == clock.isoformat()


def test_tick_snapshot_is_owned_on_write_and_copied_on_read(pipeline, clock):
    bus = pipeline._context_bus
    incoming = tick(clock)
    bus.update_tick(incoming)
    incoming.update(bid=9.0, last_seen_ts=0.0)
    read = bus.get_latest_tick("EURCHF")
    assert read["bid"] == 0.94
    assert read["last_seen_ts"] == clock.timestamp()
    read.update(bid=8.0, last_seen_ts=1.0)
    assert bus.get_latest_tick("EURCHF")["bid"] == 0.94
    assert bus.get_latest_tick("EURCHF")["last_seen_ts"] == clock.timestamp()


@pytest.mark.parametrize("timestamp", [None, "invalid", float("nan"), float("inf"), 0.0, -1.0])
def test_missing_or_invalid_tick_timestamp_is_not_replaced_by_receipt_time(pipeline, clock, timestamp):
    raw = {"symbol": "EURCHF", "bid": 0.94, "ask": 0.9402}
    if timestamp is not None:
        raw["last_seen_ts"] = timestamp
    pipeline._context_bus.update_tick(raw)
    pipeline._context_bus.record_feed_update("EURCHF", clock.timestamp())
    payload = lineage(pipeline, build_context(pipeline))
    assert payload["price_snapshot_time_utc"] is None
    assert payload["price_age_seconds"] is None
    assert payload["price_snapshot_status"] == "MISSING"
    assessed = pipeline._decision_price_lineage_payload(payload, symbol="EURCHF")
    assert assessed["reference_price_is_live"] is False
    assert assessed["quote_health_execution_blocked"] is True
    assert assessed["quote_health_reason"] == "QUOTE_SNAPSHOT_TIMESTAMP_MISSING"
    assert assessed["quote_health_observed_at_utc"] is None
    assert assessed["quote_observation_count"] == 0


@pytest.mark.parametrize("age,status", [(30.0, "LIVE"), (30.001, "STALE"), (-1.0, "LIVE"), (-1.001, "FUTURE")])
def test_tick_freshness_uses_existing_age_and_future_boundaries(pipeline, clock, age, status):
    pipeline._context_bus.record_feed_update("EURCHF", clock.timestamp())
    payload = pipeline._price_freshness_payload(
        symbol="EURCHF",
        source="LIVE_TICK_MID",
        source_timestamp=(clock - timedelta(seconds=age)).timestamp(),
    )
    assert payload["price_snapshot_status"] == status
    assert payload["reference_price_is_live"] is (status == "LIVE")


def test_future_quote_does_not_poison_next_valid_warmup(pipeline, clock):
    future = pipeline._price_freshness_payload(
        symbol="EURCHF",
        source="LIVE_TICK_MID",
        source_timestamp=(clock + timedelta(seconds=2)).timestamp(),
    )
    invalid = pipeline._decision_price_lineage_payload(
        {"price": 0.9401, "price_source": "LIVE_TICK_MID", **future}, symbol="EURCHF"
    )
    assert invalid["quote_health_reason"] == "QUOTE_SNAPSHOT_TIMESTAMP_FUTURE"
    pipeline._context_bus.update_tick(tick(clock))
    valid = pipeline._decision_price_lineage_payload(lineage(pipeline, build_context(pipeline)), symbol="EURCHF")
    assert valid["quote_health_reason"] == "QUOTE_RESTART_WARMUP_BASELINE_ESTABLISHED"
    assert valid["quote_observation_count"] == 1


def test_out_of_order_quote_is_blocked_without_overwriting_feed_freshness(pipeline, clock):
    current = clock - timedelta(seconds=2)
    pipeline._context_bus.update_tick(tick(current))
    newer = build_context(pipeline)
    older = type(newer)(
        symbol="EURCHF",
        raw_allowed_direction=None,
        bid=0.94,
        ask=0.9402,
        tick_snapshot_timestamp_epoch=(current - timedelta(seconds=1)).timestamp(),
    )
    pipeline._decision_price_lineage_payload(lineage(pipeline, newer), symbol="EURCHF")
    out_of_order = pipeline._decision_price_lineage_payload(lineage(pipeline, older), symbol="EURCHF")
    assert out_of_order["quote_health_status"] == "OUT_OF_ORDER"
    assert out_of_order["quote_health_execution_blocked"] is True
    assert out_of_order["reference_price_is_live"] is False
    assert out_of_order["price_freshness_status"] == "LIVE"
    assert out_of_order["quote_observation_count"] == 1


def test_valid_tick_observations_keep_existing_three_observation_thirty_second_warmup(pipeline, clock):
    result: dict[str, Any] = {}
    for seconds, bid in [(-30, 0.94), (-15, 0.9401), (0, 0.9402)]:
        pipeline._context_bus.update_tick(tick(clock + timedelta(seconds=seconds), bid=bid))
        result = pipeline._decision_price_lineage_payload(lineage(pipeline, build_context(pipeline)), symbol="EURCHF")
    assert result["quote_health_status"] == "LIVE"
    assert result["quote_observation_count"] == 3
    assert result["quote_warmup_elapsed_seconds"] == 30.0
    assert result["reference_price_is_live"] is True
    assert result["price_freshness_status"] == "LIVE"
