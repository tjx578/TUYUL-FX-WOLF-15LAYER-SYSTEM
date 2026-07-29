from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from analysis.signal_throttle_log_analyzer import (
    SignalThrottleLogEvent,
    analyze_signal_throttle_csv,
    analyze_signal_throttle_events,
    build_pressure_blocks,
)
from analysis.signal_throttle_pressure_tier import (
    ARCHIVE_SCOPE,
    IMPACT_TIER_1_KEY_LEVEL,
    TIER_1_OVERFLOW_RADAR,
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


def _pressure_block(
    symbol: str,
    *,
    start_offset_seconds: int,
    duration_seconds: int,
    direction: str = "BUY",
    effective_density_per_minute: float = 1.0,
) -> SimpleNamespace:
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC) + timedelta(seconds=start_offset_seconds)
    return SimpleNamespace(
        symbol=symbol,
        start=start,
        end=start + timedelta(seconds=duration_seconds),
        duration_seconds=float(duration_seconds),
        direction=direction,
        effective_density_per_minute=effective_density_per_minute,
        density_per_minute=effective_density_per_minute,
    )


def test_pressure_tier_snapshot_is_diagnostic_only_for_live_clean_block():
    events = [_pressure_event(offset, "USDJPY", "BUY") for offset in range(0, 361, 60)]

    report = analyze_signal_throttle_events(events)
    snapshot = report["pressure_tier_snapshot"]
    row = _row(snapshot, "USDJPY")

    assert row["effective_pressure_tier"] == TIER_1_PRIMARY_ANALYSIS
    assert row["tier_action"] == "PRIORITIZE_ANALYSIS"
    assert row["tier_is_execution_signal"] is False
    assert row["tier_execution_impact"] is False
    assert row["active_clean_block_id"].startswith("USDJPY_")
    assert row["last_valid_clean_block_id"] == row["active_clean_block_id"]
    assert row["fragmented_pressure_memory"]["clean_block_count"] == 1
    assert row["fragmented_pressure_memory"]["pure_clean_block_interrupted"] is False
    assert row["fragmented_pressure_memory"]["live_scope_fragmented_interrupted"] is False
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


def test_pressure_tier_timing_maturity_prioritizes_15m_over_5m_clean_block():
    events = [
        *[_pressure_event(1750 + index * 5, "EURUSD", "BUY") for index in range(6)],
        *[_pressure_event(1750 + index * 5, "GBPUSD", "BUY") for index in range(6)],
    ]
    snapshot = build_pressure_tier_snapshot(
        events,
        blocks=[
            _pressure_block("EURUSD", start_offset_seconds=1500, duration_seconds=300),
            _pressure_block("GBPUSD", start_offset_seconds=900, duration_seconds=900),
        ],
    )
    early = _row(snapshot, "EURUSD")
    mature = _row(snapshot, "GBPUSD")

    assert early["metrics"]["live"]["timing_maturity_bucket"] == "TIMING_VALID_5M"
    assert early["metrics"]["live"]["timing_maturity_score"] == 20.0
    assert mature["metrics"]["live"]["timing_maturity_bucket"] == "SUSTAINED_CONFIRMED_15M"
    assert mature["metrics"]["live"]["timing_maturity_score"] == 27.0
    assert mature["tier_score"] > early["tier_score"]
    assert "RECENT_CLEAN_BLOCK_GE_15M" in mature["tier_reasons"]
    assert "TIMING_MATURITY_CONFIRMED" in mature["tier_reasons"]


def test_pressure_tier_keeps_sub_5m_high_density_pressure_out_of_tier_1():
    events = [_pressure_event(index * 8, "AUDJPY", "BUY") for index in range(30)]
    snapshot = build_pressure_tier_snapshot(
        events,
        blocks=[
            _pressure_block(
                "AUDJPY",
                start_offset_seconds=0,
                duration_seconds=240,
                effective_density_per_minute=30.0,
            )
        ],
    )
    row = _row(snapshot, "AUDJPY")

    assert row["effective_pressure_tier"] != TIER_1_PRIMARY_ANALYSIS
    assert row["metrics"]["live"]["clean_block_count"] == 0
    assert row["metrics"]["live"]["timing_maturity_bucket"] == "SUB_5M_PRESSURE"
    assert "CLEAN_BLOCK_BELOW_5M" in row["tier_reasons"]


def test_pressure_tier_marks_30m_clean_block_as_major_pressure_duration():
    events = [_pressure_event(1750 + index * 5, "GBPAUD", "BUY") for index in range(6)]
    snapshot = build_pressure_tier_snapshot(
        events,
        blocks=[_pressure_block("GBPAUD", start_offset_seconds=0, duration_seconds=1800)],
    )
    row = _row(snapshot, "GBPAUD")

    assert row["metrics"]["live"]["timing_maturity_bucket"] == "MAJOR_30M"
    assert row["metrics"]["live"]["timing_maturity_score"] == 30.0
    assert "RECENT_CLEAN_BLOCK_GE_30M" in row["tier_reasons"]
    assert "MAJOR_PRESSURE_DURATION" in row["tier_reasons"]


