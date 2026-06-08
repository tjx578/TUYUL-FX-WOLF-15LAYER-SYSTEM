from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta

from analysis.market_context_validator import MarketContext
from analysis.signal_json_emitter import build_signal_json_event
from analysis.signal_throttle_log_analyzer import (
    SignalThrottleLiveAnalyzer,
    SignalThrottleLogEvent,
    analyze_signal_throttle_csv,
    analyze_signal_throttle_events,
    build_pressure_blocks,
    compute_currency_pressure,
    parse_engine_log_event,
    parse_signal_throttle_rows,
)

_FIXTURE = "tests/fixtures/signal_throttle_sample.csv"


def _event(offset_seconds: int, symbol: str, event_type: str = "THROTTLED") -> SignalThrottleLogEvent:
    verdict = "EXECUTE_REDUCED_RISK_BUY" if event_type != "THROTTLED" else None
    return SignalThrottleLogEvent(
        timestamp=datetime(2026, 5, 8, 12, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        severity="error" if event_type == "THROTTLED" else "info",
        message=f"[SignalThrottle] {symbol} {event_type}",
        symbol=symbol,
        event_type=event_type,
        verdict=verdict,
        direction="BUY" if verdict else None,
    )


def test_parse_signal_throttle_rows_extracts_allowed_and_throttled():
    rows = [
        {
            "timestamp": "2026-05-08T12:00:00Z",
            "severity": "error",
            "message": "[SignalThrottle] XAUUSD THROTTLED - 3 signals in last 300s (max 3) suppressed=2",
        },
        {
            "timestamp": "2026-05-08T12:00:10Z",
            "severity": "info",
            "message": "2026-05-08 | WARNING | x - [SignalThrottle] GBPCAD allowed - verdict EXECUTE_BUY",
        },
    ]

    events = parse_signal_throttle_rows(rows)

    assert [(event.symbol, event.event_type, event.direction) for event in events] == [
        ("XAUUSD", "THROTTLED", None),
        ("GBPCAD", "ALLOWED", "BUY"),
    ]
    assert events[1].raw_verdict == "EXECUTE_BUY"
    assert events[1].effective_action == "ALLOWED"
    assert events[1].is_downgraded is False
    assert events[0].suppressed == 2
    assert events[0].effective_ticks == 3


def test_parse_signal_throttle_check_as_pressure_canary():
    event = parse_engine_log_event(
        {
            "timestamp": "2026-06-08T08:49:17Z",
            "severity": "info",
            "message": (
                "2026-06-08 08:43:32 | WARNING | pipeline - "
                "event=signal_throttle_check symbol=AUDUSD authority=SIGNAL_THROTTLE "
                "verdict_stream=post_l12_pre_v11 verdict=NO_TRADE direction=BUY "
                "status=skipped reason=non_execute_verdict source_verdict=NO_TRADE"
            ),
        }
    )

    assert event is not None
    assert event.symbol == "AUDUSD"
    assert event.event_type == "PRESSURE_CANARY"
    assert event.verdict == "NO_TRADE"
    assert event.direction == "BUY"
    assert event.effective_action == "OBSERVE"
    assert event.is_downgraded is False


def test_parse_downgraded_hold_preserves_raw_verdict_and_effective_action():
    event = parse_engine_log_event(
        {
            "timestamp": "2026-05-08T12:00:00Z",
            "severity": "info",
            "message": (
                "[SignalThrottle] GBPCAD THROTTLED - verdict EXECUTE_REDUCED_RISK_BUY "
                "downgraded to HOLD (count=3, remaining=0)"
            ),
        }
    )

    assert event is not None
    assert event.symbol == "GBPCAD"
    assert event.raw_verdict == "EXECUTE_REDUCED_RISK_BUY"
    assert event.direction == "BUY"
    assert event.effective_action == "HOLD"
    assert event.is_downgraded is True


def test_csv_fixture_reports_data_quality_without_large_raw_export():
    report = analyze_signal_throttle_csv(_FIXTURE)

    assert report["data_quality"] == {
        "source": "csv",
        "file_found": True,
        "process_local": False,
        "global_aggregation": False,
        "row_count": 3,
        "parsed_signal_count": 3,
        "unparsed_count": 0,
        "start_utc": "2026-05-08T12:00:00+00:00",
        "end_utc": "2026-05-08T12:00:20+00:00",
        "timezone_assumption": "UTC",
        "state_warmup": True,
        "first_event_is_continuation": True,
        "state_warmup_reason": "window_count_started_nonzero",
        "first_event_state": {
            "symbol": "XAUUSD",
            "timestamp_utc": "2026-05-08T12:00:00+00:00",
            "event_type": "THROTTLED",
            "count": 3,
            "remaining": None,
            "streak": None,
            "max_signals": 3,
            "window_seconds": 300.0,
            "suppressed": 0,
        },
    }


def test_csv_state_warmup_detects_first_intel_continuation(tmp_path):
    csv_path = tmp_path / "signal_throttle_with_intel.csv"
    rows = [
        {
            "timestamp": "2026-05-18T07:28:00Z",
            "severity": "info",
            "message": "[SignalThrottle] CADJPY allowed - verdict EXECUTE_BUY",
        },
        {
            "timestamp": "2026-05-18T07:28:00Z",
            "severity": "info",
            "message": (
                "[SignalThrottleIntel] symbol=CADJPY raw_direction=BUY final_direction=WAIT "
                "direction_status=CANARY_QUORUM_PENDING_VALIDATION phase=ALLOWED_CANARY_QUORUM "
                "action=WAIT_PRICE_THEME_STRUCTURE verdict=EXECUTE_BUY count=1 remaining=2 "
                "streak=10 max=3 window=300s reason=allowed_is_candidate_until_price_theme_structure_validation"
            ),
        },
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["message", "severity", "timestamp"])
        writer.writeheader()
        writer.writerows(rows)

    report = analyze_signal_throttle_csv(csv_path)

    assert report["data_quality"]["parsed_signal_count"] == 1
    assert report["state_warmup"] is True
    assert report["first_event_is_continuation"] is True
    assert report["state_warmup_reason"] == "streak_exceeds_window_count"
    assert report["first_event_state"] == {
        "symbol": "CADJPY",
        "timestamp_utc": "2026-05-18T07:28:00+00:00",
        "event_type": "ALLOWED",
        "count": 1,
        "remaining": 2,
        "streak": 10,
        "max_signals": 3,
        "window_seconds": 300.0,
        "suppressed": 0,
    }


def test_build_pressure_blocks_groups_same_symbol_until_gap_or_rotation():
    events = [
        _event(0, "GBPCAD"),
        _event(30, "GBPCAD"),
        _event(60, "GBPCAD"),
        _event(70, "EURCAD"),
        _event(90, "GBPCAD"),
    ]

    blocks = build_pressure_blocks(events, max_gap_seconds=75)

    assert [(block.symbol, block.events) for block in blocks] == [
        ("GBPCAD", 3),
        ("EURCAD", 1),
        ("GBPCAD", 1),
    ]


def test_same_second_pair_collision_does_not_break_primary_block():
    base = datetime(2026, 5, 8, 12, 0, 5, tzinfo=UTC)
    events = [
        SignalThrottleLogEvent(base + timedelta(milliseconds=100), "error", "", "GBPCAD", "THROTTLED"),
        SignalThrottleLogEvent(base + timedelta(milliseconds=200), "error", "", "EURCAD", "THROTTLED"),
        SignalThrottleLogEvent(base + timedelta(milliseconds=300), "error", "", "GBPCAD", "THROTTLED"),
    ]

    blocks = build_pressure_blocks(events, max_gap_seconds=75)

    assert [(block.symbol, block.events) for block in blocks] == [
        ("GBPCAD", 2),
        ("EURCAD", 1),
    ]


def test_analyzer_classifies_fragmented_latest_rotation_as_theme_alert():
    symbols = ["EURCAD", "GBPUSD", "CHFJPY", "NZDCAD", "GBPNZD", "GBPJPY"]
    events = [_event(index * 10, symbols[index % len(symbols)]) for index in range(120)]

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600)

    assert report["final_mode"] == "THEME_ALERT_AND_PAIR_SELECTION"
    assert report["clean_entry_signal"] is False
    assert report["pair_timing_candidate"] is False
    assert report["requires_market_context"] is True
    assert report["latest_phase"] == "BROAD_ROTATION_FRAGMENTED"
    assert report["recommended_action"] == "OUTPUT_THEME_ALERT_AND_WATCHLIST"
    assert report["watchlist"] == report["main_watchlist"]
    assert report["data_quality"]["source"] == "live_process"


