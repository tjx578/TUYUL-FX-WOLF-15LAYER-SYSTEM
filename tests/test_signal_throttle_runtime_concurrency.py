from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer, SignalThrottleLogEvent
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population

START = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)


def _recorded_events(count: int) -> tuple[SignalThrottleLogEvent, ...]:
    analyzer = SignalThrottleLiveAnalyzer(
        retention_seconds=7200,
        max_events=count + 100,
    )
    events = tuple(
        SignalThrottleLogEvent(
            timestamp=START + timedelta(milliseconds=index),
            severity="warning",
            message="raw",
            symbol="EURUSD",
            event_type="ALLOWED",
            verdict="EXECUTE_BUY",
            direction="BUY",
            pressure_source="SignalThrottle",
            source_stream="ALLOWED",
            deployment_id="deployment-A",
            eligible_for_pressure_block=True,
            eligible_for_execution=False,
        )
        for index in range(count)
    )
    with ThreadPoolExecutor(max_workers=32) as executor:
        tuple(executor.map(analyzer._record_runtime_event, events))
    with analyzer._lock:
        return tuple(analyzer._events)


def test_concurrent_scanner_metadata_is_lossless_and_deterministic_at_10k() -> None:
    first = _recorded_events(10_000)
    second = _recorded_events(10_000)

    assert len(first) == 10_000
    assert len(second) == 10_000
    assert all(event.scanner_cycle_id for event in first)
    assert all(event.observed_cycle_index == 1 for event in first)

    first_population = build_raw_admission_population(first)
    second_population = build_raw_admission_population(second)
    assert len(first_population.events) == 10_000
    assert len(first_population.blocks) == 1
    assert first_population.blocks[0].source_event_ids == second_population.blocks[0].source_event_ids
    assert first_population.blocks[0].raw_block_id == second_population.blocks[0].raw_block_id
