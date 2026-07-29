"""Acceptance rules for market-episode grouping (5scr.market-episode.v1).

Each test here corresponds to a locked acceptance criterion: transport churn
must not fork a market story, and a single opposite snapshot must not be
mistaken for a reversal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analysis.strategy_5scr_v3.episode_grouping import EpisodeEvent
from analysis.strategy_5scr_v3.episode_policy import MarketEpisodePolicyV1
from analysis.strategy_5scr_v3.episode_reducer import MarketEpisodeReducer

START = datetime(2026, 7, 17, 13, 0, 0, tzinfo=UTC)


def _event(
    index: int,
    *,
    symbol="CHFJPY",
    offset_seconds=0,
    direction="BUY",
    clean_block=None,
    watch=None,
    transport=None,
    cluster_suffix="",
    hard_reset=False,
    pressure_seen=True,
    microboost_transition=None,
    context_hash=None,
    pressure_event_count=3,
):
    at = START + timedelta(seconds=offset_seconds)
    return EpisodeEvent(
        pressure_event_id=f"evt-{symbol}-{index}{cluster_suffix}",
        symbol=symbol,
        event_time_utc=at,
        transport_lifecycle_id=transport or f"unresolved:{symbol}:{at.isoformat()}",
        raw_direction=direction,
        source_clean_block_id=clean_block,
        source_watch_id=watch,
        hard_context_reset=hard_reset,
        pressure_seen=pressure_seen,
        pressure_event_count=pressure_event_count,
        microboost_transition=microboost_transition,
        context_hash=context_hash,
    )


def _heartbeat(index, *, symbol="CHFJPY", offset_seconds=0):
    """Non-pressure telemetry: advances the event clock only."""
    at = START + timedelta(seconds=offset_seconds)
    return EpisodeEvent(
        pressure_event_id=f"hb-{symbol}-{index}",
        symbol=symbol,
        event_time_utc=at,
        transport_lifecycle_id=f"heartbeat:{symbol}:{at.isoformat()}",
        raw_direction=None,
        pressure_seen=False,
        pressure_event_count=0,
    )


def _reduce(events, *, max_gap_seconds=900):
    reducer = MarketEpisodeReducer(
        policy=MarketEpisodePolicyV1(max_continuity_gap_seconds=max_gap_seconds)
    )
    return reducer.ingest_many(events)


# --------------------------------------------------------------------------
# transport churn must not fork a market story
# --------------------------------------------------------------------------


def test_unique_transport_ids_still_form_one_episode():
    """The core fix: every event has its own transport id, yet one story."""
    events = [_event(i, offset_seconds=i * 60) for i in range(10)]
    result = _reduce(events)

    assert len(result.lifecycles) == 1
    assert len(result.links) == 10
    assert result.compression_ratio == pytest.approx(10.0)


def test_new_cluster_id_does_not_change_the_lifecycle():
    result = _reduce(
        [
            _event(1, cluster_suffix="-clusterA"),
            _event(2, offset_seconds=60, cluster_suffix="-clusterB"),
        ]
    )

    assert len(result.lifecycles) == 1


def test_new_deployment_does_not_change_the_lifecycle():
    """deployment_id is deliberately absent from identity."""
    result = _reduce(
        [
            _event(1, transport="deployment-a:lifecycle-1"),
            _event(2, offset_seconds=60, transport="deployment-b:lifecycle-2"),
        ]
    )

    assert len(result.lifecycles) == 1


def test_new_clean_block_attaches_instead_of_forking():
    result = _reduce(
        [
            _event(1, clean_block="CHFJPY_block_A"),
            _event(2, offset_seconds=120, clean_block="CHFJPY_block_B"),
        ]
    )

    assert len(result.lifecycles) == 1
    lifecycle = next(iter(result.lifecycles.values()))
    assert lifecycle.clean_block_count == 2


def test_canonical_anchors_are_preserved_on_the_link():
    result = _reduce([_event(1, clean_block="block-A", watch="watch-A")])
    link = result.links[0]

    assert link.source_clean_block_id == "block-A"
    assert link.source_watch_id == "watch-A"
    assert link.transport_lifecycle_id.startswith("unresolved:")


def test_duplicate_event_does_not_increment_event_count():
    duplicate = _event(1)
    result = _reduce([duplicate, duplicate, duplicate])

    lifecycle = next(iter(result.lifecycles.values()))
    assert lifecycle.event_count == 1
    assert result.duplicate_event_count == 2


# --------------------------------------------------------------------------
# episode boundaries
# --------------------------------------------------------------------------


def test_gap_beyond_policy_opens_a_new_episode():
    result = _reduce([_event(1), _event(2, offset_seconds=901)])

    assert len(result.lifecycles) == 2
    assert result.split_reasons.get("CONTINUITY_GAP_EXCEEDED") == 1


def test_gap_exactly_at_policy_boundary_continues():
    result = _reduce([_event(1), _event(2, offset_seconds=900)])

    assert len(result.lifecycles) == 1


def test_steady_pressure_keeps_one_episode_alive():
    """Unchanged pressure still proves the story is running."""
    events = [_event(i, offset_seconds=i * 300) for i in range(8)]  # 0..2100s
    result = _reduce(events)

    assert len(result.lifecycles) == 1
    lifecycle = next(iter(result.lifecycles.values()))
    # Continuity tracked every event; nothing material ever changed.
    assert lifecycle.last_continuity_event_at_utc == START + timedelta(seconds=2100)
    assert lifecycle.last_material_event_at_utc == START


def test_hard_context_reset_opens_a_new_episode():
    result = _reduce([_event(1), _event(2, offset_seconds=60, hard_reset=True)])

    assert len(result.lifecycles) == 2
    assert result.split_reasons.get("HARD_CONTEXT_RESET") == 1


def test_separate_symbols_never_share_an_episode():
    result = _reduce([_event(1, symbol="CHFJPY"), _event(1, symbol="NZDCAD", offset_seconds=30)])

    assert len(result.lifecycles) == 2


# --------------------------------------------------------------------------
# three clocks: event / continuity / material
# --------------------------------------------------------------------------


def test_identical_pressure_every_five_minutes_advances_continuity_only():
    events = [_event(i, offset_seconds=i * 300) for i in range(4)]
    result = _reduce(events)
    lifecycle = next(iter(result.lifecycles.values()))

    assert len(result.lifecycles) == 1
    assert lifecycle.last_event_at_utc == START + timedelta(seconds=900)
    assert lifecycle.last_continuity_event_at_utc == START + timedelta(seconds=900)
    assert lifecycle.last_material_event_at_utc == START


def test_non_pressure_telemetry_cannot_sustain_an_episode():
    """A heartbeat moves the event clock but not continuity, so the gap fires."""
    events = [_event(1, offset_seconds=0)]
    events += [_heartbeat(i, offset_seconds=300 * (i + 1)) for i in range(3)]  # 300,600,900
    events.append(_event(2, offset_seconds=1000))
    result = _reduce(events)

    # Continuity stopped at t=0, so t=1000 is beyond the 900s continuity gap.
    assert len(result.lifecycles) == 2
    assert result.split_reasons.get("CONTINUITY_GAP_EXCEEDED") == 1


def test_heartbeat_advances_only_the_event_clock():
    result = _reduce([_event(1, offset_seconds=0), _heartbeat(1, offset_seconds=120)])
    lifecycle = next(iter(result.lifecycles.values()))

    assert lifecycle.last_event_at_utc == START + timedelta(seconds=120)
    assert lifecycle.last_continuity_event_at_utc == START
    assert lifecycle.last_material_event_at_utc == START


def test_sticky_microboost_snapshot_advances_continuity_not_material():
    events = [
        _event(1, offset_seconds=0),
        _event(2, offset_seconds=120, microboost_transition=None),
    ]
    result = _reduce(events)
    lifecycle = next(iter(result.lifecycles.values()))

    assert lifecycle.last_continuity_event_at_utc == START + timedelta(seconds=120)
    assert lifecycle.last_material_event_at_utc == START


def test_microboost_weakened_transition_is_material():
    events = [
        _event(1, offset_seconds=0),
        _event(2, offset_seconds=120, microboost_transition="WEAKENED"),
    ]
    result = _reduce(events)
    lifecycle = next(iter(result.lifecycles.values()))

    assert lifecycle.last_continuity_event_at_utc == START + timedelta(seconds=120)
    assert lifecycle.last_material_event_at_utc == START + timedelta(seconds=120)


def test_context_restated_with_same_hash_is_not_material():
    events = [
        _event(1, offset_seconds=0, context_hash="ctx-1"),
        _event(2, offset_seconds=120, context_hash="ctx-1"),
    ]
    result = _reduce(events)
    lifecycle = next(iter(result.lifecycles.values()))

    assert lifecycle.last_material_event_at_utc == START


def test_context_hash_change_is_material_but_keeps_the_lifecycle():
    events = [
        _event(1, offset_seconds=0, context_hash="ctx-1"),
        _event(2, offset_seconds=120, context_hash="ctx-2"),
    ]
    result = _reduce(events)
    lifecycle = next(iter(result.lifecycles.values()))

    assert len(result.lifecycles) == 1
    assert lifecycle.last_material_event_at_utc == START + timedelta(seconds=120)


def test_first_canonical_lineage_is_material_but_restating_it_is_not():
    events = [
        _event(1, offset_seconds=0),
        _event(2, offset_seconds=120, clean_block="block-A"),
        _event(3, offset_seconds=240, clean_block="block-A"),
    ]
    result = _reduce(events)
    lifecycle = next(iter(result.lifecycles.values()))

    # Attached at t=120; restating the same block at t=240 changes nothing.
    assert lifecycle.last_material_event_at_utc == START + timedelta(seconds=120)


def test_material_clock_never_outruns_continuity():
    events = [_event(i, offset_seconds=i * 100, microboost_transition="REINFORCED") for i in range(5)]
    result = _reduce(events)

    for lifecycle in result.lifecycles.values():
        assert lifecycle.last_material_event_at_utc <= lifecycle.last_continuity_event_at_utc
        assert lifecycle.last_continuity_event_at_utc <= lifecycle.last_event_at_utc


# --------------------------------------------------------------------------
# direction semantics
# --------------------------------------------------------------------------


def test_same_direction_continues():
    result = _reduce([_event(1, direction="BUY"), _event(2, offset_seconds=60, direction="BUY")])

    lifecycle = next(iter(result.lifecycles.values()))
    assert len(result.lifecycles) == 1
    assert lifecycle.direction_state == "BUY"


def test_unknown_direction_does_not_erase_a_known_one():
    result = _reduce([_event(1, direction="BUY"), _event(2, offset_seconds=60, direction=None)])

    lifecycle = next(iter(result.lifecycles.values()))
    assert lifecycle.direction_state == "BUY"


def test_unknown_then_known_direction_resolves_in_place():
    result = _reduce([_event(1, direction=None), _event(2, offset_seconds=60, direction="BUY")])

    lifecycle = next(iter(result.lifecycles.values()))
    assert len(result.lifecycles) == 1
    assert lifecycle.direction_state == "BUY"


def test_one_off_opposite_snapshot_becomes_transition_pending_not_a_new_episode():
    """A single opposite snapshot is evidence, not a reversal."""
    result = _reduce([_event(1, direction="BUY"), _event(2, offset_seconds=60, direction="SELL")])

    assert len(result.lifecycles) == 1
    lifecycle = next(iter(result.lifecycles.values()))
    assert lifecycle.state == "TRANSITION_PENDING"
    assert lifecycle.direction_state == "CONFLICT"


def test_transition_pending_resolves_when_direction_is_restated():
    result = _reduce(
        [
            _event(1, direction="BUY"),
            _event(2, offset_seconds=60, direction="SELL"),
            _event(3, offset_seconds=120, direction="BUY"),
        ]
    )

    lifecycle = next(iter(result.lifecycles.values()))
    assert len(result.lifecycles) == 1
    assert lifecycle.state == "ANALYSIS_OPEN"
    assert lifecycle.direction_state == "BUY"


def test_transition_pending_survives_an_unknown_direction_refresh():
    result = _reduce(
        [
            _event(1, direction="BUY"),
            _event(2, offset_seconds=60, direction="SELL"),
            _event(3, offset_seconds=120, direction=None),
        ]
    )

    lifecycle = next(iter(result.lifecycles.values()))
    assert lifecycle.state == "TRANSITION_PENDING"


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


def test_out_of_order_input_is_deterministic():
    events = [_event(i, offset_seconds=i * 60) for i in range(6)]
    forward = _reduce(events)
    reversed_result = _reduce(list(reversed(events)))

    assert set(forward.lifecycles) == set(reversed_result.lifecycles)
    assert forward.compression_ratio == reversed_result.compression_ratio


def test_reducer_restart_reproduces_the_same_ids():
    events = [_event(i, offset_seconds=i * 60) for i in range(5)]

    first = _reduce(events)
    second = _reduce(events)

    assert sorted(first.lifecycles) == sorted(second.lifecycles)


def test_lifecycle_id_excludes_transport_identity():
    with_block = _reduce([_event(1, clean_block="block-A")])
    without_block = _reduce([_event(1)])

    assert sorted(with_block.lifecycles) == sorted(without_block.lifecycles)


# --------------------------------------------------------------------------
# shadow-only invariant
# --------------------------------------------------------------------------


def test_lifecycles_never_carry_execution_authority():
    result = _reduce([_event(i, offset_seconds=i * 60) for i in range(3)])

    assert all(item.execution_authority is False for item in result.lifecycles.values())