def test_live_analyzer_empty_snapshot_keeps_runtime_config():
    analyzer = SignalThrottleLiveAnalyzer(retention_seconds=7200, max_events=20000)

    report = analyzer.snapshot()

    assert report["final_mode"] == "NO_SIGNAL_THROTTLE_DATA"
    assert report["counts"]["total_events"] == 0
    assert report["latest_window"]["event_count"] == 0
    assert report["data_quality"]["source"] == "live_process"
    assert report["data_quality"]["process_local"] is True
    assert report["runtime_config"]["retention_seconds"] == 7200
    assert report["runtime_config"]["max_events_in_memory"] == 20000


def test_theme_scores_split_dominant_secondary_and_noisy_themes():
    events = []
    for index in range(40):
        events.append(_event(index, "EURCAD", event_type="ALLOWED"))
    for index in range(40, 70):
        events.append(_event(index, "GBPJPY", event_type="ALLOWED"))
    for index in range(70, 80):
        events.append(_event(index, "NZDCHF", event_type="ALLOWED"))

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600)

    assert 1 <= len(report["dominant_themes"]) <= 5
    assert all(isinstance(item["score"], int) for item in report["theme_scores"])
    assert set(report["dominant_themes"][0]) >= {"theme", "score", "raw_pressure", "cross_events"}
    assert report["dominant_themes"][0]["theme"] in {"CAD_WEAKNESS", "EUR_STRENGTH"}


