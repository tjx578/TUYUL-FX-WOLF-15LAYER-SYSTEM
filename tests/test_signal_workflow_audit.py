from __future__ import annotations

import csv
import json

from analysis.signal_workflow_audit import main, parse_signal_workflow_rows, summarize_signal_workflow


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
    assert summary["accuracy_scope_gate"]["status"] == "SINGLE_DEPLOYMENT_VALID"
    assert summary["accuracy_scope_gate"]["accuracy_computation_allowed"] is True


def test_signal_workflow_audit_rejects_mixed_deployment_accuracy_without_explicit_mode():
    rows = [
        {
            "timestamp": "2026-07-10T00:00:00Z",
            "message": (
                '[SignalPressureStateJSON] {"event":"signal_pressure_state_json",'
                '"schema_version":"2.0-pressure-state","symbol":"NZDCHF","valid_for_execution":false}'
            ),
            "tags": '{"deployment":"dep-a"}',
        },
        {
            "timestamp": "2026-07-10T00:01:00Z",
            "message": (
                '[SignalPressureStateJSON] {"event":"signal_pressure_state_json",'
                '"symbol":"NZDCAD","valid_for_execution":false}'
            ),
            "tags": '{"deployment":"dep-b"}',
        },
    ]
    events = parse_signal_workflow_rows(rows)

    summary = summarize_signal_workflow(events)
    historical = summarize_signal_workflow(events, historical_cross_deployment_audit=True)

    assert summary["accuracy_scope_gate"]["status"] == "REJECTED_MIXED_DEPLOYMENT"
    assert summary["accuracy_scope_gate"]["accuracy_computation_allowed"] is False
    assert historical["accuracy_scope_gate"]["status"] == "HISTORICAL_CROSS_DEPLOYMENT_AUDIT"
    assert historical["accuracy_scope_gate"]["accuracy_computation_allowed"] is True
    assert summary["pressure_state_schema_gate"] == {
        "canonical_schema_version": "2.0-pressure-state",
        "schema_counts": {"2.0-pressure-state": 1, "LEGACY_UNVERSIONED": 1},
        "total_pressure_states": 2,
        "noncanonical_pressure_states": 1,
        "consistent": False,
        "status": "REJECTED_MIXED_OR_LEGACY_SCHEMA",
    }


def test_signal_workflow_audit_summarizes_pressure_tier_snapshot_and_watch_context():
    rows = [
        {
            "timestamp": "2026-07-01T00:00:00Z",
            "message": (
                '[SignalThrottlePressureTierSnapshot] {"event":"signal_throttle_pressure_tier_snapshot",'
                '"schema_version":"1.1-pressure-tier","generated_at_utc":"2026-07-01T00:00:00Z",'
                '"display_line":"pressure_tiers tier1=1[XAGUSD:SELL:88.0] tier2=0[-] '
                'tier3_hidden=2 stale=1 unsafe_mixed=0 execution_impact=false",'
                '"summary":{"tier_1":1,"tier_2":0,"tier_3_hidden":2,"stale_archive":1,'
                '"unsafe_mixed_deployment":0},'
                '"tier_1":[{"symbol":"XAGUSD","effective_pressure_tier":"TIER_1_PRIMARY_ANALYSIS",'
                '"dominant_direction":"SELL","tier_score":88.0,"tier_action":"PRIORITIZE_ANALYSIS"}],'
                '"tier_2":[],"tier_3_hidden_count":2,"stale_archive_count":1,'
                '"unsafe_mixed_deployment_count":0,'
                '"visibility_policy":{"tier_3":"HIDDEN_FROM_SNAPSHOT_ROWS"},'
                '"execution_guard":{"decision_update_tier_context_allowed":false},'
                '"tier_is_execution_signal":false,"tier_execution_impact":false}'
            ),
        },
        {
            "timestamp": "2026-07-01T00:00:01Z",
            "message": (
                '[SignalWatchJSON] {"event":"signal_watch_json","symbol":"EURUSD",'
                '"cluster_id":"EURUSD_1","status":"EARLY_SELL_WATCH","raw_direction":"BUY",'
                '"candidate_direction":"SELL","watch_direction":"SELL","final_direction":"WAIT",'
                '"valid_for_execution":false,'
                '"pressure_priority_context":{"effective_pressure_tier":"TIER_3_KEY_LEVEL_RADAR_EXCEPTION",'
                '"tier_action":"RADAR_EXCEPTION_ONLY","low_event_high_impact_candidate":true,'
                '"tier_is_execution_signal":false,"tier_execution_impact":false}}'
            ),
        },
    ]

    events = parse_signal_workflow_rows(rows)
    summary = summarize_signal_workflow(events)

    assert summary["channel_counts"]["SignalThrottlePressureTierSnapshot"] == 1
    assert summary["pressure_tier_snapshot_count"] == 1
    assert summary["latest_pressure_tier_snapshot"]["schema_version"] == "1.1-pressure-tier"
    assert summary["latest_pressure_tier_snapshot"]["display_line"].startswith("pressure_tiers tier1=1")
    assert summary["latest_pressure_tier_snapshot"]["summary"]["tier_3_hidden"] == 2
    assert (
        summary["latest_pressure_tier_snapshot"]["visibility_policy"]["tier_3"]
        == "HIDDEN_FROM_SNAPSHOT_ROWS"
    )
    assert summary["latest_pressure_tier_snapshot"]["execution_guard"] == {
        "decision_update_tier_context_allowed": False
    }
    assert summary["latest_pressure_tier_snapshot"]["tier_1"][0]["symbol"] == "XAGUSD"
    assert summary["latest_pressure_tier_snapshot"]["tier_3_hidden_count"] == 2
    assert summary["watch_pressure_priority_context_count"] == 1
    assert summary["watch_pressure_priority_context_by_symbol"] == {"EURUSD": 1}
    assert summary["tier3_key_level_exception_by_symbol"] == {"EURUSD": 1}
    assert summary["low_event_high_impact_watch_by_symbol"] == {"EURUSD": 1}
    assert summary["tier_leakage_guard"]["clean"] is True


