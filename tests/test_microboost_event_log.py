from __future__ import annotations

from datetime import UTC, datetime

from analysis.microboost_event_log import (
    build_microboost_intel_event,
    emit_microboost_intel,
    parse_microboost_intel_row,
)


def test_microboost_intel_emits_standalone_parseable_log(capsys):
    report = {
        "microboost_summary": {
            "count_total": 1,
            "market_context_applied": True,
            "action": "VALIDATE_RETEST_OR_HOLD",
            "latest": {
                "symbol": "CADJPY",
                "direction": "BUY",
                "phase_unpriced": "DENSE_MICROBOOST",
                "phase_priced": "TREND_CONTINUATION_MICROBOOST",
                "action": "VALIDATE_RETEST_OR_HOLD",
                "event_count": 4,
                "effective_tick_count": 15,
                "suppressed_tick_count": 11,
                "effective_density_per_minute": 8.25,
                "duration_seconds": 109.2,
                "requires_market_context": False,
                "end_utc": "2026-05-18T10:15:23+00:00",
                "market_context_validation": {"final_direction": "BUY"},
                "market_context_snapshot": {
                    "price_at_signal_start": 103.25,
                    "price_at_5m_confirm": 103.32,
                    "price_at_signal_end": 103.38,
                    "m15_phase": "PIVOT_RECLAIM",
                    "h1_phase": "BULLISH",
                    "price_position": "MID_RANGE",
                },
                "reason": "microboost_aligns_with_running_trend_away_from_main_extreme",
            },
        }
    }

    event = build_microboost_intel_event(report)
    emit_microboost_intel(event)
    line = capsys.readouterr().out.strip()

    assert line.startswith("[MicroboostIntel] symbol=CADJPY")
    parsed = parse_microboost_intel_row(
        {
            "timestamp": datetime(2026, 5, 18, 10, 15, 23, tzinfo=UTC).isoformat(),
            "severity": "info",
            "message": line,
        }
    )

    assert parsed is not None
    assert parsed.event.symbol == "CADJPY"
    assert parsed.event.raw_direction == "BUY"
    assert parsed.event.final_direction == "BUY"
    assert parsed.event.phase_unpriced == "DENSE_MICROBOOST"
    assert parsed.event.phase_priced == "TREND_CONTINUATION_MICROBOOST"
    assert parsed.event.effective_tick_count == 15
    assert parsed.event.suppressed_tick_count == 11
    assert parsed.event.effective_density_per_minute == 8.25
    assert parsed.event.requires_market_context is False
    assert parsed.event.market_context_applied is True
    assert parsed.event.m15_phase == "PIVOT_RECLAIM"
    assert parsed.event.h1_phase == "BULLISH"
