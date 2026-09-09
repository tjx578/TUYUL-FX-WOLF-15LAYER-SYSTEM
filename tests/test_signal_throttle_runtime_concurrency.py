from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from random import Random
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
    assert concurrent_events == tuple(sorted(concurrent_events, key=concurrent._canonical_event_key))
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


def _retention_facts(
    analyzer: SignalThrottleLiveAnalyzer,
    *,
    symbol: str = "EURUSD",
) -> dict[str, object]:
    with analyzer._lock:
        events = tuple(analyzer._events)
    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)
    blocks = [block for block in population.blocks if block.symbol == symbol]
    assert len(blocks) == 1
    block = blocks[0]
    evaluations = [
        evaluation for evaluation in audit.evaluations if evaluation["candidate_block_id"] == block.raw_block_id
    ]
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    grants = [grant for grant in audit.grants if grant.pair_admission_id == evaluation["pair_admission_id"]]
    assert len(grants) == 1
    grant = grants[0]
    return {
        "raw_block_id": block.raw_block_id,
        "pair_admission_id": grant.pair_admission_id,
        "logical_start": block.start,
        "logical_end": block.end,
        "finalization_event_id": block.finalization_event_id,
        "source_event_ids": block.source_event_ids,
        "source_event_count": evaluation["source_event_count"],
        "duration_at_finalization": evaluation["calculated_duration_seconds"],
        "raw_lineage_hash": evaluation["raw_lineage_hash"],
        "source_ledger_event_ids": tuple(evaluation["source_ledger_event_ids"]),
        "grant_source_ledger_hash": grant.source_ledger_hash,
        "evaluation": evaluation,
    }


def _retention_state(
    analyzer: SignalThrottleLiveAnalyzer,
) -> tuple[tuple[str, ...], tuple[datetime, datetime] | None]:
    with analyzer._lock:
        return (
            tuple(raw_signal_throttle_event_id(event) for event in analyzer._events),
            analyzer._retention_guard,
        )


def test_retention_never_truncates_a_finalized_raw_block_head() -> None:
    analyzer = SignalThrottleLiveAnalyzer(retention_seconds=800, max_events=100)
    for seconds in range(0, 701, 100):
        analyzer.record(_retention_event(seconds, "EURUSD"))
    analyzer.record(_retention_event(701, "GBPUSD"))

    first = _retention_facts(analyzer)

    # Advancing the cutoff into the middle of EURUSD must retain that complete
    # finalized block. Popping its head one event at a time changes both the
    # raw block identity and the logical PairAdmission identity. Multiple
    # cutoff shifts must preserve the canonical evidence, not just the IDs.
    for seconds in (900, 1000, 1200, 1499):
        analyzer.record(_retention_event(seconds, "GBPUSD"))
        assert _retention_facts(analyzer) == first

    # Once the cutoff passes the block end, the block is removed atomically;
    # no shortened suffix may survive and become a second logical grant.
    analyzer.record(_retention_event(1501, "GBPUSD"))
    with analyzer._lock:
        expired_events = tuple(analyzer._events)
    expired_population = build_raw_admission_population(expired_events)

    assert all(block.symbol != "EURUSD" for block in expired_population.blocks)


def test_retention_is_permutation_invariant_across_replay_and_restart() -> None:
    expired_outside_guard = _retention_event(-400, "USDJPY")
    source = [_retention_event(seconds, "EURUSD") for seconds in range(0, 701, 100)]
    source.insert(4, source[3])
    source.append(_retention_event(701, "GBPUSD"))

    shuffled_source = list(source)
    Random(405).shuffle(shuffled_source)
    analyzers = [SignalThrottleLiveAnalyzer(retention_seconds=800, max_events=100) for _ in range(3)]
    for analyzer, replay in zip(
        analyzers,
        (source, list(reversed(source)), shuffled_source),
        strict=True,
    ):
        for event in replay:
            analyzer.record(event)

    expected = _retention_facts(analyzers[0])
    expired_id = raw_signal_throttle_event_id(expired_outside_guard)
    for analyzer in analyzers:
        # Insert an already-expired row after every replay permutation has
        # reconstructed the same topology. It must be removed immediately,
        # even though its canonical location is the middle/front of the deque.
        analyzer.record(expired_outside_guard)
        retained_ids, _ = _retention_state(analyzer)
        assert expired_id not in retained_ids
        assert _retention_facts(analyzer) == expected

    for seconds in (900, 1000, 1200, 1499):
        for analyzer in analyzers:
            analyzer.record(_retention_event(seconds, "GBPUSD"))
        states = [_retention_state(analyzer) for analyzer in analyzers]
        assert states[0] == states[1] == states[2]
        assert states[0][1] is not None
        assert all(_retention_facts(analyzer) == expected for analyzer in analyzers)

    # Passing the protected block end expires it atomically for every replay
    # permutation. Equality cannot be satisfied merely by retaining stale rows.
    for analyzer in analyzers:
        analyzer.record(_retention_event(1501, "GBPUSD"))
    states = [_retention_state(analyzer) for analyzer in analyzers]
    assert states[0] == states[1] == states[2]
    for analyzer in analyzers:
        with analyzer._lock:
            population = build_raw_admission_population(tuple(analyzer._events))
        assert all(block.symbol != "EURUSD" for block in population.blocks)


