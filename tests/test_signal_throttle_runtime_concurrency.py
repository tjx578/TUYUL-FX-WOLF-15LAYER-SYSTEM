from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer, SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import (
    build_raw_admission_population,
    raw_signal_throttle_event_id,
)

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


def _multi_symbol_event(index: int) -> SignalThrottleLogEvent:
    symbol = "EURUSD" if index % 2 == 0 else "GBPJPY"
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(milliseconds=index),
        severity="warning",
        message="raw",
        symbol=symbol,
        event_type="ALLOWED",
        verdict="EXECUTE_BUY",
        direction="BUY",
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="deployment-A",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
    )


def _canonical_events(events: tuple[SignalThrottleLogEvent, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            event.timestamp,
            event.symbol,
            event.scanner_cycle_id,
            event.scanner_epoch,
            event.observed_cycle_index,
            raw_signal_throttle_event_id(event),
        )
        for event in sorted(events, key=lambda item: (item.timestamp, item.symbol))
    )


def test_concurrent_multi_symbol_stream_matches_sequential_reference_at_10k() -> None:
    events = tuple(_multi_symbol_event(index) for index in range(10_000))
    sequential = SignalThrottleLiveAnalyzer(retention_seconds=7200, max_events=10_100)
    concurrent = SignalThrottleLiveAnalyzer(retention_seconds=7200, max_events=10_100)

    for event in events:
        sequential._record_runtime_event(event)

    # Seed the first observation of each symbol in canonical order. Subsequent
    # writer scheduling may vary, but cycle indexes and global event-time
    # ordering must remain identical to the sequential reference.
    concurrent._record_runtime_event(events[0])
    concurrent._record_runtime_event(events[1])
    start = Event()

    def write(event: SignalThrottleLogEvent) -> None:
        start.wait()
        concurrent._record_runtime_event(event)

    def read_snapshot() -> None:
        start.wait()
        concurrent.snapshot()

    with ThreadPoolExecutor(max_workers=32) as executor:
        readers = [executor.submit(read_snapshot) for _ in range(2)]
        writers = [executor.submit(write, event) for event in events[2:]]
        start.set()
        for future in writers + readers:
            future.result()

    with sequential._lock:
        sequential_events = tuple(sequential._events)
    with concurrent._lock:
        concurrent_events = tuple(concurrent._events)

    assert len(sequential_events) == len(concurrent_events) == 10_000
    assert _canonical_events(concurrent_events) == _canonical_events(sequential_events)
    assert {event.symbol: event.observed_cycle_index for event in concurrent_events[:2]} == {
        "EURUSD": 1,
        "GBPJPY": 2,
    }

    sequential_population = build_raw_admission_population(sequential_events)
    concurrent_population = build_raw_admission_population(concurrent_events)
    assert concurrent_population.duplicate_event_count == 0
    assert len(concurrent_population.events) == 10_000
    assert len(concurrent_population.blocks) == 10_000
    assert [block.symbol for block in concurrent_population.blocks] == [
        block.symbol for block in sequential_population.blocks
    ]
    assert [block.raw_block_id for block in concurrent_population.blocks] == [
        block.raw_block_id for block in sequential_population.blocks
    ]


def _retention_event(seconds: int, symbol: str) -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="warning",
        message="raw",
        symbol=symbol,
        event_type="ALLOWED",
        verdict="EXECUTE_BUY",
        direction="BUY",
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="deployment-A",
        scanner_cycle_id=f"cycle-{seconds}",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
    )


def test_retention_never_truncates_a_finalized_raw_block_head() -> None:
    analyzer = SignalThrottleLiveAnalyzer(retention_seconds=800, max_events=100)
    for seconds in range(0, 701, 100):
        analyzer.record(_retention_event(seconds, "EURUSD"))
    analyzer.record(_retention_event(701, "GBPUSD"))

    with analyzer._lock:
        first_events = tuple(analyzer._events)
    first_population = build_raw_admission_population(first_events)
    first_audit = build_pair_admission_audit(first_population.blocks, raw_events=first_population.events)
    first_block = first_population.blocks[0]
    first_grant = first_audit.grants[0]

    # Advancing the cutoff into the middle of EURUSD must retain that complete
    # finalized block. Popping its head one event at a time changes both the
    # raw block identity and the logical PairAdmission identity.
    analyzer.record(_retention_event(1000, "GBPUSD"))
    with analyzer._lock:
        retained_events = tuple(analyzer._events)
    retained_population = build_raw_admission_population(retained_events)
    retained_audit = build_pair_admission_audit(retained_population.blocks, raw_events=retained_population.events)
    retained_block = retained_population.blocks[0]
    retained_grant = retained_audit.grants[0]

    assert retained_block.source_event_ids == first_block.source_event_ids
    assert retained_block.raw_block_id == first_block.raw_block_id
    assert retained_grant.pair_admission_id == first_grant.pair_admission_id
    assert retained_audit.evaluations[0] == first_audit.evaluations[0]

    # Once the cutoff passes the block end, the block is removed atomically;
    # no shortened suffix may survive and become a second logical grant.
    analyzer.record(_retention_event(1502, "GBPUSD"))
    with analyzer._lock:
        expired_events = tuple(analyzer._events)
    expired_population = build_raw_admission_population(expired_events)

    assert all(block.symbol != "EURUSD" for block in expired_population.blocks)
