from __future__ import annotations

from datetime import UTC, datetime

from analysis.microboost_event_log import (
    build_microboost_intel_event,
    build_microboost_table_events,
    emit_microboost_intel,
    emit_microboost_table_event,
    parse_microboost_intel_row,
    parse_microboost_table_row,
)


def test_microboost_intel_emits_standalone_parseable_log(capsys, monkeypatch):
    monkeypatch.setenv("MICROBOOST_INTEL_FULL_PAYLOAD_ENABLED", "true")
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

    assert line.startswith("[MicroboostIntel]")
    assert "symbol=CADJPY" in line
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


def test_microboost_intel_lean_by_default_omits_heavy_market_context(capsys):
    report = {
        "microboost_summary": {
            "count_total": 1,
            "market_context_applied": True,
            "latest": {
                "symbol": "CADJPY",
                "direction": "BUY",
                "phase_unpriced": "DENSE_MICROBOOST",
                "phase_priced": "TREND_CONTINUATION_MICROBOOST",
                "action": "VALIDATE_RETEST_OR_HOLD",
                "event_count": 4,
                "effective_tick_count": 15,
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
                "reason": "microboost",
            },
        }
    }

    emit_microboost_intel(build_microboost_intel_event(report))
    line = capsys.readouterr().out.strip()

    assert line.startswith("[MicroboostIntel]")
    # Pure-stage markers are always present.
    assert "direction=UNRESOLVED" in line
    assert "valid_for_execution=false" in line
    assert "next_stage=SIGNAL_WATCH" in line
    # Heavy market-context fields are stripped from the lean (default) line.
    assert "m15_phase=" not in line
    assert "h1_phase=" not in line
    assert "price_start=" not in line
    assert "price_5m=" not in line
    assert "price_end=" not in line
    # The lean line still round-trips; heavy fields parse to None.
    parsed = parse_microboost_intel_row(
        {
            "timestamp": datetime(2026, 5, 18, 10, 15, 23, tzinfo=UTC).isoformat(),
            "severity": "info",
            "message": line,
        }
    )
    assert parsed is not None
    assert parsed.event.symbol == "CADJPY"
    assert parsed.event.m15_phase is None
    assert parsed.event.h1_phase is None
    assert parsed.event.price_at_signal_start is None


def test_microboost_table_events_emit_all_cluster_rows(capsys):
    report = {
        "microboost_summary": {
            "count_total": 3,
            "market_context_applied": False,
            "blocks": [
                {
                    "symbol": "CHFJPY",
                    "direction": "BUY",
                    "start_utc": "2026-05-18T12:33:59+00:00",
                    "end_utc": "2026-05-18T12:38:54+00:00",
                    "duration_minutes": 4.92,
                    "effective_tick_count": 47,
                    "suppressed_tick_count": 35,
                    "effective_density_per_minute": 9.55,
                    "phase_unpriced": "REPEATED_MICROBOOST",
                    "phase_priced": None,
                    "action": "PRIORITIZE_PAIR_FOR_MARKET_CONTEXT",
                    "requires_market_context": True,
                    "score": 76,
                    "reason": "unpriced_microboost_requires_market_context_before_entry_or_exit",
                },
                {
                    "symbol": "CADJPY",
                    "direction": "BUY",
                    "start_utc": "2026-05-18T12:18:09+00:00",
                    "end_utc": "2026-05-18T12:22:58+00:00",
                    "duration_minutes": 4.81,
                    "effective_tick_count": 46,
                    "suppressed_tick_count": 34,
                    "effective_density_per_minute": 9.57,
                    "phase_unpriced": "NEAR_TIMING_GATE_MICROBOOST",
                    "phase_priced": "TREND_CONTINUATION_MICROBOOST",
                    "action": "VALIDATE_RETEST_OR_HOLD",
                    "requires_market_context": False,
                    "score": 88,
                    "reason": "microboost_aligns_with_running_trend_away_from_main_extreme",
                },
                {
                    "symbol": "CADJPY",
                    "direction": "BUY",
                    "start_utc": "2026-05-18T12:40:26+00:00",
                    "end_utc": "2026-05-18T12:45:08+00:00",
                    "duration_minutes": 4.70,
                    "effective_tick_count": 45,
                    "suppressed_tick_count": 33,
                    "effective_density_per_minute": 9.57,
                    "phase_unpriced": "REPEATED_MICROBOOST",
                    "phase_priced": "LATE_DENSE_PRESSURE",
                    "action": "PROTECT_PROFIT",
                    "requires_market_context": False,
                    "score": 64,
                    "reason": "late_pressure_requires_protect_profit",
                },
            ],
        }
    }

    rows = build_microboost_table_events(report, timezone_name="Asia/Makassar")

    assert [row.symbol for row in rows] == ["CADJPY", "CADJPY", "CHFJPY"]
    assert rows[0].window_local == "20:18:09-20:22:58"
    assert rows[0].effective_tick_count == 46
    assert rows[0].duration_minutes == 4.81
    assert rows[0].effective_density_per_minute == 9.57
    assert rows[0].phase == "continuation"
    assert rows[1].phase == "late_dense"

    emit_microboost_table_event(rows[0])
    line = capsys.readouterr().out.strip()

    assert line.startswith("[MicroboostTable] rank=1")
    assert "symbol=CADJPY" in line
    assert "window_wita=20:18:09-20:22:58" in line
    assert "effective_ticks=46" in line
    assert "duration_minutes=4.81" in line
    assert "effective_density=9.57" in line
    assert "phase=continuation" in line

    parsed = parse_microboost_table_row(
        {
            "timestamp": datetime(2026, 5, 18, 12, 22, 58, tzinfo=UTC).isoformat(),
            "severity": "info",
            "message": line,
        }
    )

    assert parsed is not None
    assert parsed.event.symbol == "CADJPY"
    assert parsed.event.window_local == "20:18:09-20:22:58"
    assert parsed.event.effective_tick_count == 46
    assert parsed.event.phase == "continuation"


def test_microboost_parsers_ignore_signal_json_lifecycle_channels():
    signal_watch_row = {
        "timestamp": "2026-06-03T13:01:20Z",
        "severity": "warning",
        "message": (
            '[SignalWatchJSON] {"event":"signal_watch_json","symbol":"NZDJPY",'
            '"signal_family":"MICROBOOST_COUNTER_ENTRY","status":"BUY_TIMING_WATCH"}'
        ),
    }
    decision_row = {
        "timestamp": "2026-06-03T16:22:04Z",
        "severity": "warning",
        "message": (
            '[SignalDecisionUpdateJSON] {"event":"signal_decision_update_json","symbol":"GBPCAD",'
            '"signal_family":"MICROBOOST_COUNTER_ENTRY","status":"WAIT_STRUCTURE_OR_NEXT_M15"}'
        ),
    }

    assert parse_microboost_intel_row(signal_watch_row) is None
    assert parse_microboost_table_row(signal_watch_row) is None
    assert parse_microboost_intel_row(decision_row) is None
    assert parse_microboost_table_row(decision_row) is None
