from __future__ import annotations

from analysis.market_context_validator import MarketContext
from analysis.signal_throttle_followthrough_score import (
    build_signal_throttle_followthrough_scores,
    followthrough_context_for_symbol,
    signal_throttle_followthrough_score_log_payload,
)


def _tier_row(symbol: str = "GBPCAD", direction: str = "BUY") -> dict:
    return {
        "symbol": symbol,
        "direction": direction,
        "effective_pressure_tier": "TIER_1_PRIMARY_ANALYSIS",
        "tier_scope": "LIVE_120M",
        "tier_score": 92.0,
        "tier_reasons": ["RECENT_CLEAN_BLOCK_GE_30M", "THEME_ALIGNED"],
        "metrics": {
            "live": {
                "timing_maturity_bucket": "MAJOR_30M",
                "timing_maturity_score": 30.0,
                "theme_aligned": True,
            }
        },
    }


def test_followthrough_score_rewards_open_lane_clean_pressure():
    scores = build_signal_throttle_followthrough_scores(
        clean_watch_candidates=[
            {
                "symbol": "GBPCAD",
                "raw_pressure_direction": "BUY",
                "source_clean_block_id": "GBPCAD_20260708T010000Z_20260708T013500Z",
                "clean_block_duration_seconds": 2100.0,
                "effective_ticks": 72,
                "effective_density_per_minute": 2.2,
                "max_gap_seconds": 64.0,
            }
        ],
        pressure_tiers=[_tier_row()],
        market_contexts={
            "GBPCAD": MarketContext(
                symbol="GBPCAD",
                raw_allowed_direction="BUY",
                pip_value=0.0001,
                price_at_signal_start=1.8500,
                price_at_signal_end=1.8520,
                key_support=1.8480,
                key_resistance=1.8580,
                price_position="MID_RANGE",
                m15_phase="BULLISH_PULLBACK",
                h1_phase="BULLISH",
                theme_aligned=True,
            )
        },
        microboost_summary={
            "latest": {
                "symbol": "GBPCAD",
                "direction": "BUY",
                "phase_priced": "CONTINUATION_MICROBOOST",
            }
        },
    )

    score = scores[0]
    assert score["symbol"] == "GBPCAD"
    assert score["followthrough_score"] >= 80
    assert score["followthrough_bucket"] == "HIGH_FOLLOWTHROUGH_CANDIDATE"
    assert score["directional_room_pips"] == 60.0
    assert score["microboost_role"] == "CONFIRMATION_OR_ACCELERATION"
    assert score["gap_degradation_penalty"] == 0.0
    assert score["valid_for_execution"] is False
    assert score["execution_impact"] is False


def test_followthrough_score_penalizes_late_buy_at_resistance_with_broken_gap():
    scores = build_signal_throttle_followthrough_scores(
        clean_watch_candidates=[
            {
                "symbol": "USDCAD",
                "raw_pressure_direction": "BUY",
                "source_clean_block_id": "USDCAD_20260708T020000Z_20260708T023500Z",
                "clean_block_duration_seconds": 2100.0,
                "effective_ticks": 120,
                "effective_density_per_minute": 35.0,
                "max_gap_seconds": 1900.0,
            }
        ],
        pressure_tiers=[_tier_row("USDCAD", "BUY")],
        market_contexts={
            "USDCAD": MarketContext(
                symbol="USDCAD",
                raw_allowed_direction="BUY",
                pip_value=0.0001,
                price_at_signal_start=1.3600,
                price_at_signal_end=1.3668,
                key_support=1.3620,
                key_resistance=1.3670,
                price_position="MAIN_RESISTANCE",
                m15_phase="BEARISH_PULLBACK",
                h1_phase="BULLISH",
                theme_aligned=True,
            )
        },
        microboost_summary={
            "latest": {
                "symbol": "USDCAD",
                "direction": "BUY",
                "phase_priced": "EXHAUSTION_AT_RESISTANCE",
            }
        },
    )

    score = scores[0]
    assert score["followthrough_bucket"] == "LATE_OR_ABSORPTION_RISK"
    assert score["pressure_quality_bucket"] == "BROKEN_SEQUENCE_PRESSURE"
    assert score["gap_degradation_penalty"] == 20.0
    assert score["late_move_penalty"] > 0
    assert "BUY_PRESSURE_AT_KEY_RESISTANCE_NO_CHASE" in score["risk_flags"]
    assert "MICROBOOST_ABSORPTION_WARNING" in score["risk_flags"]
    assert score["valid_for_execution"] is False


def test_followthrough_log_payload_and_watch_context_are_execution_neutral():
    scores = [
        {
            "symbol": "GBPUSD",
            "direction": "SELL",
            "followthrough_score": 76,
            "followthrough_bucket": "MEDIUM_FOLLOWTHROUGH_CANDIDATE",
            "pressure_quality_bucket": "ACTIVE_CLEAN_PRESSURE",
            "duration_maturity_bucket": "SUSTAINED_CONFIRMED_15M",
            "microboost_role": "ACCELERATION",
            "room_to_move_score": 16.0,
            "directional_room_pips": 24.0,
            "gap_health": "HEALTHY",
            "late_move_penalty": 0.0,
            "gap_degradation_penalty": 0.0,
            "risk_flags": [],
        }
    ]

    payload = signal_throttle_followthrough_score_log_payload(scores)
    context = followthrough_context_for_symbol(scores, "GBPUSD")

    assert payload["event"] == "signal_throttle_followthrough_score_snapshot"
    assert payload["execution_impact"] is False
    assert payload["valid_for_execution"] is False
    assert payload["scores"][0]["symbol"] == "GBPUSD"
    assert context["followthrough_score"] == 76
    assert context["source_event"] == "SignalThrottleFollowthroughScore"
    assert context["execution_impact"] is False
    assert context["valid_for_execution"] is False