def test_analyzer_classifies_clean_same_pair_block_as_pair_candidate():
    events = [_event(index * 30, "GBPCAD") for index in range(12)]

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600)

    assert report["final_mode"] == "PAIR_SIGNAL_CANDIDATE"
    assert report["pair_timing_candidate"] is True
    assert report["clean_entry_signal"] is False
    assert report["requires_market_context"] is True
    assert report["latest_phase"] == "PAIR_TIMING_BLOCK"
    assert report["recommended_action"] == "FETCH_PRICE_PHASE_M15_H1_BEFORE_SIGNAL_OUTPUT"
    assert report["candidate"] == {
        "symbol": "GBPCAD",
        "block_start_utc": "2026-05-08T12:00:00+00:00",
        "block_end_utc": "2026-05-08T12:05:30+00:00",
        "valid_since_utc": "2026-05-08T12:05:00+00:00",
        "duration_minutes": 5.5,
        "density_per_minute": 2.18,
        "events": 12,
        "effective_ticks": 12,
        "suppressed_ticks": 0,
        "effective_density_per_minute": 2.18,
        "direction": None,
        "phase": "LOW_DENSITY_OPEN_LANE",
        "pressure_grade": "C",
        "pressure_temperature": "CONTEXTUAL_RADAR",
        "priority": "WATCH_LOW",
        "signal_status": "VALID_CONTEXTUAL_RADAR",
        "max_gap_health": "VERY_HEALTHY",
        "execution_status": "NO_DIRECT_ENTRY",
        "reason": "duration_or_events_present_but_density_is_contextual",
    }
    assert report["market_context_validation"]["direction_validated"] is False
    assert report["market_context_validation"]["requires_market_context"] is True


def test_live_analyzer_fragmented_rotation_returns_theme_alert():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    symbols = ["EURCAD", "GBPUSD", "CHFJPY", "NZDCAD", "GBPNZD", "GBPJPY"]
    for index in range(120):
        analyzer.record_throttled(symbol=symbols[index % len(symbols)], timestamp=base + timedelta(seconds=index * 10))

    report = analyzer.snapshot()

    assert report["final_mode"] == "THEME_ALERT_AND_PAIR_SELECTION"
    assert report["latest_phase"] == "BROAD_ROTATION_FRAGMENTED"
    assert report["clean_entry_signal"] is False
    assert report["pair_timing_candidate"] is False
    assert report["requires_market_context"] is True


def test_live_analyzer_same_pair_5m_returns_pair_timing_candidate():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for index in range(12):
        analyzer.record_throttled(symbol="GBPCAD", timestamp=base + timedelta(seconds=index * 30))

    report = analyzer.snapshot()

    assert report["final_mode"] == "PAIR_SIGNAL_CANDIDATE"
    assert report["latest_phase"] == "PAIR_TIMING_BLOCK"
    assert report["pair_timing_candidate"] is True
    assert report["clean_entry_signal"] is False
    assert report["candidate"]["symbol"] == "GBPCAD"


def test_live_analyzer_downgraded_hold_not_clean_entry():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)

    analyzer.record_throttled(
        symbol="GBPCAD",
        verdict="EXECUTE_REDUCED_RISK_BUY",
        count=3,
        remaining=0,
        max_signals=3,
        window_seconds=300,
    )
    report = analyzer.snapshot()

    assert report["event_counts"] == {"allowed": 0, "throttled": 1, "downgraded_to_hold": 1}
    assert report["clean_entry_signal"] is False
    assert report["requires_market_context"] is True


def test_live_analyzer_allowed_quorum_ignores_error_between_info_events():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)

    analyzer.record_allowed(symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base)
    analyzer.record_throttled(symbol="EURCAD", timestamp=base + timedelta(seconds=1))
    analyzer.record_allowed(symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=2))
    analyzer.record_allowed(symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=3))
    report = analyzer.snapshot()

    assert report["allowed_quorum"] == {
        "symbol": "GBPCAD",
        "direction": "BUY",
        "streak": 3,
        "quorum_size": 3,
        "quorum_reached": True,
    }


def test_short_allowed_quorum_trend_continuation_does_not_emit_signal_payload():
    events = [_event(index * 2, "USDCAD", event_type="ALLOWED") for index in range(11)]
    market = MarketContext(
        symbol="USDCAD",
        raw_allowed_direction="BUY",
        pip_value=0.0001,
        price_at_signal_start=1.37560,
        price_at_5m_confirm=1.375675,
        price_at_signal_end=1.375675,
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        theme_aligned=True,
        spread_normal=True,
        price_position="MID_RANGE",
        main_support=1.3720,
        main_resistance=1.3850,
        minor_resistance=1.3785,
        tp1_resistance=1.3785,
        tp2_resistance=1.3810,
        tp3_resistance=1.3850,
    )

    report = analyze_signal_throttle_events(events, market_contexts={"USDCAD": market})
    continuation = report["microboost_continuation_entry"]

    assert continuation["status"] == "NONE"
    assert continuation["final_direction"] == "WAIT"
    assert continuation["action"] == "WAIT_SIGNAL_THROTTLE_CLEAN_BLOCK"


