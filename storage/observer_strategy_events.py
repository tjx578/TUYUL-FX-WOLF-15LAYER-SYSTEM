"""Source-verbatim W1-A projections into the observer telemetry contract.

No function in this module evaluates strategy, risk, or execution.  Each
factory receives an already-validated source fact and projects only fields the
source owns.  Missing authority stays missing; in particular no producer for
``MATURE_ADVISORY`` exists until Wolf15 owns a durable canonical source for it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from contracts.observer_telemetry_export_v1 import (
    AnalysisLifecycleTransitionV1,
    CanonicalDecisionReasonV1,
    ContextEpochTransitionObserverV1,
    ObserverSourceEventRangeV1,
    ObserverSourceV1,
    ObserverTelemetryDraftV1,
    PairAdmissionEvaluationV3_1,
    StrategyAnalysisAdmissionV1,
    observer_draft,
    observer_source_from_env,
)
from contracts.strategy_5scr_context_epoch_v1 import (
    ContextTransitionV1,
    MaterialContextEvidenceV1,
    StrategyContextEpochV1,
)
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink, StrategyLifecycleV2
from contracts.strategy_5scr_pressure_radar import PressureRadarManifest
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    TradePlanCandidateBuildEvidenceV2,
    TradePlanEvaluationV2,
)

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


def _source(
    *,
    service: str,
    policy_version: str | None,
    deployment_id: str | None = None,
    source_commit_sha: str | None = None,
) -> ObserverSourceV1:
    commit = str(source_commit_sha or "").strip().lower()
    environ: dict[str, str] = {}
    if _COMMIT_SHA_RE.fullmatch(commit):
        environ["SOURCE_COMMIT_SHA"] = commit
    if deployment_id:
        environ["DEPLOYMENT_ID"] = deployment_id
    return observer_source_from_env(
        service=service,
        policy_version=policy_version,
        environ=environ,
    )


def _hashed_stream(namespace: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def pair_admission_evaluation_observer_draft(record: Mapping[str, Any]) -> ObserverTelemetryDraftV1:
    payload = dict(record["payload"])
    source_ids = tuple(str(value) for value in payload.get("source_ledger_event_ids") or ())
    if not source_ids:
        raise ValueError("pair admission observer export requires source ledger event IDs")
    decision_raw = str(record["decision"])
    if decision_raw not in {"GRANTED", "NOT_GRANTED"}:
        raise ValueError("pair admission observer export requires a canonical decision")
    decision = cast(Literal["GRANTED", "NOT_GRANTED"], decision_raw)
    evaluated_at = record["evaluated_at"]
    if not isinstance(evaluated_at, datetime):
        raise ValueError("pair admission observer export requires evaluated_at")
    body = PairAdmissionEvaluationV3_1(
        symbol=str(record["symbol"]),
        raw_block_id=str(record["raw_block_id"]),
        evaluation_id=str(record["evaluation_id"]),
        coverage_status="EVALUATED",
        decision=decision,
        reason_code=record.get("reason"),
        rule_version=str(record["rule_version"]),
        evaluated_at_utc=evaluated_at,
        source_event_range=ObserverSourceEventRangeV1(
            first_event_id=source_ids[0],
            last_event_id=source_ids[-1],
            first_occurred_at_utc=record["started_at"],
            last_occurred_at_utc=record["latest_at"],
            event_count=len(source_ids),
        ),
        source_event_ids=source_ids,
    )
    deployment_id = str(record["deployment_id"])
    return observer_draft(
        logical_event_key=body.evaluation_id,
        stream_id=_hashed_stream(
            "pair-admission",
            f"{deployment_id}|{body.raw_block_id}",
        ),
        occurred_at_utc=evaluated_at,
        source=_source(
            service="strategy-5scr-pair-admission",
            policy_version=body.rule_version,
            deployment_id=deployment_id,
            source_commit_sha=payload.get("commit_sha"),
        ),
        body=body,
    )


def strategy_analysis_admission_observer_draft(
    manifest: PressureRadarManifest,
    *,
    occurred_at_utc: datetime,
    source_commit_sha: str | None,
) -> ObserverTelemetryDraftV1:
    if manifest.status != "ANALYSIS_READY" or manifest.pair_admission_id is None:
        raise ValueError("only an ANALYSIS_READY manifest owns canonical raw analysis admission")
    if manifest.pair_admission_rule_version is None:
        raise ValueError("analysis-ready manifest is missing its pair-admission rule")
    body = StrategyAnalysisAdmissionV1(
        analysis_admission_id=f"5scr-analysis-admission:{manifest.manifest_id}",
        authority_scope_id=manifest.pair_admission_id,
        symbol=manifest.symbol,
        admission_class="CANONICAL_RAW",
        decision="ADMITTED",
        rule_version=manifest.pair_admission_rule_version,
        admitted_at_utc=occurred_at_utc,
        next_required_stage=manifest.next_required_stage,
        source_event_ids=tuple(sorted(set(manifest.observed_event_ids))),
    )
    return observer_draft(
        logical_event_key=f"{manifest.manifest_id}|ANALYSIS_READY",
        stream_id=f"strategy-analysis-admission:{manifest.pair_admission_id}",
        occurred_at_utc=occurred_at_utc,
        source=_source(
            service="strategy-5scr-pressure-radar",
            policy_version=manifest.gate_rule_version,
            deployment_id=manifest.deployment_id,
            source_commit_sha=source_commit_sha,
        ),
        body=body,
    )


def analysis_lifecycle_transition_observer_draft(
    lifecycle: StrategyLifecycleV2,
    link: StrategyLifecycleEventLink,
    *,
    previous_state: str | None,
) -> ObserverTelemetryDraftV1:
    body = AnalysisLifecycleTransitionV1(
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        symbol=lifecycle.symbol,
        previous_state=previous_state,
        new_state=lifecycle.state,
        reason_code=link.link_reason,
        transition_time_utc=link.linked_at_utc,
        source_event_ids=(link.pressure_event_id,),
    )
    return observer_draft(
        logical_event_key=(
            f"{lifecycle.strategy_lifecycle_id}|{previous_state or 'NONE'}|{lifecycle.state}|{link.pressure_event_id}"
        ),
        stream_id=f"analysis-lifecycle:{lifecycle.strategy_lifecycle_id}",
        occurred_at_utc=link.linked_at_utc,
        source=_source(
            service="strategy-5scr-lifecycle-v2-shadow",
            policy_version=lifecycle.rule_version,
        ),
        body=body,
    )


def context_epoch_transition_observer_draft(
    transition: ContextTransitionV1,
    epoch: StrategyContextEpochV1,
    evidence: MaterialContextEvidenceV1,
) -> ObserverTelemetryDraftV1:
    affected_epoch_id = transition.to_context_epoch_id or transition.from_context_epoch_id
    body = ContextEpochTransitionObserverV1(
        context_epoch_id=affected_epoch_id,
        strategy_lifecycle_id=transition.strategy_lifecycle_id,
        previous_epoch_id=transition.from_context_epoch_id,
        material_context_hash=transition.material_context_hash,
        direction_domain=epoch.direction_domain,
        route=epoch.allowed_routes,
        target_map_version=epoch.target_map_version,
        transition_reason=transition.reason,
        transition_time_utc=transition.occurred_at_utc,
        source_event_ids=transition.source_event_ids,
    )
    return observer_draft(
        logical_event_key=transition.transition_id,
        stream_id=f"analysis-lifecycle:{transition.strategy_lifecycle_id}",
        occurred_at_utc=transition.occurred_at_utc,
        source=_source(
            service="strategy-5scr-context-epoch-v1-shadow",
            policy_version=epoch.contract_version,
            deployment_id=evidence.source_deployment_id,
        ),
        body=body,
    )


def canonical_tradeplan_decision_observer_draft(
    evaluation: TradePlanEvaluationV2,
    evidence: TradePlanCandidateBuildEvidenceV2,
) -> ObserverTelemetryDraftV1:
    refs = {
        evaluation.source_request_id,
        evaluation.strategy_lifecycle_id,
        evaluation.context_epoch_id,
        evaluation.strategy_thesis_id,
        evaluation.execution_box_id,
        evaluation.evidence_hash,
        evaluation.material_evaluation_hash,
    }
    if evaluation.result_tradeplan_id is not None:
        refs.add(evaluation.result_tradeplan_id)
    body = CanonicalDecisionReasonV1(
        decision_id=evaluation.evaluation_id,
        strategy_lifecycle_id=evaluation.strategy_lifecycle_id,
        authority_scope_id=evaluation.execution_box_id,
        stage="TRADEPLAN_CANDIDATE_V2",
        decision=evaluation.decision,
        reason_code=evaluation.reason_codes[0],
        reason_codes=evaluation.reason_codes,
        next_required_stage=None,
        evidence_refs=tuple(sorted(refs)),
        decided_at_utc=evaluation.decision_at_utc,
    )
    return observer_draft(
        logical_event_key=evaluation.evaluation_id,
        stream_id=f"analysis-lifecycle:{evaluation.strategy_lifecycle_id}",
        occurred_at_utc=evaluation.decision_at_utc,
        source=_source(
            service="strategy-5scr-tradeplan-candidate-v2",
            policy_version=evaluation.rule_version,
            deployment_id=evidence.source_deployment_id,
        ),
        body=body,
    )


__all__ = [
    "analysis_lifecycle_transition_observer_draft",
    "canonical_tradeplan_decision_observer_draft",
    "context_epoch_transition_observer_draft",
    "pair_admission_evaluation_observer_draft",
    "strategy_analysis_admission_observer_draft",
]