def test_pressure_tier_session_15m_clean_block_stays_confirmation_support():
    session_events = [_pressure_event(index * 180, "NZDJPY", "SELL") for index in range(6)]
    fresh_context = [_pressure_event(4 * 3600, "EURUSD", "BUY")]
    snapshot = build_pressure_tier_snapshot(
        session_events + fresh_context,
        blocks=[_pressure_block("NZDJPY", start_offset_seconds=0, duration_seconds=900, direction="SELL")],
    )
    row = _row(snapshot, "NZDJPY")

    assert row["effective_pressure_tier"] == TIER_2_CONFIRMATION_SUPPORT
    assert row["tier_scope"] == "SESSION_24H"
    assert row["metrics"]["session"]["timing_maturity_bucket"] == "SUSTAINED_CONFIRMED_15M"
    assert "SESSION_FALLBACK_CAPPED_BELOW_LIVE" in row["tier_reasons"]


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
    assert memory["pure_clean_block_interrupted"] is True
    assert memory["live_scope_fragmented_interrupted"] is True
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
            "tier_1_overflow_radar": 0,
            "tier_3": 2,
            "fragmented_pressure_radar": 1,
            "pressure_memory_radar": 1,
            "theme_rotation_radar": 0,
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
    assert payload["schema_version"] == "1.2-pressure-tier"
    assert payload["summary"] == {
        "tier_1": 1,
        "tier_2": 1,
        "tier_3_hidden": 4,
        "tier_1_overflow_radar": 0,
        "tier_3_theme_radar": 2,
        "fragmented_pressure_radar": 1,
        "pressure_memory_radar": 1,
        "theme_rotation_radar": 0,
        "stale_archive": 1,
        "unsafe_mixed_deployment": 0,
    }
    assert payload["radar_breakdown"] == {
        "tier_1_overflow_radar": 0,
        "tier_3_theme_radar": 2,
        "fragmented_pressure_radar": 1,
        "pressure_memory_radar": 1,
        "theme_rotation_radar": 0,
    }
    assert payload["display_line"] == (
        "pressure_tiers tier1=1[XAGUSD:SELL:88.0] tier2=1[AUDCAD:BUY:44.0] "
        "tier3_hidden=4 radar_breakdown[tier3=2 fragmented=1 memory=1 theme_rotation=0] "
        "stale=1 unsafe_mixed=0 execution_impact=false"
    )
    assert payload["tier_1"][0]["symbol"] == "XAGUSD"
    assert payload["tier_1"][0]["event_count"] == 7
    assert payload["tier_1"][0]["clean_block_count"] == 1
    assert payload["tier_1"][0]["max_clean_block_minutes"] == 6.0
    assert payload["tier_1"][0]["tier_reason_codes"] == ["RECENT_CLEAN_BLOCK_GE_5M", "DIRECTION_PURITY_HIGH"]
    assert payload["tier_2"][0]["symbol"] == "AUDCAD"
    assert payload["tier_3_hidden_count"] == 4
    assert payload["radar_hidden_count"] == 4
    assert payload["visibility_policy"]["tier_1"] == "VISIBLE_PRIMARY_ANALYSIS_CAPPED"
    assert payload["visibility_policy"]["tier_1_overflow_radar"] == "HIDDEN_FROM_PRIMARY_WATCH_CONTEXT"
    assert payload["visibility_policy"]["tier_3"] == "HIDDEN_FROM_SNAPSHOT_ROWS"
    assert payload["execution_guard"]["decision_update_tier_context_allowed"] is False
    assert payload["tier_is_execution_signal"] is False
    assert payload["tier_execution_impact"] is False


def test_pressure_tier_caps_visible_tier_1_and_moves_overflow_to_radar():
    events = []
    blocks = []
    for index, symbol in enumerate(["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]):
        events.extend(_pressure_event(index * 10 + offset, symbol, "BUY") for offset in range(0, 361, 60))
        blocks.append(
            _pressure_block(
                symbol,
                start_offset_seconds=index * 10,
                duration_seconds=360,
                effective_density_per_minute=5.0 - index,
            )
        )

    snapshot = build_pressure_tier_snapshot(events, blocks=blocks, visible_tier_1_max_symbols=2)

    assert len(snapshot["tiers"]["tier_1"]) == 2
    assert len(snapshot["tiers"]["tier_1_overflow_radar"]) == 2
    overflow = [row for row in snapshot["symbols"] if row["effective_pressure_tier"] == TIER_1_OVERFLOW_RADAR]
    assert len(overflow) == 2
    assert all(row["original_effective_pressure_tier"] == TIER_1_PRIMARY_ANALYSIS for row in overflow)
    assert all(row["tier_action"] == "TIER_1_OVERFLOW_RADAR_ONLY" for row in overflow)
    assert all("TIER_1_VISIBLE_LIMIT_OVERFLOW" in row["tier_reasons"] for row in overflow)


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
    assert context["timing_maturity_bucket"] == "TIMING_VALID_5M"
    assert context["timing_maturity_score"] == 20.0
    assert context["clean_block_duration_seconds"] == 360.0
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
