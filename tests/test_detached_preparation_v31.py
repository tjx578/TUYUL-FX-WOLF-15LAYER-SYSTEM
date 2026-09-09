"""Detached preparation integrity and fixed-deadline checks, without authority."""

from dataclasses import replace
from datetime import timedelta

import pytest

from contracts.strategy_5scr_candidate_revision_v31 import StoredCandidateRevisionV31
from storage import strategy_5scr_prepared_v31 as detached
from tests.test_strategy_5scr_candidate_handoff_v31 import NOW, bundle
from tests.test_strategy_5scr_candidate_revision_v31 import prepared, revision


def test_sealed_preparation_roundtrip_is_independent_test_only_value():
    issuer = object()
    value = prepared(revision())
    binding = {"revision": 1, "owner": "test-owner"}
    token = detached.seal_v31(issuer, "append", binding, value)
    recovered = detached.unseal_v31(token, issuer, "append", binding, StoredCandidateRevisionV31)
    assert recovered == value
    assert recovered is not value
    assert recovered.request.profile == "TEST_ONLY"
    candidate = recovered.request.handoff.candidate
    assert candidate.valid_for_execution is False
    assert candidate.execution_command_allowed is False
    assert candidate.final_signal_allowed is False


@pytest.mark.parametrize("fault", ["issuer", "operation", "binding", "payload", "signature", "missing"])
def test_detached_preparation_rejects_rebound_or_tampered_value(fault):
    issuer = object()
    value = prepared(revision())
    binding = {"revision": 1}
    token = detached.seal_v31(issuer, "append", binding, value)
    operation = "append"
    if fault == "issuer":
        issuer = object()
    elif fault == "operation":
        operation = "reserve"
    elif fault == "binding":
        binding["revision"] = 2
    elif fault == "payload":
        token = replace(token, payload=prepared(revision(advisory=True)).model_dump_json())
    elif fault == "signature":
        token = replace(token, signature="0" * 64)
    else:
        token = None
    with pytest.raises(ValueError, match="DETACHED_PREPARATION_BINDING_MISMATCH"):
        detached.unseal_v31(token, issuer, operation, binding, StoredCandidateRevisionV31)


@pytest.mark.parametrize("nested", [False, True])
def test_guard_detects_verifier_mutating_supplied_object(nested):
    request = revision()

    def mutate(body):
        if nested:
            object.__setattr__(body.handoff.candidate, "tradeplan_revision", 7)
        else:
            object.__setattr__(body, "reevaluation_receipt_hash", "sha256:" + "f" * 64)
        return True

    with pytest.raises(ValueError, match="DETACHED_VERIFIER_INPUT_CHANGED"):
        detached.guard_callback_v31(mutate)(request)


def test_guard_preserves_rejection_and_missing_verifier():
    assert detached.guard_callback_v31(None) is None
    assert detached.guard_callback_v31(lambda *_: False)(revision()) is False


@pytest.mark.parametrize("field", ["reservation", "handoff", "cost", "snapshot", "risk_state"])
def test_commit_freshness_rejects_expired_evidence_without_extending_deadline(field):
    _, handoff, request = bundle()
    expires = NOW + timedelta(seconds=1)
    if field == "reservation":
        checked = expires
        reason = "RESERVATION_EXPIRED"
    else:
        checked = NOW
        expires = NOW + timedelta(seconds=1)
        if field == "handoff":
            handoff = handoff.model_copy(update={"handoff_receipt_valid_until": NOW})
            reason = "RECEIPT_EXPIRED"
        elif field == "cost":
            costs = request.geometry.costs.model_copy(update={"valid_until": NOW})
            request = request.model_copy(update={"geometry": request.geometry.model_copy(update={"costs": costs})})
            reason = "COST_EXPIRED"
        elif field == "snapshot":
            snapshot = request.snapshot.model_copy(
                update={"captured_at_utc": NOW - timedelta(seconds=request.policy.snapshot_max_age_seconds + 1)}
            )
            request = request.model_copy(update={"snapshot": snapshot})
            reason = "SNAPSHOT_STALE"
        else:
            request = request.model_copy(
                update={
                    "risk_state_captured_at": NOW - timedelta(seconds=request.policy.risk_state_max_age_seconds + 1)
                }
            )
            reason = "RISK_STATE_STALE"
    original_request = request.model_dump_json()
    original_handoff = handoff.model_dump_json()
    with pytest.raises(ValueError, match=reason):
        detached.fresh_parent_v31(request, handoff, expires, checked)
    assert request.model_dump_json() == original_request
    assert handoff.model_dump_json() == original_handoff


@pytest.mark.parametrize("callback", [None, lambda *_: True])
def test_transaction_boundary_rejects_verifier_argument_even_when_empty(callback):
    with pytest.raises(ValueError, match="EXTERNAL_VERIFIER_REQUIRES_DETACHED_PREPARATION"):
        detached.reject_callbacks_v31({"verify_risk_inputs": callback})
