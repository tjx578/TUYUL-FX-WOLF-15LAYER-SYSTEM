"""S1B-2 acceptance: AnalysisLifecycleV31 attachment/upgrade + append-only revisions (SSOT v3.1 §4.2, §7A.6, §8)."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_analysis_lifecycle_v31 import (
    InMemoryAnalysisLifecycleLedgerV31,
    attach_admission_v31,
    expire_admission_v31,
    lifecycle_progression_allowed_v31,
    lifecycle_view_v31,
    rebuild_lifecycles_v31,
    record_admission_revision_v31,
    require_canonical_lineage_v31,
)
from contracts.strategy_5scr_analysis_lifecycle_v31 import AnalysisLifecycleV31, AuthorityUpgradeV31
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31
from tests.test_strategy_5scr_analysis_admission_v31 import AT, _advisory, _canonical, _episode
from tests.test_strategy_5scr_market_episode_v31 import _event, _reduce
from tests.test_strategy_5scr_pair_admission_coverage_v31 import _classify, _evaluation, _observation
from tests.test_strategy_5scr_per_symbol_admission import _safety


def _chain(symbol: str = "EURUSD", episode: Any = None, state: Any = None):
    """IMMATURE rejection → later advisory grant → later canonical grant, all in one market episode."""

    if episode is None:
        episode, state = _episode(symbol)
    advisory_coverage = _classify(_observation(block=None, symbol=symbol), maturity="MATURE").coverage
    immature = _advisory(episode, state, coverage=advisory_coverage, duration_seconds=100.0).admission
    advisory = _advisory(episode, state, coverage=advisory_coverage, at=AT + timedelta(minutes=5)).admission
    evaluation = _evaluation(canonical_symbol=symbol, raw_authority_block_id=f"{symbol}-block-1")
    canonical = _canonical(
        episode,
        state,
        coverage=_classify(_observation(symbol=symbol), evaluation=evaluation).coverage,
        evaluation=evaluation,
        at=AT + timedelta(minutes=10),
    ).admission
    assert immature is not None and advisory is not None and canonical is not None
    assert (immature.admission_status, advisory.admission_status, canonical.admission_status) == (
        "REJECTED",
        "GRANTED",
        "GRANTED",
    )
    return episode, state, immature, advisory, canonical


def _apply(ledger, episode, state, *admissions):
    results = []
    for admission in admissions:
        results.append(record_admission_revision_v31(ledger, admission))
        if admission.admission_status == "GRANTED":
            results.append(attach_admission_v31(ledger, episode=episode, episode_state=state, admission=admission))
    return results


def test_advisory_opens_the_lifecycle_and_canonical_upgrades_the_same_one():
    episode, state, immature, advisory, canonical = _chain()
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, immature, advisory)
    lifecycle_id = strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)
    before = lifecycle_view_v31(ledger, lifecycle_id, state)
    assert (before.highest_analysis_authority, before.active_strategy_analysis_admission_id) == (
        "MATURE_ADVISORY",
        advisory.strategy_analysis_admission_id,
    )
    attached = _apply(ledger, episode, state, canonical)[-1]
    view, upgrade = attached.view, attached.upgrade
    assert view is not None and upgrade is not None
    assert view.strategy_lifecycle_id == lifecycle_id == before.strategy_lifecycle_id  # same L
    assert list(ledger.attachments) == [lifecycle_id]  # no second lifecycle
    assert advisory.strategy_analysis_admission_id != canonical.strategy_analysis_admission_id
    assert view.admission_lineage_ids == (
        advisory.strategy_analysis_admission_id,
        canonical.strategy_analysis_admission_id,
    )
    assert (view.highest_analysis_authority, view.active_strategy_analysis_admission_id) == (
        "CANONICAL_RAW",
        canonical.strategy_analysis_admission_id,
    )
    assert (upgrade.from_authority, upgrade.to_authority, upgrade.trigger_admission_id) == (
        "MATURE_ADVISORY",
        "CANONICAL_RAW",
        canonical.strategy_analysis_admission_id,
    )
    assert upgrade.superseded_active_admission_id == advisory.strategy_analysis_admission_id


def test_upgrade_never_reuses_the_advisory_candidate_as_canonical():
    episode, state, immature, advisory, canonical = _chain()
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    upgrade = _apply(ledger, episode, state, immature, advisory, canonical)[-1].upgrade
    assert upgrade is not None
    assert (upgrade.required_action, upgrade.advisory_candidate_reused_as_canonical) == (
        "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED",
        False,
    )
    view = lifecycle_view_v31(ledger, upgrade.strategy_lifecycle_id, state)
    assert require_canonical_lineage_v31(view, advisory.strategy_analysis_admission_id) == (
        "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    )
    assert require_canonical_lineage_v31(view, canonical.strategy_analysis_admission_id) is None
    with pytest.raises(ValidationError):
        AuthorityUpgradeV31.model_validate({**upgrade.model_dump(), "advisory_candidate_reused_as_canonical": True})


def test_admission_revisions_are_append_only_under_one_logical_id():
    episode, state, immature, advisory, _ = _chain()
    assert immature.strategy_analysis_admission_id == advisory.strategy_analysis_admission_id
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    first = record_admission_revision_v31(ledger, immature).revision
    assert first is not None
    snapshot = first.model_dump()
    second = record_admission_revision_v31(ledger, advisory).revision
    assert second is not None
    chain = ledger.revisions[advisory.strategy_analysis_admission_id]
    assert [r.revision_number for r in chain] == [1, 2] and chain[0].model_dump() == snapshot
    assert (second.supersedes_revision_id, second.previous_revision_hash) == (first.revision_id, first.revision_hash)
    assert (first.admission_status, first.reason_code, second.admission_status) == (
        "REJECTED",
        "ADVISORY_PRESSURE_IMMATURE",
        "GRANTED",
    )


def test_authority_downgrade_is_rejected_and_expiry_keeps_canonical_lineage():
    episode, state, immature, advisory, canonical = _chain()
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, immature, advisory, canonical)
    lifecycle_id = strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)
    suspended = _canonical(
        episode, state, direction="CONFLICT", alignment="CONFLICT", at=AT + timedelta(minutes=20)
    ).admission
    assert suspended is not None
    assert record_admission_revision_v31(ledger, suspended).reason_code == "AUTHORITY_DOWNGRADE_FORBIDDEN"
    refresh = _canonical(episode, state, at=AT + timedelta(minutes=30)).admission
    assert refresh is not None
    assert record_admission_revision_v31(ledger, refresh).reason_code == "ADMISSION_ALREADY_GRANTED"
    assert expire_admission_v31(ledger, canonical.strategy_analysis_admission_id, at=AT).reason_code == (
        "EXPIRY_BEFORE_DEADLINE"
    )
    assert canonical.expires_at_utc is not None
    expired = expire_admission_v31(ledger, canonical.strategy_analysis_admission_id, at=canonical.expires_at_utc)
    assert expired.revision is not None and expired.revision.admission_status == "EXPIRED"
    assert lifecycle_view_v31(ledger, lifecycle_id, state).highest_analysis_authority == "CANONICAL_RAW"  # §8.6
    assert record_admission_revision_v31(ledger, suspended).reason_code == "ADMISSION_TERMINAL"
    view = lifecycle_view_v31(ledger, lifecycle_id, state)
    with pytest.raises(ValidationError, match="HIGHEST_ANALYSIS_AUTHORITY_NOT_DERIVED"):
        AnalysisLifecycleV31.model_validate({**view.model_dump(), "highest_analysis_authority": "MATURE_ADVISORY"})
    with pytest.raises(ValidationError, match="ACTIVE_ADMISSION_NOT_DERIVED"):
        AnalysisLifecycleV31.model_validate(
            {**view.model_dump(), "active_strategy_analysis_admission_id": advisory.strategy_analysis_admission_id}
        )


def test_symbols_interleave_without_cross_contamination():
    eur = _chain("EURUSD")
    gbp = _chain("GBPUSD")
    solo = rebuild_lifecycles_v31(episodes=[eur[:2]], admissions=eur[2:])
    mixed = rebuild_lifecycles_v31(episodes=[eur[:2], gbp[:2]], admissions=[*eur[2:], *gbp[2:]])
    eur_id = strategy_lifecycle_id_from_episode_v31(eur[0].market_episode_id)
    gbp_id = strategy_lifecycle_id_from_episode_v31(gbp[0].market_episode_id)
    assert eur_id != gbp_id and set(mixed.attachments) == {eur_id, gbp_id}
    assert lifecycle_view_v31(solo, eur_id, eur[1]) == lifecycle_view_v31(mixed, eur_id, eur[1])
    assert solo.attachments[eur_id] == mixed.attachments[eur_id] and solo.upgrades[eur_id] == mixed.upgrades[eur_id]


def test_random_replay_order_gives_the_same_final_lineage():
    eur, gbp = _chain("EURUSD"), _chain("GBPUSD")
    admissions = [*eur[2:], *gbp[2:]]
    baseline = rebuild_lifecycles_v31(episodes=[eur[:2], gbp[:2]], admissions=admissions)
    for seed in range(5):
        shuffled = admissions[:]
        random.Random(seed).shuffle(shuffled)
        replay = rebuild_lifecycles_v31(episodes=[eur[:2], gbp[:2]], admissions=shuffled)
        assert (replay.revisions, replay.attachments, replay.upgrades) == (
            baseline.revisions,
            baseline.attachments,
            baseline.upgrades,
        )


def test_deployment_and_restart_metadata_never_change_lifecycle_identity():
    events_a = [_event(0, 0, deployment_id="deploy-A"), _event(1, 60, deployment_id="deploy-A")]
    events_b = [_event(0, 0, deployment_id="deploy-B", cluster_id="c-x"), _event(1, 60, deployment_id="deploy-C")]
    (episode_a,) = _reduce(events_a).episodes.values()
    (episode_b,) = _reduce(events_b).episodes.values()
    assert episode_a.strategy_lifecycle_id == episode_b.strategy_lifecycle_id
    episode, state, *admissions = _chain()
    live = InMemoryAnalysisLifecycleLedgerV31()
    _apply(live, episode, state, *admissions)
    restarted = rebuild_lifecycles_v31(episodes=[(episode, state)], admissions=admissions)
    lifecycle_id = strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)
    assert lifecycle_view_v31(live, lifecycle_id, state) == lifecycle_view_v31(restarted, lifecycle_id, state)


@pytest.mark.parametrize("override", [{"kill_switch_active": True}, {"database_and_governance_ok": False}])
def test_global_veto_stops_progression_without_touching_history(override):
    episode, state, *admissions = _chain()
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, *admissions)
    lifecycle_id = strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)
    view = lifecycle_view_v31(ledger, lifecycle_id, state)
    history = (dict(ledger.revisions), dict(ledger.attachments), dict(ledger.upgrades))
    allowed, vetoes = lifecycle_progression_allowed_v31(view, _safety(**override))
    assert (allowed, bool(vetoes)) == (False, True)
    assert lifecycle_progression_allowed_v31(view, _safety())[0] is True
    assert (dict(ledger.revisions), dict(ledger.attachments), dict(ledger.upgrades)) == history
    assert lifecycle_view_v31(ledger, lifecycle_id, state) == view


def test_duplicate_decisions_and_attachments_are_idempotent():
    episode, state, immature, advisory, canonical = _chain()
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, immature, advisory, canonical)
    snapshot = ({k: list(v) for k, v in ledger.revisions.items()}, {k: list(v) for k, v in ledger.attachments.items()})
    assert record_admission_revision_v31(ledger, canonical).outcome == "IDEMPOTENT"
    again = attach_admission_v31(ledger, episode=episode, episode_state=state, admission=canonical)
    assert (again.outcome, again.upgrade) == ("ALREADY_ATTACHED", None)
    assert (
        {k: list(v) for k, v in ledger.revisions.items()},
        {k: list(v) for k, v in ledger.attachments.items()},
    ) == snapshot
    assert len(ledger.upgrades[strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)]) == 1


def test_unrecorded_or_ungranted_admissions_never_attach_and_a_later_advisory_never_lowers_authority():
    episode, state, immature, advisory, canonical = _chain()
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    assert attach_admission_v31(ledger, episode=episode, episode_state=state, admission=advisory).reason_code == (
        "ADMISSION_NOT_GRANTED_OR_NOT_RECORDED"
    )
    _apply(ledger, episode, state, immature, canonical)
    # Recorded but REJECTED (immature): its record matches the latest revision, yet it may never attach.
    assert attach_admission_v31(ledger, episode=episode, episode_state=state, admission=immature).reason_code == (
        "ADMISSION_NOT_GRANTED_OR_NOT_RECORDED"
    )
    _apply(ledger, episode, state, advisory)  # advisory granted after canonical
    lifecycle_id = strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)
    view = lifecycle_view_v31(ledger, lifecycle_id, state)
    assert (view.highest_analysis_authority, view.active_strategy_analysis_admission_id) == (
        "CANONICAL_RAW",
        canonical.strategy_analysis_admission_id,
    )
    assert lifecycle_id not in ledger.upgrades  # canonical opened the lifecycle: nothing to upgrade
