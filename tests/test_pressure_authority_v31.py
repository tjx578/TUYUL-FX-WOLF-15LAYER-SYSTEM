from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_pressure_authority_v31 import (
    PressureAuthorityV31,
    PressureDirectionDecisionV31,
    PressurePolicyBindingV31,
    evaluate_pressure_direction,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def source(**updates):
    payload = {
        "symbol": "EURUSD",
        "source_event_ids": ["fixture-event-1"],
        "pressure_authority_mode": "RADAR_ONLY",
        "pressure_contract_status": "OPEN",
        "pressure_contract_version": "fixture-producer-contract/v1",
        "pressure_contract_invalidated_at": None,
        "observed_at_utc": NOW - timedelta(seconds=10),
        "valid_until_utc": NOW + timedelta(seconds=10),
        "raw_direction": "BUY",
        "candidate_direction": "BUY",
        "watch_direction": "BUY",
        "block_direction": "BUY",
        "direction_lineage_alignment": "ALIGNED",
        "pressure_consensus_status": "BUY",
    }
    payload.update(updates)
    return PressureAuthorityV31.model_validate(payload)


def policy(**updates):
    payload = {
        "approval_state": "APPROVED",
        "policy_id": "fixture-only/pressure-policy/v1",
        "policy_digest": "sha256:" + "1" * 64,
        "approved_at_utc": NOW - timedelta(seconds=20),
        "valid_until_utc": NOW + timedelta(seconds=20),
    }
    payload.update(updates)
    return PressurePolicyBindingV31.model_validate(payload)


def decide(value=None, **kwargs):
    return evaluate_pressure_direction(
        value or source(),
        policy=kwargs.pop("policy", policy()),
        requested_direction=kwargs.pop("requested_direction", "BUY"),
        decision_at_utc=kwargs.pop("decision_at_utc", NOW),
        **kwargs,
    )


@pytest.mark.parametrize(
    "mode,alignment,consensus,requested",
    list(
        product(
            ["RADAR_ONLY", "CONSOLIDATED_DIRECTION_CONTRACT"],
            ["ALIGNED", "CONFLICT", "UNAVAILABLE"],
            ["BUY", "SELL", "CONFLICT", "INCOMPLETE", "STALE"],
            ["BUY", "SELL"],
        )
    ),
)
def test_pressure_direction_table(mode, alignment, consensus, requested):
    direction = consensus if consensus in {"BUY", "SELL"} else "BUY"
    updates = dict.fromkeys(["raw_direction", "candidate_direction", "watch_direction", "block_direction"], direction)
    if alignment == "CONFLICT":
        updates["block_direction"] = "SELL" if direction == "BUY" else "BUY"
    elif alignment == "UNAVAILABLE":
        updates["block_direction"] = None
    if mode == "CONSOLIDATED_DIRECTION_CONTRACT":
        updates.update(
            pressure_contract_status="LOCKED",
            contract_direction=direction,
            formal_transition_event_id="fixture-event-1",
        )
    result = decide(
        source(
            pressure_authority_mode=mode,
            direction_lineage_alignment=alignment,
            pressure_consensus_status=consensus,
            **updates,
        ),
        requested_direction=requested,
    )
    assert result.pressure_direction_gate_passed is (alignment == "ALIGNED" and consensus == requested)
    assert result.separate_route_gate_passed is False
    assert result.separate_route_reason == "SEPARATE_ROUTE_POLICY_UNRESOLVED"
    assert result.hypothesis_authority is result.risk_authority is result.execution_authority is False


@pytest.mark.parametrize("state", ["UNBOUND", "REVOKED"])
def test_unapproved_binding_denies(state):
    assert not decide(policy=policy(approval_state=state)).pressure_direction_gate_passed
    assert not decide(policy=None).pressure_direction_gate_passed


@pytest.mark.parametrize("field", ["policy_id", "policy_digest", "approved_at_utc", "valid_until_utc"])
def test_approval_requires_explicit_evidence(field):
    with pytest.raises(ValidationError):
        policy(**{field: None})


@pytest.mark.parametrize(
    "updates",
    [
        {"approved_at_utc": NOW + timedelta(seconds=1)},
        {"valid_until_utc": NOW},
    ],
)
def test_policy_future_or_expired_denies(updates):
    assert decide(policy=policy(**updates)).reason_code == "PRESSURE_POLICY_NOT_CURRENT"


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"observed_at_utc": NOW + timedelta(seconds=1)}, "FUTURE_PRESSURE_EVIDENCE"),
        ({"valid_until_utc": NOW}, "PRESSURE_EVIDENCE_EXPIRED"),
        ({"pressure_contract_status": "EXPIRED"}, "PRESSURE_EVIDENCE_EXPIRED"),
        ({"pressure_contract_status": "TRANSITION_PENDING"}, "PRESSURE_CONTRACT_NOT_OPEN"),
        ({"pressure_contract_invalidated_at": NOW}, "CONTRACT_INVALIDATED"),
        ({"pressure_contract_invalidated_at": NOW + timedelta(seconds=1)}, "FUTURE_INVALIDATION_EVIDENCE"),
    ],
)
def test_asof_and_contract_state_denials(updates, reason):
    assert decide(source(**updates)).reason_code == reason


