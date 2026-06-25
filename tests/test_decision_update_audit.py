from __future__ import annotations

from analysis.decision_update_audit import (
    detect_event_flood,
    parse_signal_decision_update_rows,
    rank_symbol_direction_pressure,
    summarize_decision_updates,
)


def test_parse_signal_decision_update_rows_ignores_other_channels() -> None:
    rows = [
        {
            "timestamp": "2026-06-25T12:00:00Z",
            "severity": "warning",
            "message": (
                '[SignalDecisionUpdateJSON] {"event":"signal_decision_update_json",'
                '"symbol":"USDCAD","signal_family":"SIGNAL_THROTTLE_PRESSURE",'
                '"status":"NO_TRADE_REASONED","raw_direction":"BUY","valid_for_execution":false,'
                '"signal_valid_price":1.3701}'
            ),
        },
        {
            "timestamp": "2026-06-25T12:00:01Z",
            "severity": "warning",
            "message": '[SignalWatchJSON] {"event":"signal_watch_json","symbol":"USDCAD"}',
        },
    ]

    events = parse_signal_decision_update_rows(rows)

    assert len(events) == 1
    assert events[0].symbol == "USDCAD"
    assert events[0].direction == "BUY"
    assert events[0].valid_for_execution is False


def test_summarize_decision_updates_exposes_family_status_and_pressure_rank() -> None:
    rows = [
        {
            "timestamp": f"2026-06-25T12:00:0{idx}Z",
            "severity": "warning",
            "message": (
                '[SignalDecisionUpdateJSON] {"event":"signal_decision_update_json",'
                '"symbol":"USDCAD","signal_family":"SIGNAL_THROTTLE_PRESSURE",'
                '"status":"NO_TRADE_REASONED","raw_direction":"BUY","valid_for_execution":false}'
            ),
        }
        for idx in range(3)
    ]
    rows.append(
        {
            "timestamp": "2026-06-25T12:01:00Z",
            "severity": "warning",
            "message": (
                '[SignalDecisionUpdateJSON] {"event":"signal_decision_update_json",'
                '"symbol":"AUDCAD","signal_family":"MICROBOOST_COUNTER_ENTRY",'
                '"status":"WAIT_STRUCTURE_OR_NEXT_M15","raw_direction":"BUY","valid_for_execution":false}'
            ),
        }
    )
    events = parse_signal_decision_update_rows(rows)

    summary = summarize_decision_updates(events)
    pressure = rank_symbol_direction_pressure(events)
    floods = detect_event_flood(events, min_count=3)

    assert summary["total_events"] == 4
    assert summary["signal_json_final"] == 0
    assert summary["valid_for_execution_true"] == 0
    assert summary["family_counts"]["SIGNAL_THROTTLE_PRESSURE"] == 3
    assert pressure[0] == {"symbol": "USDCAD", "direction": "BUY", "count": 3}
    assert floods[0]["symbol"] == "USDCAD"