def test_max_events_trims_chronological_oldest_for_reversed_replay() -> None:
    events = [_retention_event(seconds, "EURUSD") for seconds in range(10)]
    forward = SignalThrottleLiveAnalyzer(retention_seconds=1000, max_events=5)
    reverse = SignalThrottleLiveAnalyzer(retention_seconds=1000, max_events=5)

    for event in events:
        forward.record(event)
    for event in reversed(events):
        reverse.record(event)

    with forward._lock:
        forward_events = tuple(forward._events)
    with reverse._lock:
        reverse_events = tuple(reverse._events)
    expected = tuple(events[-5:])

    assert forward_events == reverse_events == expected
    assert [event.timestamp for event in reverse_events] == sorted(event.timestamp for event in reverse_events)


def test_concurrent_retention_matches_chronological_reference() -> None:
    events = tuple(_retention_event(index, "EURUSD" if index % 2 == 0 else "GBPJPY") for index in range(200))
    sequential = SignalThrottleLiveAnalyzer(retention_seconds=300, max_events=500)
    concurrent = SignalThrottleLiveAnalyzer(retention_seconds=300, max_events=500)

    for event in events:
        sequential.record(event)

    start = Event()

    def write(event: SignalThrottleLogEvent) -> None:
        start.wait()
        concurrent.record(event)

    with ThreadPoolExecutor(max_workers=32) as executor:
        writers = [executor.submit(write, event) for event in reversed(events)]
        start.set()
        for future in writers:
            future.result()

    # Apply one common post-batch watermark only after the complete event set
    # is present. Online retention cannot infer interruptions that have not
    # arrived yet; the next canonical runtime observation closes that window.
    watermark_event = _retention_event(399, "USDCHF")
    sequential.record(watermark_event)
    concurrent.record(watermark_event)

    with sequential._lock:
        sequential_events = tuple(sequential._events)
    with concurrent._lock:
        concurrent_events = tuple(concurrent._events)

    assert concurrent_events == sequential_events
    assert concurrent_events == tuple(sorted(concurrent_events, key=concurrent._canonical_event_key))
    assert concurrent_events[0].timestamp == START + timedelta(seconds=99)
    assert concurrent_events[-1].timestamp == START + timedelta(seconds=399)


def test_retention_does_not_merge_distinct_same_symbol_episodes() -> None:
    analyzer = SignalThrottleLiveAnalyzer(retention_seconds=800, max_events=100)
    for seconds in (0, 150, 300, 601, 751, 901):
        analyzer.record(_retention_event(seconds, "EURUSD"))
    analyzer.record(_retention_event(902, "GBPUSD"))

    with analyzer._lock:
        initial_events = tuple(analyzer._events)
    initial_population = build_raw_admission_population(initial_events)
    eurusd_blocks = [block for block in initial_population.blocks if block.symbol == "EURUSD"]
    assert len(eurusd_blocks) == 2
    first, second = eurusd_blocks
    assert first.raw_block_id != second.raw_block_id
    assert first.finalization_event_id == raw_signal_throttle_event_id(_retention_event(601, "EURUSD"))
    assert second.finalization_event_id == raw_signal_throttle_event_id(_retention_event(902, "GBPUSD"))

    # The first logical episode expires as a unit while the second remains
    # intact. The guard must not over-merge both EURUSD stories.
    analyzer.record(_retention_event(1201, "GBPUSD"))
    with analyzer._lock:
        retained_events = tuple(analyzer._events)
    retained_population = build_raw_admission_population(retained_events)
    retained_eurusd = [block for block in retained_population.blocks if block.symbol == "EURUSD"]
    assert len(retained_eurusd) == 1
    assert retained_eurusd[0] == second

    # After the second episode expires, a genuinely new same-symbol event
    # receives a new identity instead of reviving either finalized block.
    analyzer.record(_retention_event(1800, "GBPUSD"))
    analyzer.record(_retention_event(2101, "EURUSD"))
    with analyzer._lock:
        fresh_events = tuple(analyzer._events)
    fresh_population = build_raw_admission_population(fresh_events)
    fresh_eurusd = [block for block in fresh_population.blocks if block.symbol == "EURUSD"]
    assert len(fresh_eurusd) == 1
    assert fresh_eurusd[0].raw_block_id not in {first.raw_block_id, second.raw_block_id}