def test_one_minute_allowed_quorum_trend_continuation_waits_for_clean_throttle_block():
    events = [_event(index * 2, "USDCAD", event_type="ALLOWED") for index in range(32)]
    market = MarketContext(
        symbol="USDCAD",
        raw_allowed_direction="BUY",
        pip_value=0.0001,
        price_at_signal_start=1.37560,
        price_at_5m_confirm=1.375675,
        price_at_signal_end=1.375675,
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        theme_aligned=True,
        spread_normal=True,
        price_position="MID_RANGE",
        main_support=1.3720,
        main_resistance=1.3850,
        minor_resistance=1.3785,
        tp1_resistance=1.3785,
        tp2_resistance=1.3810,
        tp3_resistance=1.3850,
    )

    report = analyze_signal_throttle_events(events, market_contexts={"USDCAD": market})
    continuation = report["microboost_continuation_entry"]

    assert continuation["status"] == "NONE"
    assert continuation["final_direction"] == "WAIT"
    assert continuation["action"] == "WAIT_SIGNAL_THROTTLE_CLEAN_BLOCK"
    assert continuation["reason"] == "SIGNAL_THROTTLE_CLEAN_BLOCK_REQUIRED"
    assert report["signal_watch_gate"]["eligible"] is False


def test_clean_throttle_block_allows_later_microboost_validation_for_same_pair():
    events = [_event(index * 30, "USDCAD", event_type="ALLOWED") for index in range(11)]
    events.extend(_event(390 + index * 2, "USDCAD", event_type="ALLOWED") for index in range(32))
    market = MarketContext(
        symbol="USDCAD",
        raw_allowed_direction="BUY",
        pip_value=0.0001,
        price_at_signal_start=1.37560,
        price_at_5m_confirm=1.375675,
        price_at_signal_end=1.375675,
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        theme_aligned=True,
        spread_normal=True,
        price_position="MID_RANGE",
        main_support=1.3720,
        main_resistance=1.3850,
        minor_resistance=1.3785,
        tp1_resistance=1.3785,
        tp2_resistance=1.3810,
        tp3_resistance=1.3850,
    )

    report = analyze_signal_throttle_events(events, market_contexts={"USDCAD": market})
    continuation = report["microboost_continuation_entry"]

    assert report["signal_watch_gate"]["eligible"] is True
    assert report["signal_watch_gate"]["source"] == "SIGNAL_THROTTLE_CLEAN_BLOCK"
    assert continuation["status"] == "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION"
    assert continuation["source_clean_block_confirmed"] is True
    assert continuation["microboost_validation_status"] == "PASSED"
    assert continuation["target_mode"] == "FINAL_MARKET_STRUCTURE"


def test_clean_throttle_block_then_resistance_microboost_creates_watch_before_any_final():
    events = [_event(index * 30, "GBPCAD", event_type="ALLOWED") for index in range(11)]
    events.extend(_event(390 + index * 4, "GBPCAD", event_type="ALLOWED") for index in range(46))
    market = MarketContext(
        symbol="GBPCAD",
        raw_allowed_direction="BUY",
        pip_value=0.0001,
        price_at_signal_start=1.8636,
        price_at_5m_confirm=1.8636,
        price_at_signal_end=1.8636,
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        theme_aligned=True,
        spread_normal=True,
        price_position="MAIN_RESISTANCE",
        main_resistance=1.8650,
        resistance_low=1.8636,
        resistance_high=1.8650,
        minor_support=1.8624,
        major_support=1.8616,
        m15_close_above_resistance=True,
        tp1_support=1.8600,
        tp2_support=1.8580,
        tp3_support=1.8560,
        support_ladder_ready=True,
    )

    report = analyze_signal_throttle_events(events, market_contexts={"GBPCAD": market})
    watch = report["microboost_counter_entry"]

    assert report["signal_watch_gate"]["eligible"] is True
    assert watch["status"] == "SELL_ABSORPTION_WATCH"
    assert watch["final_direction"] == "WAIT"
    assert watch["validated_direction"] is None
    assert watch["watch_direction"] == "SELL"
    assert watch["direction_validation_status"] == "WATCH_ONLY_PENDING_M15"
    assert watch["valid_for_execution"] is False
    assert watch["requires_m15_close"] is True
    assert watch["targets_execution_usable"] is False
    assert watch["pattern_match_score"] >= watch["pattern_score"]
    assert watch["source_clean_block_confirmed"] is True
    assert watch["microboost_validation_status"] == "PASSED"
    assert report["microboost_watch_entry"] is None


def test_live_analyzer_same_second_batch_not_hard_interrupt():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)
    base = datetime(2026, 5, 8, 12, 0, 5, tzinfo=UTC)

    analyzer.record_throttled(symbol="GBPCAD", timestamp=base + timedelta(milliseconds=100))
    analyzer.record_throttled(symbol="EURCAD", timestamp=base + timedelta(milliseconds=200))
    analyzer.record_throttled(symbol="GBPCAD", timestamp=base + timedelta(milliseconds=300))
    report = analyzer.snapshot()

    block = next(item for item in report["top_clean_blocks"] if item["symbol"] == "GBPCAD")
    assert block["events"] == 2


def test_live_analyzer_microboost_cluster_added_to_watchlist():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for index in range(30):
        analyzer.record_allowed(symbol="NZDJPY", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5))

    report = analyzer.snapshot()

    assert report["main_watchlist"][0] == "NZDJPY"
    assert report["top_microboost"][0]["symbol"] == "NZDJPY"
    assert report["top_microboost"][0]["direction"] == "BUY"


