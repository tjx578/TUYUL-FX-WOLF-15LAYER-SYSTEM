from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import (
    SignalThrottleLiveAnalyzer,
    SignalThrottleLogEvent,
    analyze_signal_throttle_events,
    build_pressure_blocks,
    compute_currency_pressure,
    parse_signal_throttle_rows,
)


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


def test_analyzer_classifies_fragmented_latest_rotation_as_theme_alert():
    symbols = ["EURCAD", "GBPUSD", "CHFJPY", "NZDCAD", "GBPNZD", "GBPJPY"]
    events = [_event(index * 10, symbols[index % len(symbols)]) for index in range(120)]

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600)

    assert report["final_mode"] == "THEME_ALERT_AND_PAIR_SELECTION"
    assert report["clean_entry_signal"] is False
    assert report["latest_phase"] == "BROAD_ROTATION_FRAGMENTED"
    assert report["recommended_action"] == "OUTPUT_THEME_ALERT_AND_WATCHLIST"


def test_analyzer_classifies_clean_same_pair_block_as_pair_candidate():
    events = [_event(index * 30, "GBPCAD") for index in range(12)]

    report = analyze_signal_throttle_events(events, latest_window_seconds=3600)

    assert report["final_mode"] == "PAIR_SIGNAL_CANDIDATE"
    assert report["clean_entry_signal"] is True
    assert report["latest_phase"] == "PAIR_TIMING_BLOCK"


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
