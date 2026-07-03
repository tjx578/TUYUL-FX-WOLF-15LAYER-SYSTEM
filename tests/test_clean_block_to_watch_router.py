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
    }
    assert sum(route.emit_as_watch for route in routes) == 1
    assert sum(route.diagnostic for route in routes) == 2


def test_clean_block_with_market_context_becomes_non_executable_watch():
    route = route_clean_block_to_watch(_candidate(), market_context=_market())

    assert route.event == "signal_watch_json"
    assert route.emit_as_watch is True
    payload = route.payload
    assert payload["status"] == "CLEAN_BLOCK_BUY_WATCH"
    assert payload["source_clean_block_id"] == "USDCAD_20260623T050049Z_20260623T055702Z"
    assert payload["watch_promotion_source"] == "CLEAN_BLOCK_ROUTER"
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False
    assert payload["requires_m15_close"] is False
    assert payload["requires_m15_close_policy"] == "OPTIONAL_HTF_ALIGNED_CONTINUATION"


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


def test_missing_context_becomes_promotion_diagnostic():
    route = route_clean_block_to_watch(_candidate(), market_context=None)

    assert route.event == "signal_watch_promotion_diagnostic"
    assert route.diagnostic is True
    assert route.payload["eligible_for_signal_watch"] is False
    assert "MARKET_CONTEXT_MISSING" in route.payload["blocked_by"]
    assert route.payload["next_required_stage"] == "HYDRATE_MARKET_CONTEXT"


def test_signal_watch_promotion_diagnostic_emits(caplog):
    route = route_clean_block_to_watch(_candidate(), market_context=None)

    with caplog.at_level(logging.WARNING, logger="signal_json"):
        assert emit_signal_watch_promotion_diagnostic(route.payload) is True

    assert "[SignalWatchPromotionDiagnostic]" in caplog.text
    assert '"event":"signal_watch_promotion_diagnostic"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
