"""S1B-0 acceptance: MarketEpisodeV31 is the identity root (owner decision S3, SSOT v3.1 §4.2, §7A.6, §8.1, §8.3)."""

from __future__ import annotations

import ast
import inspect
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_market_episode_v31 import MarketEpisodeReducerV31
from contracts.strategy_5scr_market_episode_v31 import (
    LifecycleMergePolicyV31,
    MarketEpisodeEventV31,
    MarketEpisodeV31,
    canonical_sha256_v31,
    market_episode_id_v31,
    strategy_lifecycle_id_from_episode_v31,
)

T0 = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def _policy(gap: int = 900, version: str = "test-merge.v1") -> LifecycleMergePolicyV31:
    body: dict[str, Any] = {
        "policy_version": version,
        "rule_version": "5scr.market-episode.v31.v1",
        "max_continuity_gap_seconds": gap,
    }
    return LifecycleMergePolicyV31(**body, policy_hash=canonical_sha256_v31(body))


POLICY = _policy()


def _event(n: int, seconds: float, *, symbol: str = "EURUSD", direction: Any = "BUY", **overrides: Any):
    values: dict[str, Any] = {
        "pressure_event_id": f"{symbol}-ev-{n}",
        "canonical_symbol": symbol,
        "event_time": T0 + timedelta(seconds=seconds),
        "direction": direction,
        "pressure_seen": True,
        "pair_eligible_for_analysis": False,
        "allowed_quorum_reached": False,
        "microboost_detected": False,
        "pressure_event_count": 1,
        "microboost_transition": None,
        "material_context_hash": None,
        "hard_structural_invalidation_evidence_id": None,
        "confirmed_opposite_transition_evidence_id": None,
        "transport_lifecycle_id": f"transport-{n}",
        "source_clean_block_id": None,
        "source_watch_id": None,
        "cluster_id": f"cluster-{n}",
        "deployment_id": "deploy-A",
        **overrides,
    }
    return MarketEpisodeEventV31(**values)


def _heartbeat(n: int, seconds: float, **overrides: Any):
    return _event(n, seconds, direction=None, pressure_seen=False, pressure_event_count=0, **overrides)


def _reduce(events, policy=POLICY):
    return MarketEpisodeReducerV31(policy=policy).ingest_many(events)


def test_replay_in_any_arrival_order_gives_identical_episode_and_lifecycle_ids():
    events = [_event(i, i * 60) for i in range(6)] + [_event(10 + i, i * 60, symbol="GBPUSD") for i in range(4)]
    baseline = _reduce(events)
    shuffled = events[:]
    random.Random(7).shuffle(shuffled)
    replay = _reduce(shuffled)
    assert set(baseline.episodes) == set(replay.episodes) and len(baseline.episodes) == 2
    assert baseline.episodes == replay.episodes
    for episode in baseline.episodes.values():
        assert episode.strategy_lifecycle_id == strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)


def test_transport_deployment_cluster_block_and_watch_churn_never_open_an_episode():
    events = [
        _event(
            i,
            i * 60,
            deployment_id=f"deploy-{i}",
            cluster_id=f"cluster-{i}",
            transport_lifecycle_id=f"t-{i}",
            source_clean_block_id=f"block-{i}",
            source_watch_id=f"watch-{i}",
        )
        for i in range(8)
    ]
    reduction = _reduce(events)
    assert len(reduction.episodes) == 1 and reduction.split_reasons == {"NO_ACTIVE_EPISODE": 1}


def test_duplicate_telemetry_changes_nothing():
    events = [_event(i, i * 60) for i in range(4)]
    once = _reduce(events)
    twice = _reduce(events + events)
    assert (once.episodes, once.states) == (twice.episodes, twice.states)
    assert twice.duplicate_event_count == 4 and len(twice.links) == len(once.links)


def test_gap_is_measured_on_the_continuity_clock_not_the_event_or_material_clock():
    # Steady same-direction pressure (continuity, no material change) keeps one episode for 2 h.
    steady = _reduce([_event(i, i * 600) for i in range(13)])
    (state,) = steady.states.values()
    assert len(steady.episodes) == 1 and state.last_material_event_at == T0
    # Heartbeats carry no continuity evidence: they cannot keep a dead episode alive.
    events = [_event(0, 0)] + [_heartbeat(i, i * 300) for i in range(1, 5)] + [_event(9, 1500)]
    split = _reduce(events)
    assert len(split.episodes) == 2 and split.split_reasons["CONTINUITY_GAP_EXCEEDED"] == 1
    closed = [s for s in split.states.values() if s.state == "CLOSED"]
    assert len(closed) == 1 and closed[0].closed_reason == "CONTINUITY_GAP_EXCEEDED"


