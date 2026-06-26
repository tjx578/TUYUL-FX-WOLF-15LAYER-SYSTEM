from __future__ import annotations

from analysis.signal_workflow_audit import parse_signal_workflow_rows, summarize_signal_workflow


def test_signal_workflow_audit_joins_channels_and_counts_conflicts():
    watch_message = (
        '[SignalWatchJSON] {"event":"signal_watch_json","symbol":"USDCAD",'
        '"cluster_id":"USDCAD_1","signal_family":"MICROBOOST_COUNTER_ENTRY",'
        '"status":"SELL_TIMING_WATCH","raw_direction":"BUY","candidate_direction":"SELL",'
        '"watch_direction":"SELL","final_direction":"WAIT","valid_for_execution":false}'
    )
    rows = [
        {
            "timestamp": "2026-06-22T14:00:00Z",
            "message": (
                '[MicroboostIntel] {"event":"microboost_intel","symbol":"USDCAD",'
                '"cluster_id":"USDCAD_1","raw_direction":"BUY","phase_priced":"RESISTANCE_PRESSURE_WARNING"}'
            ),
            "tags": '{"deployment":"dep-a"}',
        },
        {
            "timestamp": "2026-06-22T14:00:01Z",
            "message": watch_message,
            "tags": '{"deployment":"dep-a"}',
        },
        {
            "timestamp": "2026-06-22T14:05:01Z",
            "message": (
                '[SignalDecisionUpdateJSON] {"event":"signal_decision_update_json","symbol":"USDCAD",'
                '"cluster_id":"USDCAD_1","pending_decision_id":"USDCAD_1_DECISION",'
                '"status":"WAIT_STRUCTURE_OR_NEXT_M15","raw_direction":"BUY",'
                '"candidate_direction":"SELL","watch_direction":"SELL","valid_for_execution":false}'
            ),
            "tags": '{"deployment":"dep-a"}',
        },
        {
            "timestamp": "2026-06-22T14:00:01Z",
            "message": watch_message,
            "tags": '{"deployment":"dep-a"}',
        },
    ]

    events = parse_signal_workflow_rows(rows, dedupe=True)
    summary = summarize_signal_workflow(events)

    assert summary["total_events"] == 3
    assert summary["channel_counts"]["MicroboostIntel"] == 1
    assert summary["channel_counts"]["SignalWatchJSON"] == 1
    assert summary["channel_counts"]["SignalDecisionUpdateJSON"] == 1
    assert summary["signal_json_final"] == 0
    assert summary["valid_for_execution_true"] == 0
    assert summary["raw_buy_candidate_sell_by_symbol"] == {"USDCAD": 2}
    assert summary["cluster_summary"]["watch_clusters_without_microboost"] == 0
    assert summary["cluster_summary"]["decision_clusters_with_watch"] == 1
