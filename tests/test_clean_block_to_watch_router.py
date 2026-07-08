from __future__ import annotations

import logging

from analysis.clean_block_watch_router import (
    emit_signal_watch_promotion_diagnostic,
    route_clean_block_to_watch,
    route_clean_blocks_to_watch,
)
from analysis.market_context_validator import MarketContext


def _candidate(symbol="USDCAD", direction="BUY", start="2026-06-23T05:00:49+00:00", end="2026-06-23T05:57:02+00:00"):
    return {
        "symbol": symbol,
        "direction": direction,
        "block_start_utc": start,
        "block_end_utc": end,
        "valid_since_utc": "2026-06-23T05:05:49+00:00",
        "duration_seconds": 3373.0,
        "duration_minutes": 56.22,
        "events": 48,
        "effective_ticks": 48,
        "effective_density_per_minute": 8.1,
        "ledger_type": "V1_SCANNER_CLEAN_BLOCK_LEDGER",
        "ledger_source": "SIGNAL_THROTTLE_V1_CLEAN_BLOCK_LEDGER",
        "split_rule": "SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE",
        "gap_policy": "SCANNER_CYCLE_QUALITY_ONLY",
        "scanner_cycle_aware": True,
        "source_stream_profile": {"RAW_THROTTLED": 36, "ALLOWED": 12},
        "raw_signal_throttle_severity_profile": {"ERROR": 36, "INFO": 12},
        "raw_signal_throttle_error_count": 36,
        "raw_signal_throttle_primary_severity": "ERROR",
        "raw_pressure_origin": "SIGNAL_THROTTLE_RAW_THROTTLED",
    }


def _market(symbol="USDCAD"):
    return MarketContext(
        symbol=symbol,
        raw_allowed_direction="BUY",
        price_at_signal_start=1.3730,
        price_at_5m_confirm=1.3735,
        price_at_signal_end=1.3740,
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        price_position="MID_RANGE",
        main_support=1.3700,
        main_resistance=1.3800,
    )


def test_every_clean_block_gets_watch_or_diagnostic():
    candidates = [
        _candidate("USDCAD", "BUY"),
        _candidate("GBPNZD", "BUY", start="2026-06-23T06:00:00+00:00", end="2026-06-23T06:58:00+00:00"),
        _candidate("GBPJPY", "SELL", start="2026-06-23T07:00:00+00:00", end="2026-06-23T08:02:46+00:00"),
    ]

    routes = route_clean_blocks_to_watch(candidates, market_contexts={"USDCAD": _market("USDCAD")})

    assert len(routes) == len(candidates)
    assert {route.event for route in routes} <= {
        "signal_watch_json",
        "signal_watch_promotion_diagnostic",
        "signal_throttle_clean_block_radar",
    }
    assert sum(route.emit_as_watch for route in routes) == 1
    assert sum(route.diagnostic for route in routes) == 2


def test_clean_block_with_market_context_becomes_non_executable_watch():
    route = route_clean_block_to_watch(_candidate(), market_context=_market())

    assert route.event == "signal_watch_json"
    assert route.emit_as_watch is True
    payload = route.payload
    assert payload["status"] == "CLEAN_BLOCK_BUY_WATCH"
    assert payload["source_clean_block_id"] == "USDCAD_20260623T050049Z_20260623T050549Z"
    assert payload["source_clean_block_first_valid_end_utc"] == "2026-06-23T05:05:49+00:00"
    assert payload["source_clean_block_latest_end_utc"] == "2026-06-23T05:57:02+00:00"
    assert payload["source_clean_block_latest_duration_seconds"] == 3373.0
    assert payload["watch_promotion_source"] == "CLEAN_BLOCK_ROUTER"
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False
    assert payload["requires_m15_close"] is False
    assert payload["requires_m15_close_policy"] == "OPTIONAL_HTF_ALIGNED_CONTINUATION"
    assert payload["ledger_type"] == "V1_SCANNER_CLEAN_BLOCK_LEDGER"
    assert payload["source_stream_profile"]["RAW_THROTTLED"] == 36
    assert payload["raw_signal_throttle_primary_severity"] == "ERROR"
    assert payload["raw_pressure_origin"] == "SIGNAL_THROTTLE_RAW_THROTTLED"


def test_clean_block_id_stays_stable_as_latest_end_moves():
    first = route_clean_block_to_watch(_candidate(end="2026-06-23T05:57:02+00:00"), market_context=_market())
    later = route_clean_block_to_watch(
        _candidate(end="2026-06-23T05:58:32+00:00"),
        market_context=_market(),
    )

    assert first.payload["source_clean_block_id"] == later.payload["source_clean_block_id"]
    assert later.payload["source_clean_block_latest_end_utc"] == "2026-06-23T05:58:32+00:00"


def test_clean_block_watch_requires_m15_close_at_key_level_risk():
    market = _market()
    market = MarketContext(
        **{
            **market.__dict__,
            "price_position": "MAIN_RESISTANCE",
        }
    )

    route = route_clean_block_to_watch(_candidate(), market_context=market)

    assert route.payload["requires_m15_close"] is True
    assert route.payload["requires_m15_close_policy"] == "REQUIRED_KEY_LEVEL_OR_REJECTION_RISK"


def test_clean_block_router_uses_raw_pressure_direction_when_direction_unresolved():
    candidate = _candidate(direction="UNRESOLVED")
    candidate["raw_pressure_direction"] = "BUY"

    route = route_clean_block_to_watch(candidate, market_context=_market())

    assert route.event == "signal_watch_json"
    assert route.payload["status"] == "CLEAN_BLOCK_BUY_WATCH"
    assert route.payload["raw_direction"] == "BUY"
    assert route.payload["candidate_direction"] == "BUY"
    assert route.payload["final_direction"] == "WAIT"
    assert route.payload["valid_for_execution"] is False


def test_missing_context_becomes_clean_block_radar_confirmed():
    route = route_clean_block_to_watch(_candidate(), market_context=None)

    assert route.event == "signal_throttle_clean_block_radar"
    assert route.diagnostic is True
    assert route.payload["status"] == "CLEAN_BLOCK_CONFIRMED_RADAR"
    assert route.payload["eligible_for_signal_watch"] is False
    assert "MARKET_CONTEXT_MISSING" in route.payload["blocked_by"]
    assert route.payload["next_required_stage"] == "PRICE_STRUCTURE_CONTEXT"
    assert route.payload["market_context_applied"] is False
    assert route.payload["source_stream_profile"]["RAW_THROTTLED"] == 36
    assert route.payload["raw_signal_throttle_error_count"] == 36


def test_signal_watch_promotion_diagnostic_emits(caplog):
    route = route_clean_block_to_watch(_candidate(), market_context=None)

    with caplog.at_level(logging.WARNING, logger="signal_json"):
        assert emit_signal_watch_promotion_diagnostic(route.payload) is True

    assert "[SignalWatchPromotionDiagnostic]" in caplog.text
    assert '"event":"signal_throttle_clean_block_radar"' in caplog.text
    assert '"status":"CLEAN_BLOCK_CONFIRMED_RADAR"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