def test_single_opposite_snapshot_is_transition_pending_not_a_new_episode():
    reduction = _reduce([_event(0, 0), _event(1, 60, direction="SELL"), _event(2, 120, direction="BUY")])
    assert len(reduction.episodes) == 1
    reasons = [link.link_reason for link in reduction.links]
    assert reasons == ["EPISODE_OPENED", "DIRECTION_TRANSITION_PENDING", "DIRECTION_RESTATED"]
    pending = _reduce([_event(0, 0), _event(1, 60, direction="SELL")])
    (state,) = pending.states.values()
    assert (state.state, state.direction_state) == ("TRANSITION_PENDING", "CONFLICT")


def test_confirmed_opposite_transition_and_hard_structural_invalidation_open_new_episodes():
    flip = _reduce([_event(0, 0), _event(1, 60, direction="SELL", confirmed_opposite_transition_evidence_id="proof-1")])
    assert len(flip.episodes) == 2 and flip.split_reasons["CONFIRMED_OPPOSITE_TRANSITION"] == 1
    reset = _reduce([_event(0, 0), _event(1, 60, hard_structural_invalidation_evidence_id="invalidation-1")])
    assert len(reset.episodes) == 2 and reset.split_reasons["HARD_STRUCTURAL_INVALIDATION"] == 1


def test_restart_or_redeploy_resumes_the_same_episode():
    first = MarketEpisodeReducerV31(policy=POLICY)
    first.ingest_many([_event(i, i * 60) for i in range(3)])
    ((episode_id, episode),) = first.result.episodes.items()
    resumed = MarketEpisodeReducerV31(policy=POLICY)
    resumed.seed(
        episode,
        first.result.states[episode_id],
        seen_event_ids=[link.pressure_event_id for link in first.result.links],
        last_definite_direction="BUY",
    )
    resumed.ingest_many([_event(i, i * 60, deployment_id="deploy-B") for i in range(2, 6)])
    assert set(resumed.result.episodes) == {episode_id} and resumed.result.duplicate_event_count == 1


def test_a_different_merge_policy_opens_a_new_episode_and_policies_have_no_defaults():
    first = MarketEpisodeReducerV31(policy=POLICY)
    first.ingest(_event(0, 0))
    ((episode_id, episode),) = first.result.episodes.items()
    other = MarketEpisodeReducerV31(policy=_policy(1800, "test-merge.v2"))
    other.seed(episode, first.result.states[episode_id])
    other.ingest(_event(1, 60))
    assert other.result.split_reasons == {"MERGE_POLICY_CHANGED": 1} and len(other.result.episodes) == 2
    with pytest.raises(ValidationError):
        LifecycleMergePolicyV31(
            policy_version="x.v1", rule_version="5scr.market-episode.v31.v1", policy_hash=POLICY.policy_hash
        )  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="LIFECYCLE_MERGE_POLICY_HASH_MISMATCH"):
        LifecycleMergePolicyV31.model_validate({**POLICY.model_dump(), "max_continuity_gap_seconds": 60})
    with pytest.raises(TypeError):
        MarketEpisodeReducerV31()  # type: ignore[call-arg]


def test_identity_has_no_transport_deployment_or_admission_input():
    for fn in (market_episode_id_v31, strategy_lifecycle_id_from_episode_v31):
        params = set(inspect.signature(fn).parameters)
        assert not params & {
            "deployment_id",
            "cluster_id",
            "source_clean_block_id",
            "admission_class",
            "strategy_analysis_admission_id",
        }
    episode = next(iter(_reduce([_event(0, 0)]).episodes.values()))
    with pytest.raises(ValidationError, match="MARKET_EPISODE_ID_NOT_DERIVED"):
        MarketEpisodeV31.model_validate({**episode.model_dump(), "opened_at": T0 + timedelta(seconds=1)})
    with pytest.raises(ValidationError, match="STRATEGY_LIFECYCLE_ID_NOT_DERIVED_FROM_EPISODE"):
        MarketEpisodeV31.model_validate({**episode.model_dump(), "strategy_lifecycle_id": episode.market_episode_id})


def test_episodes_are_pair_local():
    eur = [_event(i, i * 60) for i in range(4)]
    alone = _reduce(eur)
    mixed = _reduce(eur + [_event(20 + i, i * 30, symbol="GBPUSD", direction="SELL") for i in range(8)])
    eur_alone = {k: v for k, v in alone.episodes.items() if v.canonical_symbol == "EURUSD"}
    eur_mixed = {k: v for k, v in mixed.episodes.items() if v.canonical_symbol == "EURUSD"}
    assert eur_alone == eur_mixed
    assert {k: alone.states[k] for k in eur_alone} == {k: mixed.states[k] for k in eur_mixed}


def test_v31_modules_never_import_the_legacy_nonconformant_s1b():
    legacy = {"contracts.strategy_5scr_analysis_admission", "analysis.strategy_5scr_analysis_admission"}
    for path in (*ROOT.glob("contracts/*_v31.py"), *ROOT.glob("analysis/*_v31.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not imported & legacy, path.name
