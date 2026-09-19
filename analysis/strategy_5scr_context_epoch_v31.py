"""Pure gap #9 producer: context epoch resolution, route evaluation and positive receipt projection.

No database, worker, wall clock, broker or quote feed: quote authority, location alignment and material context
are explicit inputs. No liquidity FSM (§13) and no rejection/resolution logic (§12.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from contracts.strategy_5scr_context_epoch_v31 import (
    ROUTE_PERMITTING_OUTCOMES,
    ContextClockPolicyV31,
    ContextEpochTerminationV31,
    ContextEpochV31,
    ContextRouteEvaluationV31,
    DirectionDomainRegistryV31,
    LocationRoutePolicyV31,
    context_epoch_id_v31,
    context_route_evaluation_id_v31,
)
from contracts.strategy_5scr_context_route_v31 import (
    ContextRouteReceiptV31,
    MaterialContextV31,
    material_context_hash_v31,
)
from contracts.strategy_5scr_pressure_hypothesis_v31 import PressureDirectionalHypothesisV31, canonical_sha256_v31


@dataclass(frozen=True)
class EpochResolutionV31:
    outcome: Literal["REUSED", "CREATED", "NOT_CREATED"]
    reason_code: str
    epoch: ContextEpochV31 | None = None
    termination: ContextEpochTerminationV31 | None = None


def resolve_context_epoch_v31(
    *,
    strategy_lifecycle_id: UUID,
    canonical_symbol: str,
    material: MaterialContextV31,
    source_closed_through: datetime,
    registry: DirectionDomainRegistryV31 | None,
    clock_policy: ContextClockPolicyV31 | None,
    previous: ContextEpochV31 | None,
    previous_terminated: bool,
    decision_at: datetime,
) -> EpochResolutionV31:
    """Same material + live epoch → REUSED. Changed material → new epoch; the old one is SUPERSEDED.
    Expired epoch + unchanged material → NOT_CREATED (a terminal epoch is never revived under its own id)."""

    if registry is None:
        return EpochResolutionV31("NOT_CREATED", "REGISTRY_MISSING")
    if clock_policy is None:
        return EpochResolutionV31("NOT_CREATED", "CONTEXT_CLOCK_POLICY_MISSING")
    material = MaterialContextV31.model_validate(material.model_dump())
    allowed = registry.directions_for(material.primary_direction_domain)
    if allowed is None or not set(material.allowed_directions) <= set(allowed):
        return EpochResolutionV31("NOT_CREATED", "DIRECTION_DOMAIN_NOT_IN_REGISTRY")
    material_hash = material_context_hash_v31(canonical_symbol, material)
    termination = None
    if previous is not None and previous.strategy_lifecycle_id == strategy_lifecycle_id:
        expired = decision_at >= previous.valid_until
        if previous.material_context_hash == material_hash:
            if previous_terminated or expired:
                return EpochResolutionV31("NOT_CREATED", "EPOCH_EXPIRED_MATERIAL_UNCHANGED")
            return EpochResolutionV31("REUSED", "MATERIAL_CONTEXT_UNCHANGED", previous)
        new_id = context_epoch_id_v31(strategy_lifecycle_id=strategy_lifecycle_id, material_context_hash=material_hash)
        if not previous_terminated:
            termination = ContextEpochTerminationV31(
                context_epoch_id=previous.context_epoch_id,
                terminal_state="EXPIRED" if expired else "SUPERSEDED",
                reason_code="CONTEXT_EPOCH_CLOCK_EXPIRED" if expired else "MATERIAL_CONTEXT_CHANGED",
                superseded_by=None if expired else new_id,
                terminated_at=decision_at if not expired else previous.valid_until,
            )
    epoch = ContextEpochV31(
        context_epoch_id=context_epoch_id_v31(
            strategy_lifecycle_id=strategy_lifecycle_id, material_context_hash=material_hash
        ),
        strategy_lifecycle_id=strategy_lifecycle_id,
        canonical_symbol=canonical_symbol,
        material=material,
        material_context_hash=material_hash,
        direction_domain_registry_version=registry.registry_version,
        direction_domain_registry_hash=registry.registry_hash,
        source_closed_through=source_closed_through,
        valid_from=decision_at,
        valid_until=decision_at + timedelta(seconds=clock_policy.ttl_seconds),
        clock_policy_version=clock_policy.clock_policy_version,
        clock_policy_hash=clock_policy.policy_hash,
    )
    return EpochResolutionV31("CREATED", "CONTEXT_EPOCH_CREATED", epoch, termination)


@dataclass(frozen=True)
class RouteEvaluationDecisionV31:
    outcome: Literal["EVALUATED", "NOT_EVALUATED"]
    reason_code: str
    evaluation: ContextRouteEvaluationV31 | None = None


def evaluate_context_route_v31(
    *,
    epoch: ContextEpochV31,
    evaluated_direction: Literal["BUY", "SELL"],
    hypothesis: PressureDirectionalHypothesisV31 | None,
    pressure_direction: Literal["BUY", "SELL"] | None,
    requested_route: str,
    location_alignment: Literal["FAVORABLE", "NEUTRAL", "UNFAVORABLE", "UNKNOWN"],
    quote_authoritative: bool,
    registry: DirectionDomainRegistryV31 | None,
    policy: LocationRoutePolicyV31 | None,
    decision_at: datetime,
    invalidating_material_event_hash: str | None = None,
) -> RouteEvaluationDecisionV31:
    """Evaluate the epoch for one direction. Never changes the hypothesis; never picks a direction."""

    if registry is None or policy is None:
        return RouteEvaluationDecisionV31("NOT_EVALUATED", "REGISTRY_MISSING")
    if (registry.registry_version, registry.registry_hash) != (
        epoch.direction_domain_registry_version,
        epoch.direction_domain_registry_hash,
    ):
        return RouteEvaluationDecisionV31("NOT_EVALUATED", "REGISTRY_VERSION_MISMATCH")
    if not epoch.valid_from <= decision_at < epoch.valid_until:
        return RouteEvaluationDecisionV31("NOT_EVALUATED", "CONTEXT_EPOCH_NOT_ACTIVE")
    if hypothesis is not None:
        if (hypothesis.strategy_lifecycle_id, hypothesis.canonical_symbol) != (
            epoch.strategy_lifecycle_id,
            epoch.canonical_symbol,
        ):
            return RouteEvaluationDecisionV31("NOT_EVALUATED", "HYPOTHESIS_SCOPE_MISMATCH")
        if hypothesis.direction != evaluated_direction or pressure_direction not in {None, hypothesis.direction}:
            return RouteEvaluationDecisionV31("NOT_EVALUATED", "HYPOTHESIS_DIRECTION_IS_NOT_EVALUABLE_HERE")
        pressure_direction = hypothesis.direction

    material = epoch.material
    counter = pressure_direction is not None and evaluated_direction != pressure_direction
    classification = material.counter_pressure_thesis_status if counter else None
    rule = policy.rule(requested_route, evaluated_direction)
    selected: str | None = None
    defer_reason: str | None = None
    if invalidating_material_event_hash is not None:
        outcome, alignment, reason = "INVALIDATE", "CONFLICT", "MATERIAL_EVIDENCE_INVALIDATES"
    elif material.primary_direction_domain == "EMPTY":
        outcome, alignment, reason = "BLOCK_ROUTE", "EMPTY", "DIRECTION_DOMAIN_EMPTY"
    elif material.primary_direction_domain == "UNRESOLVED":
        outcome, alignment, reason, defer_reason = (
            "DEFER",
            "UNRESOLVED",
            "DIRECTION_DOMAIN_UNRESOLVED",
            "DOMAIN_UNRESOLVED",
        )
    elif evaluated_direction not in material.allowed_directions and not counter:
        outcome, alignment, reason = "CONFLICT", "CONFLICT", "DIRECTION_OUTSIDE_LEGAL_DOMAIN"
    elif counter and classification == "PROHIBITED":
        outcome, alignment, reason = "BLOCK_ROUTE", "CONFLICT", "COUNTER_PRESSURE_PROHIBITED"
    elif requested_route in material.blocked_routes or requested_route not in material.allowed_routes or rule is None:
        outcome, alignment, reason = "BLOCK_ROUTE", "CONFLICT" if counter else "ALIGNED", "ROUTE_NOT_PERMITTED"
    elif rule.requires_authoritative_quote and not quote_authoritative:
        # A stale / non-authoritative quote pauses progression; it never makes context or route illegal.
        outcome, alignment, reason, defer_reason = "DEFER", "ALIGNED", "QUOTE_NOT_AUTHORITATIVE", "PRICE_QUALITY"
    elif location_alignment not in rule.permitted_location_alignments:
        outcome, alignment, reason, defer_reason = "DEFER", "ALIGNED", "LOCATION_NOT_READY", "LOCATION_NOT_READY"
    elif counter:
        outcome, alignment, reason, selected = (
            "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE",
            "CONFLICT",
            "COUNTER_PRESSURE_PROOF_REQUIRED",
            requested_route,
        )
    else:
        outcome, alignment, reason, selected = "ALIGN", "ALIGNED", "CONTEXT_ALIGNED", requested_route

    evidence = canonical_sha256_v31(
        {
            "epoch": str(epoch.context_epoch_id),
            "material_context_hash": epoch.material_context_hash,
            "direction": evaluated_direction,
            "route": requested_route,
            "location_alignment": location_alignment,
            "quote_authoritative": quote_authoritative,
            "policy_hash": policy.policy_hash,
            "invalidating_material_event_hash": invalidating_material_event_hash,
        }
    )
    hypothesis_id = hypothesis.pressure_hypothesis_id if hypothesis is not None else None
    evaluation = ContextRouteEvaluationV31(
        evaluation_id=context_route_evaluation_id_v31(
            context_epoch_id=epoch.context_epoch_id,
            evaluated_direction=evaluated_direction,
            pressure_hypothesis_id=hypothesis_id,
        ),
        context_epoch_id=epoch.context_epoch_id,
        strategy_lifecycle_id=epoch.strategy_lifecycle_id,
        canonical_symbol=epoch.canonical_symbol,
        evaluated_direction=evaluated_direction,
        pressure_hypothesis_id=hypothesis_id,
        direction_domain_registry_version=registry.registry_version,
        location_route_policy_version=policy.policy_version,
        location_route_policy_hash=policy.policy_hash,
        route_registry_version=policy.route_registry_version,
        location_alignment=location_alignment,
        context_alignment=alignment,
        counter_pressure_classification=classification,
        quote_authoritative=quote_authoritative,
        outcome=outcome,
        reason_code=reason,
        defer_reason=defer_reason,
        selected_route=selected,
        resolution_evidence_hash=evidence,
        evaluated_at=decision_at,
    )
    return RouteEvaluationDecisionV31("EVALUATED", reason, evaluation)


def project_context_route_receipt_v31(
    epoch: ContextEpochV31, evaluation: ContextRouteEvaluationV31
) -> ContextRouteReceiptV31 | None:
    """Positive handoff projection only. CONFLICT/DEFER/BLOCK_ROUTE/INVALIDATE never produce a receipt."""

    if evaluation.outcome not in ROUTE_PERMITTING_OUTCOMES or evaluation.selected_route is None:
        return None
    if evaluation.context_epoch_id != epoch.context_epoch_id:
        raise ValueError("EVALUATION_EPOCH_MISMATCH")
    return ContextRouteReceiptV31(
        profile="TEST_ONLY",
        context_epoch_id=epoch.context_epoch_id,
        strategy_lifecycle_id=epoch.strategy_lifecycle_id,
        symbol=epoch.canonical_symbol,
        state="ACTIVE",
        material=epoch.material,
        material_context_hash=epoch.material_context_hash,
        registry_version=epoch.direction_domain_registry_version,
        location_route_policy_hash=evaluation.location_route_policy_hash,
        location_alignment=evaluation.location_alignment,
        selected_route=evaluation.selected_route,
        direction=evaluation.evaluated_direction,
        resolution_evidence_hash=evaluation.resolution_evidence_hash,
        source_closed_through=epoch.source_closed_through,
        evaluated_at=evaluation.evaluated_at,
        valid_until=epoch.valid_until,
    )


@dataclass(frozen=True)
class HypothesisTransitionIntentV31:
    to_state: str
    context_alignment: str
    location_alignment: str
    classification: str | None


def hypothesis_transition_for_evaluation_v31(
    evaluation: ContextRouteEvaluationV31,
) -> HypothesisTransitionIntentV31 | None:
    """Owner mapping (2026-09-19). None = no hypothesis state change (progression is blocked at route level).
    Direction is not part of the intent: context never turns BUY into SELL."""

    if evaluation.pressure_hypothesis_id is None:
        return None
    outcome, loc = evaluation.outcome, evaluation.location_alignment
    if outcome == "ALIGN":
        return HypothesisTransitionIntentV31("CONTEXT_ALIGNED", "ALIGNED", loc, None)
    if outcome == "CONFLICT":
        return HypothesisTransitionIntentV31("CONTEXT_CONFLICT", "CONFLICT", loc, "COUNTER_PRESSURE_PENDING_PROOF")
    if outcome == "DEFER" and evaluation.defer_reason == "PRICE_QUALITY":
        return HypothesisTransitionIntentV31("WAITING_PRICE_QUALITY", evaluation.context_alignment, loc, None)
    if outcome == "DEFER" and evaluation.defer_reason == "LOCATION_NOT_READY" and loc in {"UNFAVORABLE", "UNKNOWN"}:
        return HypothesisTransitionIntentV31("WAITING_VALID_LOCATION", evaluation.context_alignment, loc, None)
    if outcome == "INVALIDATE":
        return HypothesisTransitionIntentV31("INVALIDATED", "CONFLICT", loc, None)
    return None  # BLOCK_ROUTE, domain-unresolved DEFER, NEUTRAL-location DEFER, counter-pressure route


__all__ = [
    "EpochResolutionV31",
    "HypothesisTransitionIntentV31",
    "RouteEvaluationDecisionV31",
    "evaluate_context_route_v31",
    "hypothesis_transition_for_evaluation_v31",
    "project_context_route_receipt_v31",
    "resolve_context_epoch_v31",
]