def test_microboost_summary_classifies_dense_unpriced_cluster():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for index in range(30):
        analyzer.record_allowed(symbol="NZDJPY", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5))

    report = analyzer.snapshot()
    summary = report["microboost_summary"]

    assert summary["enabled"] is True
    assert summary["count_total"] == 1
    assert summary["count_by_phase"] == {"DENSE_MICROBOOST": 1}
    assert summary["top_symbols"] == ["NZDJPY"]
    assert summary["latest"]["phase_unpriced"] == "DENSE_MICROBOOST"
    assert summary["latest"]["phase_priced"] is None
    assert summary["latest"]["late_pressure_candidate"] is True
    assert summary["latest"]["requires_market_context"] is True
    assert summary["latest"]["action"] == "VALIDATE_PRICE_THEME_STRUCTURE"
    assert summary["reason"] == "dense_pressure_seen_but_late_pressure_requires_price_context"
    assert report["microboost_watch_entry"] is None


def test_microboost_counts_suppressed_logs_as_effective_ticks():
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    rows = [
        {
            "timestamp": (base + timedelta(seconds=index * 30)).isoformat(),
            "severity": "error",
            "message": (
                "[SignalThrottle] CADJPY THROTTLED - verdict EXECUTE_BUY 1 signals in last 300s (max 1) suppressed=2"
            ),
        }
        for index in range(4)
    ]
    events = parse_signal_throttle_rows(rows)

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600, microboost_window_minutes=15)
    summary = report["microboost_summary"]

    assert report["top_microboost"][0]["events"] == 4
    assert report["top_microboost"][0]["effective_ticks"] == 12
    assert report["top_microboost"][0]["suppressed_ticks"] == 8
    assert report["top_microboost"][0]["effective_density_per_minute"] == 8.0
    assert summary["count_total"] == 1
    assert summary["latest"]["event_count"] == 4
    assert summary["latest"]["effective_tick_count"] == 12
    assert summary["latest"]["suppressed_tick_count"] == 8
    assert summary["latest"]["effective_density_per_minute"] == 8.0
    assert summary["latest"]["phase_unpriced"] == "DENSE_MICROBOOST"
    assert summary["latest"]["direction"] == "BUY"


def test_theme_scores_fill_real_alignment_snapshot_for_microboost_context():
    events = [_event(index * 5, "USDCAD", event_type="ALLOWED") for index in range(30)]
    market = MarketContext(
        symbol="USDCAD",
        raw_allowed_direction="BUY",
        pip_value=0.0001,
        price_at_signal_start=1.37560,
        price_at_5m_confirm=1.37570,
        price_at_signal_end=1.37580,
        m15_phase="PIVOT_RECLAIM",
        h1_phase="BULLISH",
        theme_aligned=True,
        spread_normal=True,
        price_position="MID_RANGE",
        main_support=1.3720,
        main_resistance=1.3850,
        range_position=0.35,
    )

    report = analyze_signal_throttle_events(events, market_contexts={"USDCAD": market})
    latest = report["microboost_summary"]["latest"]

    assert latest["market_context_snapshot"]["theme_alignment"].endswith("_SUPPORTS_BUY")
    assert latest["theme_alignment_status"] != "NOT_AVAILABLE"
    assert "THEME_SNAPSHOT_NOT_AVAILABLE" not in (latest["pattern_bottlenecks"] or [])


def test_candidate_lifecycle_keeps_mature_pair_when_latest_isolated_ignition_arrives():
    base = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    def pressure_block(
        *,
        start_minutes: float,
        duration_minutes: float,
        symbol: str,
        direction: str,
        rows: int,
        suppressed: int,
    ) -> list[SignalThrottleLogEvent]:
        start = base + timedelta(minutes=start_minutes)
        spacing = duration_minutes * 60.0 / max(rows - 1, 1)
        return [
            SignalThrottleLogEvent(
                timestamp=start + timedelta(seconds=index * spacing),
                severity="info",
                message=f"[SignalThrottle] {symbol} allowed - verdict EXECUTE_{direction}",
                symbol=symbol,
                event_type="ALLOWED",
                verdict=f"EXECUTE_{direction}",
                direction=direction,
                suppressed=suppressed,
            )
            for index in range(rows)
        ]

    events: list[SignalThrottleLogEvent] = []
    events.extend(
        pressure_block(
            start_minutes=0,
            duration_minutes=14.8,
            symbol="GBPAUD",
            direction="SELL",
            rows=10,
            suppressed=11,
        )
    )
    events.extend(
        pressure_block(
            start_minutes=75,
            duration_minutes=44.5,
            symbol="USDCAD",
            direction="BUY",
            rows=20,
            suppressed=27,
        )
    )
    events.extend(
        pressure_block(
            start_minutes=180,
            duration_minutes=5.8,
            symbol="GBPNZD",
            direction="BUY",
            rows=10,
            suppressed=6,
        )
    )
    events.extend(
        pressure_block(
            start_minutes=201,
            duration_minutes=15.1,
            symbol="GBPCAD",
            direction="BUY",
            rows=20,
            suppressed=6,
        )
    )
    events.extend(
        pressure_block(
            start_minutes=330,
            duration_minutes=1.84,
            symbol="CADCHF",
            direction="BUY",
            rows=7,
            suppressed=3,
        )
    )

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600)

    assert report["latest_phase"] == "LOW_ACTIVITY"
    assert report["final_mode"] == "PAIR_SIGNAL_CANDIDATE_WITH_LATEST_IGNITION"
    assert report["candidate"]["symbol"] == "GBPCAD"
    assert report["active_candidate"] == "GBPCAD"
    assert report["latest_meaningful_candidate"] == "GBPCAD"
    assert report["latest_ignition_watch"] == "CADCHF"
    assert report["previous_major_leader"] == "USDCAD"
    assert report["secondary_candidate"] == "GBPNZD"
    assert report["counter_rotation"] == "GBPAUD_SELL"
    assert report["historical_leader"] == "USDCAD"
    assert report["main_watchlist"][:4] == ["GBPCAD", "CADCHF", "USDCAD", "GBPNZD"]
    assert report["market_context_validation"]["symbol"] == "GBPCAD"
    assert report["market_context_validation"]["raw_allowed_direction"] == "BUY"
    assert report["recommended_action"] == "FETCH_GBPCAD_PRICE_CONTEXT_M15_H1_BEFORE_SIGNAL_OUTPUT"
    assert report["candidate_lifecycle"]["reason"] == (
        "latest_isolated_ignition_does_not_replace_latest_meaningful_candidate"
    )