def test_aligned_labels_never_infer_consolidated_lock():
    result = decide(source(pressure_authority_mode="CONSOLIDATED_DIRECTION_CONTRACT"))
    assert result.reason_code == "CONSOLIDATED_DIRECTION_NOT_AUTHORIZED"


@pytest.mark.parametrize("requested", ["BUY", "SELL"])
def test_lock_and_current_pressure_disagreement_authorize_neither_direction(requested):
    value = source(
        pressure_authority_mode="CONSOLIDATED_DIRECTION_CONTRACT",
        pressure_contract_status="LOCKED",
        contract_direction="SELL",
        formal_transition_event_id="fixture-event-1",
    )
    assert not decide(value, requested_direction=requested).pressure_direction_gate_passed


@pytest.mark.parametrize(
    "updates",
    [
        {"pressure_contract_status": "LOCKED"},
        {"pressure_contract_status": "INVALIDATED"},
        {"contract_direction": "BUY"},
        {"direction_lineage_alignment": "CONFLICT"},
        {"pressure_consensus_status": "SELL"},
        {"source_event_ids": ["fixture-event-1", "fixture-event-1"]},
        {"source_event_ids": [" "]},
        {"pressure_contract_version": " "},
        {"observed_at_utc": NOW.replace(tzinfo=None)},
        {"valid_until_utc": NOW - timedelta(seconds=10)},
        {"execution_authority": True},
        {"legacy_grant": "not-authority"},
    ],
)
def test_invalid_source_examples_rejected(updates):
    with pytest.raises(ValidationError):
        source(**updates)


@pytest.mark.parametrize("field", ["pressure_contract_version", "pressure_contract_invalidated_at"])
def test_source_contract_fields_required_even_when_nullable(field):
    payload = source().model_dump(mode="json")
    del payload[field]
    with pytest.raises(ValidationError):
        PressureAuthorityV31.model_validate(payload)


def test_consolidated_lock_requires_source_bound_transition():
    for transition in (None, "unknown-event"):
        with pytest.raises(ValidationError):
            source(
                pressure_authority_mode="CONSOLIDATED_DIRECTION_CONTRACT",
                pressure_contract_status="LOCKED",
                contract_direction="BUY",
                formal_transition_event_id=transition,
            )


def test_version_and_invalidation_change_evidence_hash():
    baseline = decide()
    assert (
        decide(source(pressure_contract_version="fixture-producer-contract/v2")).evidence_hash != baseline.evidence_hash
    )
    changed = decide(source(pressure_contract_invalidated_at=NOW))
    assert changed.evidence_hash != baseline.evidence_hash
    assert not changed.pressure_direction_gate_passed


def test_instance_copy_bypass_revalidated():
    with pytest.raises(ValidationError):
        decide(source().model_copy(update={"execution_authority": True}))
    with pytest.raises(ValidationError):
        decide(policy=policy().model_copy(update={"policy_digest": None}))


def test_valid_example_roundtrip_and_schema_requirements():
    original = source()
    assert PressureAuthorityV31.model_validate_json(original.model_dump_json()) == original
    assert decide(PressureAuthorityV31.model_validate_json(original.model_dump_json())) == decide(original)
    schema = PressureAuthorityV31.model_json_schema()
    assert {"pressure_contract_version", "pressure_contract_invalidated_at"} <= set(schema["required"])
    assert schema["additionalProperties"] is False
    result = decide().model_dump(mode="json")
    for flag in ("hypothesis_authority", "risk_authority", "execution_authority", "separate_route_gate_passed"):
        with pytest.raises(ValidationError):
            PressureDirectionDecisionV31.model_validate({**result, flag: True})


def test_wrong_direction_or_naive_decision_rejected():
    with pytest.raises(ValueError):
        decide(requested_direction="WAIT")
    with pytest.raises(ValueError):
        decide(decision_at_utc=NOW.replace(tzinfo=None))
