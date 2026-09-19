"""Pure S1B-2 operations over an in-memory reference ledger (durability invariants, not persistence).

record → attach → (upgrade) → view. No wall clock (times come from the admission decisions), no global safety
input to any write (a global veto only gates effective progression), no path to candidates, risk or execution.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from contracts.strategy_5scr_analysis_admission_v31 import (
    StrategyAnalysisAdmissionV31,
    strategy_analysis_admission_hash_v31,
)
from contracts.strategy_5scr_analysis_lifecycle_v31 import (
    AUTHORITY_RANK,
    AdmissionRevisionV31,
    AnalysisLifecycleV31,
    AuthorityUpgradeV31,
    LifecycleAttachmentV31,
    admission_revision_id_v31,
    derive_highest_authority_v31,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_market_episode_v31 import (
    MarketEpisodeStateV31,
    MarketEpisodeV31,
    strategy_lifecycle_id_from_episode_v31,
)
from contracts.strategy_5scr_per_symbol_admission import GlobalSafetyStateV1


def _hashed(model_type: Any, hash_field: str, values: dict[str, Any]) -> Any:
    probe = model_type.model_construct(**{**values, hash_field: "sha256:" + "0" * 64})
    body = {k: v for k, v in probe.model_dump(mode="json").items() if k != hash_field}
    return model_type.model_validate({**values, hash_field: canonical_sha256_v31(body)})


@dataclass
class InMemoryAnalysisLifecycleLedgerV31:
    revisions: dict[UUID, list[AdmissionRevisionV31]] = field(default_factory=dict)
    records: dict[str, StrategyAnalysisAdmissionV31] = field(default_factory=dict)
    attachments: dict[UUID, list[LifecycleAttachmentV31]] = field(default_factory=dict)
    upgrades: dict[UUID, list[AuthorityUpgradeV31]] = field(default_factory=dict)
    episodes: dict[UUID, MarketEpisodeV31] = field(default_factory=dict)

    def latest_revision(self, admission_id: UUID) -> AdmissionRevisionV31 | None:
        chain = self.revisions.get(admission_id)
        return chain[-1] if chain else None


@dataclass(frozen=True)
class LedgerDecisionV31:
    outcome: Literal["RECORDED", "IDEMPOTENT", "REJECTED", "ATTACHED", "ALREADY_ATTACHED", "NOT_ATTACHED"]
    reason_code: str
    revision: AdmissionRevisionV31 | None = None
    view: AnalysisLifecycleV31 | None = None
    upgrade: AuthorityUpgradeV31 | None = None


def _append_revision(
    ledger: InMemoryAnalysisLifecycleLedgerV31,
    admission_id: UUID,
    *,
    episode_id: UUID,
    admission_class: str,
    status: str,
    reason: str,
    record_hash: str | None,
    at: datetime,
) -> AdmissionRevisionV31:
    chain = ledger.revisions.setdefault(admission_id, [])
    previous = chain[-1] if chain else None
    number = len(chain) + 1
    revision = _hashed(
        AdmissionRevisionV31,
        "revision_hash",
        {
            "strategy_analysis_admission_id": admission_id,
            "market_episode_id": episode_id,
            "admission_class": admission_class,
            "revision_number": number,
            "revision_id": admission_revision_id_v31(
                strategy_analysis_admission_id=admission_id, revision_number=number
            ),
            "supersedes_revision_id": None if previous is None else previous.revision_id,
            "previous_revision_hash": None if previous is None else previous.revision_hash,
            "recorded_at": at,
            "admission_status": status,
            "reason_code": reason,
            "admission_record_hash": record_hash,
        },
    )
    chain.append(revision)
    return revision


def record_admission_revision_v31(
    ledger: InMemoryAnalysisLifecycleLedgerV31, admission: StrategyAnalysisAdmissionV31
) -> LedgerDecisionV31:
    """Append a decision revision under the stable logical admission id. Never overwrites, never downgrades."""

    admission = StrategyAnalysisAdmissionV31.model_validate(admission.model_dump())
    record_hash = strategy_analysis_admission_hash_v31(admission)
    latest = ledger.latest_revision(admission.strategy_analysis_admission_id)
    if latest is not None:
        if latest.admission_record_hash == record_hash:
            return LedgerDecisionV31("IDEMPOTENT", "DUPLICATE_ADMISSION_DECISION", latest)
        if (latest.market_episode_id, latest.admission_class) != (
            admission.market_episode_id,
            admission.admission_class,
        ):
            return LedgerDecisionV31("REJECTED", "ADMISSION_IDENTITY_SCOPE_CONFLICT", latest)
        if latest.admission_status == "EXPIRED":
            return LedgerDecisionV31("REJECTED", "ADMISSION_TERMINAL", latest)
        if latest.admission_status == "GRANTED":
            if admission.admission_status == "GRANTED":
                return LedgerDecisionV31("IDEMPOTENT", "ADMISSION_ALREADY_GRANTED", latest)  # the first grant stands
            return LedgerDecisionV31("REJECTED", "AUTHORITY_DOWNGRADE_FORBIDDEN", latest)
        if admission.decided_at_utc < latest.recorded_at:
            return LedgerDecisionV31("REJECTED", "ADMISSION_REVISION_OUT_OF_ORDER", latest)
    ledger.records[record_hash] = admission
    revision = _append_revision(
        ledger,
        admission.strategy_analysis_admission_id,
        episode_id=admission.market_episode_id,
        admission_class=admission.admission_class,
        status=admission.admission_status,
        reason=admission.reason_code,
        record_hash=record_hash,
        at=admission.decided_at_utc,
    )
    return LedgerDecisionV31("RECORDED", admission.reason_code, revision)


def expire_admission_v31(
    ledger: InMemoryAnalysisLifecycleLedgerV31, admission_id: UUID, *, at: datetime
) -> LedgerDecisionV31:
    """The only legal GRANTED → non-GRANTED move: the explicit terminal clock expiry (§18). Lineage is kept."""

    latest = ledger.latest_revision(admission_id)
    if latest is None or latest.admission_status != "GRANTED":
        return LedgerDecisionV31("REJECTED", "ADMISSION_NOT_GRANTED", latest)
    assert latest.admission_record_hash is not None
    granted = ledger.records[latest.admission_record_hash]
    assert granted.expires_at_utc is not None
    if at < granted.expires_at_utc:
        return LedgerDecisionV31("REJECTED", "EXPIRY_BEFORE_DEADLINE", latest)
    revision = _append_revision(
        ledger,
        admission_id,
        episode_id=latest.market_episode_id,
        admission_class=latest.admission_class,
        status="EXPIRED",
        reason="STRATEGY_ANALYSIS_ADMISSION_EXPIRED",
        record_hash=None,
        at=at,
    )
    return LedgerDecisionV31("RECORDED", "STRATEGY_ANALYSIS_ADMISSION_EXPIRED", revision)


def lifecycle_view_v31(
    ledger: InMemoryAnalysisLifecycleLedgerV31, strategy_lifecycle_id: UUID, episode_state: MarketEpisodeStateV31
) -> AnalysisLifecycleV31:
    episode = ledger.episodes[strategy_lifecycle_id]
    chain = ledger.attachments[strategy_lifecycle_id]
    if episode_state.market_episode_id != episode.market_episode_id:
        raise ValueError("EPISODE_STATE_MISMATCH")
    ids = tuple(a.strategy_analysis_admission_id for a in chain)
    classes = tuple(a.admission_class for a in chain)
    highest = derive_highest_authority_v31(classes)
    active = next(i for i, c in reversed(tuple(zip(ids, classes, strict=True))) if c == highest)
    return _hashed(
        AnalysisLifecycleV31,
        "material_state_hash",
        {
            "strategy_lifecycle_id": strategy_lifecycle_id,
            "market_episode_id": episode.market_episode_id,
            "symbol": episode.canonical_symbol,
            "state": "ANALYSIS_OPEN",
            "highest_analysis_authority": highest,
            "active_strategy_analysis_admission_id": active,
            "admission_lineage_ids": ids,
            "admission_lineage_classes": classes,
            "direction_state": episode_state.direction_state,
            "opened_at_utc": episode.opened_at,
            "last_event_at_utc": episode_state.last_event_at,
            "last_material_event_at_utc": episode_state.last_material_event_at,
            "active_context_epoch_id": None,
            "active_pressure_hypothesis_id": None,
        },
    )


def attach_admission_v31(
    ledger: InMemoryAnalysisLifecycleLedgerV31,
    *,
    episode: MarketEpisodeV31,
    episode_state: MarketEpisodeStateV31,
    admission: StrategyAnalysisAdmissionV31,
) -> LedgerDecisionV31:
    """§8.1: a GRANTED admission opens or joins the lifecycle of its market episode (never a second one)."""

    episode = MarketEpisodeV31.model_validate(episode.model_dump())
    episode_state = MarketEpisodeStateV31.model_validate(episode_state.model_dump())
    admission = StrategyAnalysisAdmissionV31.model_validate(admission.model_dump())
    if (admission.market_episode_id, episode_state.market_episode_id) != (
        episode.market_episode_id,
        episode.market_episode_id,
    ):
        return LedgerDecisionV31("NOT_ATTACHED", "ADMISSION_EPISODE_MISMATCH")
    lifecycle_id = strategy_lifecycle_id_from_episode_v31(episode.market_episode_id)
    chain = ledger.attachments.get(lifecycle_id, [])
    if any(a.strategy_analysis_admission_id == admission.strategy_analysis_admission_id for a in chain):
        return LedgerDecisionV31(
            "ALREADY_ATTACHED", "DUPLICATE_ATTACHMENT", view=lifecycle_view_v31(ledger, lifecycle_id, episode_state)
        )
    latest = ledger.latest_revision(admission.strategy_analysis_admission_id)
    if (
        latest is None
        or latest.admission_status != "GRANTED"
        or latest.admission_record_hash != strategy_analysis_admission_hash_v31(admission)
    ):
        return LedgerDecisionV31("NOT_ATTACHED", "ADMISSION_NOT_GRANTED_OR_NOT_RECORDED", latest)
    if episode_state.state == "CLOSED":
        return LedgerDecisionV31("NOT_ATTACHED", "MARKET_EPISODE_CLOSED", latest)

    previous_highest = derive_highest_authority_v31(tuple(a.admission_class for a in chain)) if chain else None
    previous_active = (
        lifecycle_view_v31(ledger, lifecycle_id, episode_state).active_strategy_analysis_admission_id if chain else None
    )
    ledger.episodes[lifecycle_id] = episode
    attachment = _hashed(
        LifecycleAttachmentV31,
        "attachment_hash",
        {
            "strategy_lifecycle_id": lifecycle_id,
            "market_episode_id": episode.market_episode_id,
            "sequence": len(chain) + 1,
            "strategy_analysis_admission_id": admission.strategy_analysis_admission_id,
            "admission_class": admission.admission_class,
            "attached_revision_id": latest.revision_id,
            "attached_at": admission.decided_at_utc,
            "previous_attachment_hash": chain[-1].attachment_hash if chain else None,
        },
    )
    ledger.attachments.setdefault(lifecycle_id, []).append(attachment)
    upgrade = None
    if (
        previous_highest is not None
        and previous_active is not None
        and AUTHORITY_RANK[admission.admission_class] > AUTHORITY_RANK[previous_highest]
    ):
        upgrade = _hashed(
            AuthorityUpgradeV31,
            "upgrade_hash",
            {
                "strategy_lifecycle_id": lifecycle_id,
                "market_episode_id": episode.market_episode_id,
                "symbol": episode.canonical_symbol,
                "from_authority": previous_highest,
                "to_authority": admission.admission_class,
                "trigger_admission_id": admission.strategy_analysis_admission_id,
                "superseded_active_admission_id": previous_active,
                "occurred_at": admission.decided_at_utc,
            },
        )
        ledger.upgrades.setdefault(lifecycle_id, []).append(upgrade)
    view = lifecycle_view_v31(ledger, lifecycle_id, episode_state)
    return LedgerDecisionV31("ATTACHED", "ADMISSION_ATTACHED", latest, view, upgrade)


def require_canonical_lineage_v31(view: AnalysisLifecycleV31, admission_id: UUID) -> str | None:
    """Guard for any canonical-path consumer: only a CANONICAL_RAW admission of THIS lifecycle is acceptable.

    An advisory-bound candidate is never reused after an upgrade (§7A.6); it must be re-evaluated canonically.
    """

    view = AnalysisLifecycleV31.model_validate(view.model_dump())
    lineage = dict(zip(view.admission_lineage_ids, view.admission_lineage_classes, strict=True))
    if admission_id not in lineage:
        return "ADMISSION_NOT_IN_LIFECYCLE"
    if lineage[admission_id] != "CANONICAL_RAW":
        return "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    return None


def lifecycle_progression_allowed_v31(
    view: AnalysisLifecycleV31, global_safety: GlobalSafetyStateV1
) -> tuple[bool, tuple[str, ...]]:
    """Global safety is an overlay (as in #492): it stops effective progression and never mutates history."""

    AnalysisLifecycleV31.model_validate(view.model_dump())
    vetoes = tuple(str(v) for v in global_safety.vetoes)
    return (not vetoes, vetoes)


def rebuild_lifecycles_v31(
    *,
    episodes: Iterable[tuple[MarketEpisodeV31, MarketEpisodeStateV31]],
    admissions: Iterable[StrategyAnalysisAdmissionV31],
) -> InMemoryAnalysisLifecycleLedgerV31:
    """Deterministic replay: any arrival order of the same decisions gives the same ledgers and views."""

    by_episode = {e.market_episode_id: (e, s) for e, s in episodes}
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    ordered = sorted(
        admissions,
        key=lambda a: (
            a.symbol,
            a.decided_at_utc,
            str(a.strategy_analysis_admission_id),
            strategy_analysis_admission_hash_v31(a),
        ),
    )
    for admission in ordered:
        decision = record_admission_revision_v31(ledger, admission)
        if decision.outcome == "RECORDED" and admission.admission_status == "GRANTED":
            episode, state = by_episode[admission.market_episode_id]
            attach_admission_v31(ledger, episode=episode, episode_state=state, admission=admission)
    return ledger


__all__ = [
    "InMemoryAnalysisLifecycleLedgerV31",
    "LedgerDecisionV31",
    "attach_admission_v31",
    "expire_admission_v31",
    "lifecycle_progression_allowed_v31",
    "lifecycle_view_v31",
    "rebuild_lifecycles_v31",
    "record_admission_revision_v31",
    "require_canonical_lineage_v31",
]