def test_microboost_summary_detects_strong_cluster_near_timing_gate_without_clean_entry():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for index in range(25):
        analyzer.record_allowed(symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 7.5))

    report = analyzer.snapshot()
    summary = report["microboost_summary"]

    assert report["clean_entry_signal"] is False
    assert report["requires_market_context"] is True
    assert summary["timing_gate_5m"] is False
    assert summary["latest"]["phase_unpriced"] == "NEAR_TIMING_GATE_MICROBOOST"
    assert summary["latest"]["phase_priced"] is None
    assert summary["action"] == "FETCH_MARKET_CONTEXT_FOR_TIMING_GATE"


def test_microboost_summary_counts_recurrence_by_symbol():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for offset in [0, 5, 10, 15, 20, 140, 145, 150, 155, 160]:
        analyzer.record_allowed(symbol="AUDCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=offset))

    summary = analyzer.snapshot()["microboost_summary"]

    assert summary["count_total"] == 2
    assert summary["count_by_symbol"] == {"AUDCAD": 2}
    assert summary["count_by_phase"] == {"REPEATED_MICROBOOST": 2}
    assert summary["latest"]["phase_unpriced"] == "REPEATED_MICROBOOST"
    assert summary["latest"]["phase_priced"] is None
    assert summary["latest"]["score_components"]["recurrence_score"] == 5


def test_microboost_priced_phase_confirms_continuation_when_context_aligns():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for index in range(30):
        analyzer.record_allowed(symbol="NZDJPY", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5))

    report = analyzer.snapshot(
        market_contexts={
            "NZDJPY": MarketContext(
                symbol="NZDJPY",
                raw_allowed_direction="BUY",
                price_at_signal_start=91.000,
                price_at_5m_confirm=91.040,
                price_at_signal_end=91.080,
                m15_phase="PIVOT_RECLAIM",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                price_position="MID_RANGE",
            )
        }
    )
    latest = report["microboost_summary"]["latest"]

    assert report["microboost_summary"]["market_context_applied"] is True
    assert latest["phase_unpriced"] == "DENSE_MICROBOOST"
    assert latest["phase_priced"] == "CONTINUATION_MICROBOOST"
    assert latest["action"] == "VALIDATE_RETEST_OR_HOLD"
    assert latest["requires_market_context"] is False
    assert latest["market_context_validation"]["final_direction"] == "BUY"
    assert latest["market_context_snapshot"]["price_at_signal_start"] == 91.0
    assert latest["market_context_snapshot"]["price_at_5m_confirm"] == 91.04
    assert latest["market_context_snapshot"]["price_at_signal_end"] == 91.08
    assert latest["market_context_snapshot"]["m15_phase"] == "PIVOT_RECLAIM"
    assert latest["market_context_snapshot"]["h1_phase"] == "BULLISH"


def test_microboost_late_pressure_requires_price_context_before_protect_action():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    for index in range(30):
        analyzer.record_allowed(symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5))

    unpriced = analyzer.snapshot()["microboost_summary"]["latest"]
    priced_report = analyzer.snapshot(
        market_contexts={
            "GBPCAD": MarketContext(
                symbol="GBPCAD",
                raw_allowed_direction="BUY",
                price_at_signal_start=1.8500,
                price_at_5m_confirm=1.8550,
                price_at_signal_end=1.8585,
                m15_phase="PIVOT_RECLAIM",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
            )
        }
    )
    priced = priced_report["microboost_summary"]["latest"]

    assert unpriced["late_pressure_candidate"] is True
    assert unpriced["phase_priced"] is None
    assert unpriced["action"] == "VALIDATE_PRICE_THEME_STRUCTURE"
    assert priced["phase_priced"] == "LATE_DENSE_PRESSURE"
    assert priced["action"] == "PROTECT_PROFIT"
    assert priced["score_components"]["late_risk_penalty"] == -24
    assert priced["market_context_validation"]["final_direction"] == "NO_NEW_ENTRY"
    assert priced_report["microboost_summary"]["action"] == "PROTECT_PROFIT"


