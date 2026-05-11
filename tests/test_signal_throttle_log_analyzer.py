from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.market_context_validator import MarketContext
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
            "message": "[SignalThrottle] XAUUSD THROTTLED - 3 signals in last 300s (max 3)",
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
        "direction": None,
        "phase": "LOW_DENSITY_OPEN_LANE",
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

    summary = analyzer.snapshot()["microboost_summary"]

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


def test_live_report_requires_market_context_without_prices():
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
