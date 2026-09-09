"""Bind an explicitly supplied raw-ledger context to non-executable reports.

The caller owns coverage attestation. Neither a process buffer nor this adapter
can declare a raw ledger complete by hashing the rows it happens to hold.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from analysis.strategy_5scr_pair_activity import build_pair_activity_audit
from contracts.strategy_5scr_pair_activity import (
    FrozenActivityModel,
    PairActivityAuditV31,
    PairActivityEvaluationV31,
    PairActivityObservationNormalizationV1,
    PairActivityPolicyV31,
    RawActivityCoverageV31,
)


class PairActivityReportContextV31(FrozenActivityModel):
    coverage: RawActivityCoverageV31
    policy: PairActivityPolicyV31 | None = None
    decision_at_utc: datetime
    previous_evaluations: tuple[PairActivityEvaluationV31, ...] = ()


def build_pair_activity_report(
    raw_events: Iterable[Any],
    *,
    context: PairActivityReportContextV31 | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate only a caller-bound ledger; missing bindings stay unavailable."""
    if context is None:
        return {"status": "UNBOUND", "reason_code": "RAW_LEDGER_CONTEXT_UNBOUND", "execution_authority": False}
    payload = context.model_dump(mode="json") if isinstance(context, PairActivityReportContextV31) else context
    bound = PairActivityReportContextV31.model_validate(payload)
    audit = build_pair_activity_audit(
        raw_events,
        coverage=bound.coverage,
        policy=bound.policy,
        decision_at_utc=bound.decision_at_utc,
        previous_evaluations=bound.previous_evaluations,
    )
    return {"status": "EVALUATED", "audit": audit.model_dump(mode="json"), "execution_authority": False}


def pair_activity_observability_fields(*, symbol: str, report: Mapping[str, Any]) -> dict[str, Any]:
    """Carry validated activity receipts without substituting a legacy grant.

    The existing radar payload writer can retain this nested documentary field.
    No writer is invoked here, and no production persistence is inferred.
    """
    source = report.get("pair_activity_v31")
    fallback = {"status": "UNBOUND", "evaluations": [], "execution_authority": False}
    if not isinstance(source, Mapping):
        return {"pair_activity_v31": fallback}
    if source.get("status") != "EVALUATED":
        return {
            "pair_activity_v31": {
                **fallback,
                "status": str(source.get("status", "UNBOUND")),
                "reason_code": str(source.get("reason_code", "RAW_LEDGER_CONTEXT_UNBOUND")),
                "replay_required": True,
            }
        }
    try:
        if source.get("execution_authority") is not False:
            raise ValueError("activity envelope cannot carry execution authority")
        audit = PairActivityAuditV31.model_validate(source.get("audit"))
        normalized = None
        if "normalization" in source:
            payload = source["normalization"]
            if isinstance(payload, PairActivityObservationNormalizationV1):
                payload = payload.model_dump(mode="json")
            normalized = PairActivityObservationNormalizationV1.model_validate(payload)
            if (
                normalized.raw_population_hash != audit.source_ledger_hash
                or normalized.raw_event_count != audit.raw_event_count
            ):
                raise ValueError("activity normalization differs from audit population")
    except (ValidationError, ValueError, TypeError):
        return {"pair_activity_v31": {**fallback, "status": "INVALID_RECEIPT"}}
    selected = [item.model_dump(mode="json") for item in audit.evaluations if item.symbol == symbol.upper()]
    return {
        "pair_activity_v31": {
            "status": "EVALUATED",
            "rule_version": audit.rule_version,
            "evaluated_at_utc": audit.evaluated_at_utc.isoformat(),
            "coverage_status": audit.coverage_status,
            "provenance": _safe_activity_metadata(
                source.get("provenance"),
                {
                    "binding_hash",
                    "producer_id",
                    "source_scope_id",
                    "attestor_id",
                    "checkpoint_id",
                    "coverage_reason",
                    "source_revision",
                },
            ),
            "persistence": _safe_activity_metadata(
                source.get("persistence"),
                {"status", "boundary", "trigger", "replay_from_utc", "replay_scope", "raw_watermark"},
            ),
            "normalization": normalized.model_dump(mode="json") if normalized is not None else None,
            "replay_required": source.get("replay_required") is True
            or audit.coverage_status != "COMPLETE"
            or any(item.decision == "RECONCILIATION_REQUIRED" for item in audit.evaluations),
            "evaluations": selected,
            "hypothesis_authority": False,
            "risk_authority": False,
            "execution_authority": False,
        }
    }


def _safe_activity_metadata(value: object, allowed_keys: set[str]) -> dict[str, Any] | None:
    """Keep documentary scalar fields; nested claims cannot cross the adapter."""
    if not isinstance(value, Mapping):
        return None
    return {
        key: item for key, item in value.items() if key in allowed_keys and (item is None or type(item) in (str, int))
    }