def test_microboost_buy_at_main_resistance_becomes_exhaustion_warning():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 9, 9, 36, tzinfo=UTC)
    for index in range(29):
        analyzer.record_allowed(
            symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5.32)
        )

    report = analyzer.snapshot(
        market_contexts={
            "GBPCAD": MarketContext(
                symbol="GBPCAD",
                raw_allowed_direction="BUY",
                price_at_signal_start=1.8500,
                price_at_5m_confirm=1.8550,
                price_at_signal_end=1.8580,
                m15_phase="PIVOT_RECLAIM",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                market_bias="BUY",
                trend_direction="BUY",
                price_position="MAIN_RESISTANCE",
                main_support=1.8320,
                main_resistance=1.8585,
                range_position=0.98,
            )
        }
    )
    latest = report["microboost_summary"]["latest"]

    assert latest["phase_unpriced"] == "DENSE_MICROBOOST"
    assert latest["phase_priced"] == "EXHAUSTION_AT_RESISTANCE"
    assert latest["action"] == "NO_NEW_BUY_WAIT_SELL_OR_PULLBACK_CONFIRMATION"
    assert latest["price_position"] == "MAIN_RESISTANCE"
    assert latest["trend_direction"] == "BUY"
    assert latest["score_components"]["late_risk_penalty"] == -24


def test_downgraded_live_events_can_refresh_signal_watch_candidate():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 9, 9, 36, tzinfo=UTC)
    for index in range(80):
        analyzer.record_downgraded(
            symbol="GBPCAD",
            verdict="EXECUTE_BUY",
            direction="BUY",
            reason="market_context_unvalidated",
            timestamp=base + timedelta(seconds=index * 4.0),
        )

    report = analyzer.snapshot(
        market_contexts={
            "GBPCAD": MarketContext(
                symbol="GBPCAD",
                raw_allowed_direction="BUY",
                price_at_signal_start=1.8636,
                price_at_5m_confirm=1.8636,
                price_at_signal_end=1.8636,
                m15_phase="PIVOT_RECLAIM",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                market_bias="BUY",
                trend_direction="BUY",
                price_position="MAIN_RESISTANCE",
                main_support=1.8320,
                main_resistance=1.8650,
                resistance_low=1.8636,
                resistance_high=1.8650,
                minor_support=1.8624,
                major_support=1.8616,
                tp1_support=1.8600,
                tp2_support=1.8580,
                tp3_support=1.8560,
                support_ladder_ready=True,
                range_position=0.98,
            )
        }
    )
    watch = report["microboost_counter_entry"]

    assert report["event_counts"]["downgraded_to_hold"] == 80
    assert report["signal_watch_gate"]["eligible"] is True
    assert watch["market_context_applied"] is True
    assert watch["status"].endswith("_WATCH")
    assert watch["final_direction"] == "WAIT"


def test_microboost_buy_at_main_support_becomes_bounce_candidate():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 9, 9, 36, tzinfo=UTC)
    for index in range(29):
        analyzer.record_allowed(
            symbol="GBPCAD", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5.32)
        )

    report = analyzer.snapshot(
        market_contexts={
            "GBPCAD": MarketContext(
                symbol="GBPCAD",
                raw_allowed_direction="BUY",
                price_at_signal_start=1.8340,
                price_at_5m_confirm=1.8355,
                price_at_signal_end=1.8360,
                m15_phase="SUPPORT_HOLD",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                market_bias="BUY",
                trend_direction="BUY",
                price_position="MAIN_SUPPORT",
                main_support=1.8320,
                main_resistance=1.8585,
                range_position=0.15,
            )
        }
    )
    latest = report["microboost_summary"]["latest"]

    assert latest["phase_priced"] == "SUPPORT_BOUNCE_MICROBOOST"
    assert latest["action"] == "BUY_ON_RECLAIM_CONFIRMATION"
    assert latest["price_position"] == "MAIN_SUPPORT"


def test_microboost_buy_pressure_inside_m15_bearish_pullback_waits_for_reclaim():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 18, 13, 30, tzinfo=UTC)
    for index in range(29):
        analyzer.record_allowed(
            symbol="CADJPY", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5.32)
        )

    report = analyzer.snapshot(
        market_contexts={
            "CADJPY": MarketContext(
                symbol="CADJPY",
                raw_allowed_direction="BUY",
                price_at_signal_start=115.5605,
                price_at_5m_confirm=115.5290,
                price_at_signal_end=115.5235,
                m15_phase="BEARISH_PULLBACK",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                market_bias="BUY",
                trend_direction="BUY",
                price_position="MID_RANGE",
                main_support=115.10,
                main_resistance=115.90,
                range_position=0.52,
            )
        }
    )
    latest = report["microboost_summary"]["latest"]
    lifecycle = report["microboost_summary"]["microboost_lifecycle"]
    watch = report["microboost_watch_entry"]

    assert report["microboost_summary"]["market_context_applied"] is True
    assert latest["phase_priced"] == "BULLISH_PULLBACK_MICROBOOST"
    assert latest["action"] == "WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION"
    assert latest["cluster_stage"] == "pullback_validation"
    assert latest["cluster_id"].startswith("CADJPY_20260518T133000")
    assert lifecycle["cluster_count"] == 1
    assert lifecycle["raw_rows"] == 29
    assert lifecycle["dedup_required"] is True
    assert watch["status"] == "MICROBOOST_WATCH"
    assert watch["final_direction"] == "WAIT"
    assert watch["watch_direction"] == "BUY"
    assert watch["market_context_applied"] is True
    assert watch["valid_for_execution"] is False
    assert build_signal_json_event(watch) is not None


