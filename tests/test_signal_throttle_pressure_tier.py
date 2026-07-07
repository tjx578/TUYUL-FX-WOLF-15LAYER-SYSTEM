from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import (
    SignalThrottleLogEvent,
    analyze_signal_throttle_csv,
    analyze_signal_throttle_events,
    build_pressure_blocks,
)
from analysis.signal_throttle_pressure_tier import (
    ARCHIVE_SCOPE,
    IMPACT_TIER_1_KEY_LEVEL,
    TIER_1_PRIMARY_ANALYSIS,
    TIER_2_CONFIRMATION_SUPPORT,
    TIER_3_KEY_LEVEL_RADAR_EXCEPTION,
    TIER_3_THEME_RADAR,
    TIER_PRESSURE_MEMORY_RADAR,
    TIER_STALE_ARCHIVE,
    TIER_UNSAFE_MIXED_DEPLOYMENT,
    build_pressure_tier_snapshot,
    pressure_priority_context_for_symbol,
    pressure_tier_snapshot_log_payload,
)


def _pressure_event(offset_seconds: int, symbol: str, direction: str = "BUY") -> SignalThrottleLogEvent:
    timestamp = datetime(2026, 7, 1, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds)
    verdict = f"EXECUTE_{direction}"
    return SignalThrottleLogEvent(
        timestamp=timestamp,
        severity="info",
        message=f"[SignalThrottle] {symbol} allowed - verdict {verdict}",
        symbol=symbol,
        event_type="ALLOWED",
        verdict=verdict,
        direction=direction,
        raw_verdict=verdict,
        effective_action="ALLOWED",
        pressure_source="SignalThrottle",
        eligible_for_pressure_block=True,
        eligible_for_execution=True,
    )


def _row(snapshot: dict, symbol: str) -> dict:
    return next(item for item in snapshot["symbols"] if item["symbol"] == symbol)


def test_pressure_tier_snapshot_is_diagnostic_only_for_live_clean_block():
    events = [_pressure_event(offset, "USDJPY", "BUY") for offset in range(0, 361, 60)]

    report = analyze_signal_throttle_events(events)
    snapshot = report["pressure_tier_snapshot"]
    row = _row(snapshot, "USDJPY")

    assert row["effective_pressure_tier"] == TIER_1_PRIMARY_ANALYSIS
    assert row["tier_action"] == "PRIORITIZE_ANALYSIS"
    assert row["tier_is_execution_signal"] is False
    assert row["tier_execution_impact"] is False
    assert snapshot["tier_is_execution_signal"] is False
    assert snapshot["tier_execution_impact"] is False
    assert report["clean_entry_signal"] is False
    assert "valid_for_execution" not in row


def test_pressure_tier_keeps_old_clean_block_as_stale_archive_only():
    old_block = [_pressure_event(offset, "USDCAD", "SELL") for offset in range(0, 361, 60)]
    fresh_context = [_pressure_event(3 * 86400, "EURUSD", "BUY")]

    report = analyze_signal_throttle_events(old_block + fresh_context)
    row = _row(report["pressure_tier_snapshot"], "USDCAD")

    assert row["effective_pressure_tier"] == TIER_STALE_ARCHIVE
    assert row["tier_scope"] == ARCHIVE_SCOPE
    assert row["tier_action"] == "AUDIT_ONLY"
    assert "STALE_PRESSURE" in row["tier_reasons"]


def test_pressure_tier_mixed_deployment_disables_ranking():
    events = [_pressure_event(offset, "GBPAUD", "BUY") for offset in range(0, 361, 60)]

    snapshot = build_pressure_tier_snapshot(
        events,
        blocks=build_pressure_blocks(events),
        deployment_ids=["deploy-a", "deploy-b"],
    )
    row = _row(snapshot, "GBPAUD")

    assert snapshot["mixed_deployment"] is True
    assert snapshot["tiers"]["unsafe_mixed_deployment"] == ["GBPAUD"]
    assert row["effective_pressure_tier"] == TIER_UNSAFE_MIXED_DEPLOYMENT
    assert row["tier_action"] == "DO_NOT_RANK"
    assert row["tier_execution_impact"] is False


def test_pressure_tier_reads_mixed_deployment_from_csv_flag_snapshots(tmp_path):
    path = tmp_path / "mixed_deployment.csv"
    rows = [
        {
            "timestamp": "2026-07-01T00:00:00Z",
            "severity": "warning",
            "message": (
                '[SignalIntelligenceFlagSnapshot] {"event":"signal_intelligence_flag_snapshot",'
                '"deployment_id":"deploy-a"}'
            ),
        },
        *[
            {
                "timestamp": f"2026-07-01T00:0{minute}:00Z",
                "severity": "info",
                "message": "[SignalThrottle] GBPAUD allowed - verdict EXECUTE_BUY",
            }
            for minute in range(1, 6)
        ],
        {
            "timestamp": "2026-07-01T00:06:00Z",
            "severity": "warning",
            "message": (
                '[SignalIntelligenceFlagSnapshot] {"event":"signal_intelligence_flag_snapshot",'
                '"deployment_id":"deploy-b"}'
            ),
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "severity", "message"])
        writer.writeheader()
        writer.writerows(rows)

    report = analyze_signal_throttle_csv(path)
    row = _row(report["pressure_tier_snapshot"], "GBPAUD")

    assert report["pressure_tier_snapshot"]["mixed_deployment"] is True
    assert report["pressure_tier_snapshot"]["deployment_ids"] == ["deploy-a", "deploy-b"]
    assert row["effective_pressure_tier"] == TIER_UNSAFE_MIXED_DEPLOYMENT


