"""Replay audit of episode grouping over the repo's real archive cohort.

Runs ``5scr.market-episode.v1`` across the 1985 deduplicated pressure events in
``artifacts/strategy_5scr_log_archive_audit_20260724`` and contrasts the result
with the transport grouping those same events produce today.

The ~216-episode figure is a *comparison benchmark*, not an acceptance
threshold: grouping must follow from the rules, never be tuned to reproduce a
number.  These assertions therefore test properties and direction of travel,
with generous bounds, and print the measured values for review.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from analysis.strategy_5scr_v3.episode_grouping import EpisodeEvent
from analysis.strategy_5scr_v3.episode_policy import MarketEpisodePolicyV1
from analysis.strategy_5scr_v3.episode_reducer import MarketEpisodeReducer

COHORT = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "strategy_5scr_log_archive_audit_20260724"
    / "unique_pressure_events.csv"
)

pytestmark = pytest.mark.skipif(not COHORT.exists(), reason="archive cohort artifact is not present")


def _load_events() -> list[EpisodeEvent]:
    events: list[EpisodeEvent] = []
    with COHORT.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            clean_block = (row.get("source_clean_block_id") or "").strip() or None
            execution_grade = row.get("campaign_anchor_execution_grade") == "True"
            cluster_id = row.get("cluster_id") or ""
            # Reconstruct the transport identity these events resolve to today.
            transport = clean_block if execution_grade and clean_block else f"unresolved:{row['symbol']}:{cluster_id}"
            events.append(
                EpisodeEvent(
                    pressure_event_id=row["event_id"],
                    symbol=row["symbol"],
                    event_time_utc=datetime.fromisoformat(row["event_time_utc"].replace("Z", "+00:00")),
                    transport_lifecycle_id=transport,
                    raw_direction=(row.get("raw_direction") or "").strip() or None,
                    source_clean_block_id=clean_block,
                    # Continuity evidence as recorded in the archive.
                    pair_eligible_for_analysis=row.get("pair_eligible_for_analysis") == "True",
                    allowed_quorum_reached=row.get("allowed_quorum_reached") == "True",
                    pressure_event_count=int(row.get("pressure_event_count") or 0),
                    microboost_detected=(row.get("pressure_level") or "") == "MICROBOOST_WATCH",
                )
            )
    return events


@pytest.fixture(scope="module")
def cohort() -> list[EpisodeEvent]:
    return _load_events()


@pytest.fixture(scope="module")
def reduction(cohort):
    return MarketEpisodeReducer(policy=MarketEpisodePolicyV1()).ingest_many(cohort)


def test_cohort_is_the_expected_archive(cohort):
    assert len(cohort) == 1985
    # The premise of the whole change: transport identity is per-emission.
    assert len({event.pressure_event_id for event in cohort}) == 1985


def test_linked_event_count_equals_unique_input_event_count(cohort, reduction):
    """No event may be dropped, and none may be linked twice."""
    linked_event_count = len(reduction.links)
    unique_input_event_count = len({event.pressure_event_id for event in cohort})

    assert linked_event_count == unique_input_event_count
    assert {link.pressure_event_id for link in reduction.links} == {event.pressure_event_id for event in cohort}


def test_no_orphan_events(cohort, reduction):
    linked = {link.strategy_lifecycle_id for link in reduction.links}

    assert linked == set(reduction.lifecycles)


def test_episode_grouping_materially_beats_transport_grouping(cohort, reduction):
    transport_lifecycle_count = len({event.transport_lifecycle_id for event in cohort})
    transport_compression_ratio = len(cohort) / transport_lifecycle_count
    v2_lifecycle_count = len(reduction.lifecycles)
    v2_compression_ratio = reduction.compression_ratio

    print(
        f"\n  events={len(cohort)}"
        f"\n  transport lifecycles={transport_lifecycle_count}"
        f" (compression {transport_compression_ratio:.2f})"
        f"\n  strategy lifecycles V2={v2_lifecycle_count}"
        f" (compression {v2_compression_ratio:.2f})"
        f"\n  split reasons={reduction.split_reasons}"
    )

    # Relative assertions only: the rules decide the number, not a target.
    # Fewer lifecycles, higher compression -- the two move in opposite
    # directions, so both are asserted explicitly.
    assert v2_lifecycle_count < transport_lifecycle_count
    assert v2_compression_ratio > transport_compression_ratio


def test_episode_count_is_in_the_expected_neighbourhood(reduction):
    """Anomaly guard only -- ~216 is a benchmark, never strategy truth.

    A rule change may legitimately move this number.  When it does, review the
    change and update the guard; do not treat this bound as a permanent gate,
    and do not tune the rules to satisfy it.
    """
    assert 100 <= len(reduction.lifecycles) <= 400


def test_duplicate_events_have_no_side_effect(cohort):
    """Redelivering the whole cohort must change nothing."""
    once = MarketEpisodeReducer(policy=MarketEpisodePolicyV1()).ingest_many(cohort)
    twice = MarketEpisodeReducer(policy=MarketEpisodePolicyV1()).ingest_many(list(cohort) + list(cohort))

    assert len(twice.lifecycles) == len(once.lifecycles)
    assert len(twice.links) == len(once.links)
    assert twice.duplicate_event_count == len(cohort)


def test_no_episode_spans_more_than_one_symbol(cohort, reduction):
    by_lifecycle: dict[str, set[str]] = {}
    symbols = {event.pressure_event_id: event.symbol for event in cohort}
    for link in reduction.links:
        by_lifecycle.setdefault(link.strategy_lifecycle_id, set()).add(symbols[link.pressure_event_id])

    assert all(len(found) == 1 for found in by_lifecycle.values())


def test_canonical_anchors_are_retained_not_discarded(cohort, reduction):
    anchored_events = sum(1 for event in cohort if event.source_clean_block_id)
    anchored_links = sum(1 for link in reduction.links if link.source_clean_block_id)

    assert anchored_links == anchored_events
    assert anchored_events > 0


def test_multiple_clean_blocks_collapse_into_shared_episodes(reduction):
    """Canonical lineage becomes evidence inside an episode, not its identity."""
    multi_block = [item for item in reduction.lifecycles.values() if item.clean_block_count > 1]

    assert multi_block, "expected at least one episode spanning several clean blocks"


def test_reduction_is_deterministic(cohort):
    first = MarketEpisodeReducer(policy=MarketEpisodePolicyV1()).ingest_many(cohort)
    second = MarketEpisodeReducer(policy=MarketEpisodePolicyV1()).ingest_many(list(reversed(cohort)))

    assert sorted(first.lifecycles) == sorted(second.lifecycles)
    assert first.compression_ratio == second.compression_ratio


def test_tighter_gap_yields_more_episodes(cohort):
    tight = MarketEpisodeReducer(policy=MarketEpisodePolicyV1(max_continuity_gap_seconds=300)).ingest_many(cohort)
    wide = MarketEpisodeReducer(policy=MarketEpisodePolicyV1(max_continuity_gap_seconds=1800)).ingest_many(cohort)

    assert len(tight.lifecycles) > len(wide.lifecycles)


def test_no_episode_claims_execution_authority(reduction):
    assert all(item.execution_authority is False for item in reduction.lifecycles.values())