def test_signal_workflow_audit_detects_tier_leakage_to_decision_or_signal():
    rows = [
        {
            "timestamp": "2026-07-01T00:00:00Z",
            "message": (
                '[SignalDecisionUpdateJSON] {"event":"signal_decision_update_json","symbol":"EURUSD",'
                '"status":"WAIT_STRUCTURE_OR_NEXT_M15","valid_for_execution":false,'
                '"reason":"incorrect TIER_1 pressure reason",'
                '"pressure_priority_context":{"effective_pressure_tier":"TIER_1_PRIMARY_ANALYSIS"}}'
            ),
        },
        {
            "timestamp": "2026-07-01T00:00:01Z",
            "message": (
                '[SignalJSON] {"event":"signal_json","symbol":"XAGUSD","status":"SELL_TIMING_VALID",'
                '"effective_pressure_tier":"TIER_1_PRIMARY_ANALYSIS","valid_for_execution":true}'
            ),
        },
    ]

    summary = summarize_signal_workflow(parse_signal_workflow_rows(rows))

    assert summary["tier_leakage_guard"]["clean"] is False
    assert summary["tier_leakage_guard"]["decision_or_signal_with_pressure_priority_context"] == 1
    assert summary["tier_leakage_guard"]["decision_or_signal_with_effective_pressure_tier"] == 1
    assert summary["tier_leakage_guard"]["decision_or_signal_reason_mentions_tier"] == 1
    assert summary["tier_leakage_guard"]["leaking_symbols"] == ["EURUSD", "XAGUSD"]


def test_signal_workflow_audit_cli_outputs_pressure_tier_summary(tmp_path, capsys):
    csv_path = tmp_path / "logs.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "message"])
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2026-07-01T00:00:00Z",
                "message": (
                    '[SignalThrottlePressureTierSnapshot] {"event":"signal_throttle_pressure_tier_snapshot",'
                    '"generated_at_utc":"2026-07-01T00:00:00Z",'
                    '"tier_1":[{"symbol":"XAGUSD","effective_pressure_tier":"TIER_1_PRIMARY_ANALYSIS"}],'
                    '"tier_2":[],"tier_3_hidden_count":4,'
                    '"tier_is_execution_signal":false,"tier_execution_impact":false}'
                ),
            }
        )
        writer.writerow(
            {
                "timestamp": "2026-07-01T00:00:01Z",
                "message": (
                    '[SignalWatchJSON] {"event":"signal_watch_json","symbol":"XAGUSD",'
                    '"status":"SELL_TIMING_WATCH","valid_for_execution":false,'
                    '"pressure_priority_context":{"effective_pressure_tier":"TIER_1_PRIMARY_ANALYSIS",'
                    '"tier_is_execution_signal":false,"tier_execution_impact":false}}'
                ),
            }
        )

    assert main([str(csv_path), "--compact"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["pressure_tier_snapshot_count"] == 1
    assert output["latest_pressure_tier_snapshot"]["tier_1"][0]["symbol"] == "XAGUSD"
    assert output["latest_pressure_tier_snapshot"]["tier_3_hidden_count"] == 4
    assert output["watch_pressure_priority_context_by_symbol"] == {"XAGUSD": 1}
    assert output["tier_leakage_guard"]["clean"] is True