def test_pressure_tier_scores_buy_and_sell_symmetrically():
    buy_events = [_pressure_event(offset, "EURUSD", "BUY") for offset in range(0, 361, 60)]
    sell_events = [_pressure_event(offset, "EURUSD", "SELL") for offset in range(0, 361, 60)]

    buy_snapshot = build_pressure_tier_snapshot(buy_events, blocks=build_pressure_blocks(buy_events))
    sell_snapshot = build_pressure_tier_snapshot(sell_events, blocks=build_pressure_blocks(sell_events))
    buy_row = _row(buy_snapshot, "EURUSD")
    sell_row = _row(sell_snapshot, "EURUSD")

    assert buy_row["effective_pressure_tier"] == sell_row["effective_pressure_tier"]
    assert buy_row["tier_score"] == sell_row["tier_score"]


def test_pressure_tier_tracks_fragmented_pressure_memory_without_clean_block():
    events = []
    for index in range(20):
        events.append(_pressure_event(index * 120, "XAGUSD", "SELL"))
        events.append(_pressure_event(index * 120 + 30, "EURUSD", "BUY"))

    snapshot = build_pressure_tier_snapshot(events, blocks=build_pressure_blocks(events))
    row = _row(snapshot, "XAGUSD")
    memory = row["fragmented_pressure_memory"]

    assert memory["fragmented_event_count"] == 20
    assert memory["clean_block_count"] == 0
    assert memory["same_symbol_reentry_count"] == 19
    assert memory["interrupted_by_other_symbols"] is True
    assert memory["pressure_memory_score"] >= 60
    assert row["effective_pressure_tier"] == TIER_PRESSURE_MEMORY_RADAR
    assert row["tier_action"] == "PRESSURE_MEMORY_RADAR_ONLY"
    assert row["tier_family"] == "PRESSURE_MEMORY_RADAR"
    assert row["pure_signal_throttle_tier"] is None
    assert snapshot["tiers"]["tier_1"] == []
    assert set(snapshot["tiers"]["pressure_memory_radar"]) == {"XAGUSD", "EURUSD"}
    assert "FRAGMENTED_PRESSURE_REPEATED" in row["tier_reasons"]
    assert "NO_CLEAN_BLOCK_FRAGMENTED_MEMORY" in row["tier_reasons"]


def test_pressure_tier_snapshot_log_payload_shows_tier_1_and_2_only():
    snapshot = {
        "generated_at_utc": "2026-07-01T00:06:00+00:00",
        "mixed_deployment": False,
        "deployment_ids": [],
        "summary": {
            "tier_1": 1,
            "tier_2": 1,
            "tier_3": 2,
            "stale_archive": 1,
            "unsafe_mixed_deployment": 0,
        },
        "symbols": [
            {
                "symbol": "XAGUSD",
                "direction": "SELL",
                "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                "tier_scope": "LIVE_120M",
                "tier_score": 88.0,
                "tier_action": "PRIORITIZE_ANALYSIS",
                "tier_reasons": ["RECENT_CLEAN_BLOCK_GE_5M", "DIRECTION_PURITY_HIGH"],
                "fragmented_pressure_memory": {
                    "pressure_memory_score": 22.0,
                    "same_symbol_reentry_count": 1,
                    "max_clean_block_minutes": 6.0,
                },
                "metrics": {"live": {"event_count": 7, "clean_block_count": 1}},
            },
            {
                "symbol": "AUDCAD",
                "direction": "BUY",
                "effective_pressure_tier": TIER_2_CONFIRMATION_SUPPORT,
                "tier_scope": "LIVE_120M",
                "tier_score": 44.0,
                "tier_action": "CONFIRMATION_SUPPORT",
                "tier_reasons": ["LIVE_120M_PRESSURE_EVENTS"],
                "metrics": {"live": {"event_count": 4, "clean_block_count": 0}},
            },
            {
                "symbol": "EURUSD",
                "direction": "SELL",
                "effective_pressure_tier": TIER_3_THEME_RADAR,
                "tier_scope": "LIVE_120M",
                "tier_score": 28.0,
                "tier_action": "RADAR_ONLY",
            },
        ],
    }

    payload = pressure_tier_snapshot_log_payload(snapshot)

    assert payload is not None
    assert payload["event"] == "signal_throttle_pressure_tier_snapshot"
    assert payload["schema_version"] == "1.1-pressure-tier"
    assert payload["summary"] == {
        "tier_1": 1,
        "tier_2": 1,
        "tier_3_hidden": 2,
        "stale_archive": 1,
        "unsafe_mixed_deployment": 0,
    }
    assert payload["display_line"] == (
        "pressure_tiers tier1=1[XAGUSD:SELL:88.0] tier2=1[AUDCAD:BUY:44.0] "
        "tier3_hidden=2 stale=1 unsafe_mixed=0 execution_impact=false"
    )
    assert payload["tier_1"][0]["symbol"] == "XAGUSD"
    assert payload["tier_1"][0]["event_count"] == 7
    assert payload["tier_1"][0]["clean_block_count"] == 1
    assert payload["tier_1"][0]["max_clean_block_minutes"] == 6.0
    assert payload["tier_1"][0]["tier_reason_codes"] == ["RECENT_CLEAN_BLOCK_GE_5M", "DIRECTION_PURITY_HIGH"]
    assert payload["tier_2"][0]["symbol"] == "AUDCAD"
    assert payload["tier_3_hidden_count"] == 2
    assert payload["visibility_policy"]["tier_3"] == "HIDDEN_FROM_SNAPSHOT_ROWS"
    assert payload["execution_guard"]["decision_update_tier_context_allowed"] is False
    assert payload["tier_is_execution_signal"] is False
    assert payload["tier_execution_impact"] is False