def test_microboost_context_without_price_position_is_not_marked_applied():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 18, 13, 30, tzinfo=UTC)
    for index in range(29):
        analyzer.record_allowed(
            symbol="CADJPY", verdict="EXECUTE_BUY", timestamp=base + timedelta(seconds=index * 5.32)
        )

    report = analyzer.snapshot(
        market_contexts={
            "CADJPY": MarketContext(
                symbol="CADJPY",
                raw_allowed_direction="BUY",
                price_at_signal_start=115.5000,
                price_at_5m_confirm=115.5300,
                price_at_signal_end=115.5600,
                m15_phase="BULLISH_PULLBACK",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                market_bias="BUY",
                trend_direction="BUY",
            )
        }
    )
    latest = report["microboost_summary"]["latest"]

    assert latest["phase_priced"] == "TREND_CONTINUATION_MICROBOOST"
    assert latest["market_context_snapshot"]["price_position"] is None
    assert report["microboost_summary"]["market_context_applied"] is False


def test_microboost_counter_to_running_trend_is_pullback_until_structure_break():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, microboost_window_minutes=15)
    base = datetime(2026, 5, 8, 9, 9, 36, tzinfo=UTC)
    for index in range(29):
        analyzer.record_allowed(
            symbol="GBPCAD", verdict="EXECUTE_SELL", timestamp=base + timedelta(seconds=index * 5.32)
        )

    report = analyzer.snapshot(
        market_contexts={
            "GBPCAD": MarketContext(
                symbol="GBPCAD",
                raw_allowed_direction="SELL",
                price_at_signal_start=1.8460,
                price_at_5m_confirm=1.8445,
                price_at_signal_end=1.8440,
                m15_phase="BEARISH_PULLBACK",
                h1_phase="BULLISH",
                theme_aligned=True,
                spread_normal=True,
                market_bias="BUY",
                trend_direction="BUY",
                price_position="MID_RANGE",
                main_support=1.8320,
                main_resistance=1.8585,
                range_position=0.48,
            )
        }
    )
    latest = report["microboost_summary"]["latest"]

    assert latest["phase_priced"] == "MINOR_PULLBACK_MICROBOOST"
    assert latest["action"] == "WAIT_PULLBACK_COMPLETION"
    assert latest["price_position"] == "MID_RANGE"


def test_live_analyzer_requires_market_context_without_prices():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)
    analyzer.record_allowed(symbol="EURCAD", verdict="EXECUTE_BUY")

    report = analyzer.snapshot()

    assert report["requires_market_context"] is True
    assert report["clean_entry_signal"] is False


def test_live_analyzer_memory_window_prunes_old_events():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600, retention_seconds=75, max_events=3)
    base = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)

    analyzer.record_throttled(symbol="EURCAD", timestamp=base)
    analyzer.record_throttled(symbol="GBPJPY", timestamp=base + timedelta(seconds=10))
    analyzer.record_throttled(symbol="GBPCAD", timestamp=base + timedelta(seconds=70))
    analyzer.record_throttled(symbol="NZDJPY", timestamp=base + timedelta(seconds=80))
    report = analyzer.snapshot()

    assert report["counts"]["total_events"] == 3
    assert "EURCAD" not in report["counts"]["pairs"]


def test_live_analyzer_records_engine_events_without_csv():
    analyzer = SignalThrottleLiveAnalyzer(latest_window_seconds=3600)

    analyzer.record_allowed(symbol="GBPCAD", verdict="EXECUTE_BUY")
    analyzer.record_throttled(
        symbol="GBPCAD",
        verdict="EXECUTE_BUY",
        count=3,
        remaining=0,
        max_signals=3,
        window_seconds=300,
    )
    report = analyzer.snapshot()

    assert report["counts"]["total_events"] == 3
    assert report["counts"]["severity"] == {"info": 2, "error": 1}
    assert report["counts"]["verdicts"] == {"EXECUTE_BUY": 2}
    assert report["main_watchlist"] == ["GBPCAD"]
    assert report["event_counts"] == {"allowed": 1, "throttled": 1, "downgraded_to_hold": 1}
    assert report["data_quality"]["source"] == "live_process"
    assert report["data_quality"]["process_local"] is True
    assert report["data_quality"]["global_aggregation"] is False
    assert report["market_context_validation"]["symbol"] == "GBPCAD"


def test_currency_pressure_counts_usd_quote_on_metals():
    events = [
        SignalThrottleLogEvent(
            timestamp=datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
            severity="info",
            message="[SignalThrottle] XAUUSD allowed - verdict EXECUTE_BUY",
            symbol="XAUUSD",
            event_type="ALLOWED",
            verdict="EXECUTE_BUY",
            direction="BUY",
        ),
        SignalThrottleLogEvent(
            timestamp=datetime(2026, 5, 8, 12, 1, tzinfo=UTC),
            severity="info",
            message="[SignalThrottle] EURUSD allowed - verdict EXECUTE_BUY",
            symbol="EURUSD",
            event_type="ALLOWED",
            verdict="EXECUTE_BUY",
            direction="BUY",
        ),
    ]

    pressure = compute_currency_pressure(events)

    assert pressure["EUR"] == 1
    assert pressure["USD"] == -2