def test_pressure_priority_context_attaches_tier_1_to_watch_only_as_context():
    snapshot = build_pressure_tier_snapshot(
        [_pressure_event(offset, "USDJPY", "BUY") for offset in range(0, 361, 60)],
        blocks=build_pressure_blocks([_pressure_event(offset, "USDJPY", "BUY") for offset in range(0, 361, 60)]),
    )

    context = pressure_priority_context_for_symbol(
        snapshot,
        "USDJPY",
        watch_payload={"status": "CLEAN_BLOCK_BUY_WATCH", "valid_for_execution": False},
    )

    assert context is not None
    assert context["effective_pressure_tier"] == TIER_1_PRIMARY_ANALYSIS
    assert context["tier_source_event"] == "SignalThrottlePressureTierSnapshot"
    assert context["tier_is_execution_signal"] is False
    assert context["tier_execution_impact"] is False


def test_pressure_priority_context_hides_plain_tier_3_by_default():
    snapshot = {
        "symbols": [
            {
                "symbol": "EURUSD",
                "direction": "SELL",
                "effective_pressure_tier": TIER_3_THEME_RADAR,
                "tier_scope": "LIVE_120M",
                "tier_score": 28.0,
                "tier_action": "RADAR_ONLY",
                "tier_reasons": ["LOW_ACTIVITY"],
                "metrics": {"live": {"event_count": 3}},
            }
        ]
    }

    context = pressure_priority_context_for_symbol(
        snapshot,
        "EURUSD",
        watch_payload={
            "status": "EARLY_SELL_WATCH",
            "candidate_direction": "SELL",
            "price_position": "MID_RANGE",
            "market_context_applied": True,
            "valid_for_execution": False,
        },
    )

    assert context is None


def test_pressure_priority_context_rejects_non_watch_or_execution_payloads():
    snapshot = {
        "symbols": [
            {
                "symbol": "XAGUSD",
                "direction": "SELL",
                "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                "tier_scope": "LIVE_120M",
                "tier_score": 88.0,
                "tier_action": "PRIORITIZE_ANALYSIS",
                "tier_reasons": ["RECENT_CLEAN_BLOCK_GE_5M"],
                "metrics": {"live": {"event_count": 7}},
            }
        ]
    }

    assert pressure_priority_context_for_symbol(snapshot, "XAGUSD") is None
    assert (
        pressure_priority_context_for_symbol(
            snapshot,
            "XAGUSD",
            watch_payload={"status": "SELL_TIMING_VALID", "valid_for_execution": True},
        )
        is None
    )


def test_pressure_priority_context_allows_tier_3_key_level_exception():
    snapshot = {
        "symbols": [
            {
                "symbol": "EURUSD",
                "direction": "SELL",
                "effective_pressure_tier": TIER_3_THEME_RADAR,
                "tier_scope": "LIVE_120M",
                "tier_score": 28.0,
                "tier_action": "RADAR_ONLY",
                "tier_reasons": ["LOW_ACTIVITY"],
                "metrics": {"live": {"event_count": 3}},
            }
        ]
    }

    context = pressure_priority_context_for_symbol(
        snapshot,
        "EURUSD",
        watch_payload={
            "status": "EARLY_SELL_WATCH",
            "candidate_direction": "SELL",
            "price_position": "MAIN_RESISTANCE",
            "market_context_applied": True,
            "valid_for_execution": False,
        },
    )

    assert context is not None
    assert context["effective_pressure_tier"] == TIER_3_KEY_LEVEL_RADAR_EXCEPTION
    assert context["tier_action"] == "RADAR_EXCEPTION_ONLY"
    assert context["impact_tier"] == IMPACT_TIER_1_KEY_LEVEL
    assert context["low_event_high_impact_candidate"] is True
    assert "MAIN_RESISTANCE" in context["tier_reason_codes"]
