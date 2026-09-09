from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from uuid import UUID

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_target_selection_v31 import solve_target_geometry_v31, target_universe_hash_v31
from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31, TradePlanCandidateV31
from contracts.strategy_5scr_context_route_v31 import (
    ContextRouteReceiptV31,
    context_route_receipt_hash_v31,
    material_context_hash_v31,
)
from contracts.strategy_5scr_net_geometry_v31 import NetGeometryContextV31, NetGeometryRequestV31
from contracts.strategy_5scr_target_selection_v31 import TargetUniverseV31
from risk.strategy_5scr_candidate_handoff_v31 import candidate_handoff_hash_v31, propose_canonical_parent_v31
from risk.strategy_5scr_capacity_v31 import CapacityRejectedError
from risk.strategy_5scr_risk_adapter_v31 import parent_sizing_request_hash_v31
from tests.test_strategy_5scr_capacity_v31 import NOW, H, request_for, seed
from tests.test_strategy_5scr_context_route_v31 import receipt as context_fixture
from tests.test_strategy_5scr_net_geometry_v31 import request_data
from tests.test_strategy_5scr_target_selection_v31 import fixture as target_fixture


def bundle(direction="BUY"):
    ledger = seed()
    request = request_for(ledger)
    request = request.model_copy(
        update={"geometry": NetGeometryRequestV31.model_validate(request_data(direction, cost_ticks=1))}
    )
    universe_data, _ = target_fixture(direction)
    universe_data["targets"][0]["target_id"] = str(UUID(int=9))
    universe_data["targets"][1]["target_id"] = str(UUID(int=10))
    universe = TargetUniverseV31.model_validate(universe_data)
    universe_hash = target_universe_hash_v31(universe)
    geometry = request.geometry.model_copy(update={"target_evidence_hash": universe_hash})
    solved = solve_target_geometry_v31(
        universe=universe,
        context=NetGeometryContextV31(**geometry.model_dump(exclude={"target_price", "target_evidence_hash"})),
        verify_universe=lambda _, digest: digest == universe_hash,
    ).geometry
    gross = abs(Fraction(geometry.target_price) - Fraction(solved.candidate_entry)) / abs(
        Fraction(solved.candidate_entry) - Fraction(geometry.stop_price)
    )
    with localcontext() as context:
        context.prec = 80
        gross_rr = Decimal(gross.numerator) / Decimal(gross.denominator)
    candidate = TradePlanCandidateV31(
        profile="TEST_ONLY",
        tradeplan_id=UUID(int=1),
        tradeplan_revision=1,
        strategy_lifecycle_id=UUID(int=3),
        strategy_analysis_admission_id=UUID(int=4),
        analysis_admission_class="CANONICAL_RAW",
        pressure_hypothesis_id=UUID(int=5),
        strategy_thesis_id=UUID(int=2),
        context_epoch_id=UUID(int=6),
        execution_box_id=UUID(int=7),
        box_version=1,
        symbol="EURUSD",
        direction=direction,
        state="TRADEPLAN_CANDIDATE",
        final_direction="WAIT",
        valid_for_execution=False,
        promotion_eligibility="CANONICAL_RISK_PATH",
        risk_handoff_allowed=True,
        final_signal_allowed=False,
        execution_command_allowed=False,
        strategy_next_required_stage="RISK_RESERVATION",
        target_id=UUID(int=9),
        entry_interval=solved.feasible_interval,
        candidate_entry=solved.candidate_entry,
        structural_sl=geometry.stop_price,
        tp1=geometry.target_price,
        gross_rr=gross_rr,
        net_rr=solved.net_rr,
        execution_policy_id=geometry.policy.policy_id,
        evidence_hash=H,
        decision_at=NOW,
    )
    context_receipt = context_fixture(direction)
    handoff = CandidateHandoffV31(
        profile="TEST_ONLY",
        selected_ssot_hash="sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902",
        proof_policy_id="S3_S5_HANDOFF_TEST_V2",
        candidate=candidate,
        target_universe=universe,
        admission_receipt_hash=H,
        thesis_structural_proof_hash=H,
        context_route_receipt_hash=context_route_receipt_hash_v31(context_receipt),
        context_route_receipt=context_receipt,
        price_quality_receipt_hash=H,
        handoff_receipt_valid_until=NOW + timedelta(seconds=1),
    )
    request = request.model_copy(
        update={
            "tradeplan_id": str(candidate.tradeplan_id),
            "thesis_id": str(candidate.strategy_thesis_id),
            "geometry": geometry,
            "strategy_candidate_receipt_hash": candidate_handoff_hash_v31(handoff),
        }
    )
    return ledger, handoff, request


def propose(ledger, handoff, request, **overrides):
    handoff_hash = candidate_handoff_hash_v31(handoff)
    risk_hash = parent_sizing_request_hash_v31(request)
    universe_hash = target_universe_hash_v31(handoff.target_universe)
    kwargs = dict(
        reservation_id=UUID(int=21),
        expires_at=NOW + timedelta(seconds=1),
        now=NOW,
        owner_epoch=ledger.owner_epoch,
        expected_version=ledger.version,
        verify_handoff=lambda _, digest: digest == handoff_hash,
        verify_universe=lambda _, digest: digest == universe_hash,
        verify_risk_inputs=lambda _, digest: digest == risk_hash,
    )
    kwargs.update(overrides)
    return propose_canonical_parent_v31(ledger, handoff, request, **kwargs)


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("epoch", "CONTEXT_SCOPE_MISMATCH"),
        ("lifecycle", "CONTEXT_SCOPE_MISMATCH"),
        ("hash", "CONTEXT_RECEIPT_HASH_MISMATCH"),
        ("state", "CONTEXT_NOT_ACTIVE_OR_EXPIRED"),
        ("deadline", "CONTEXT_NOT_ACTIVE_OR_EXPIRED"),
        ("route", "CONTEXT_ROUTE_NOT_ALLOWED"),
        ("unresolved", "CONTEXT_ROUTE_NOT_ALLOWED"),
        ("legacy_policy", "literal_error"),
        ("missing_body", "Field required"),
    ],
)
def test_context_binding_rejected_before_risk_verifiers(fault, reason):
    ledger, handoff, request = bundle()
    body = handoff.model_dump()
    context = body["context_route_receipt"]
    if fault == "epoch":
        context["context_epoch_id"] = UUID(int=999)
    elif fault == "lifecycle":
        context["strategy_lifecycle_id"] = UUID(int=999)
    elif fault == "state":
        context["state"] = "SUPERSEDED"
    elif fault == "deadline":
        body["handoff_receipt_valid_until"] = context["valid_until"] + timedelta(seconds=1)
    elif fault == "route":
        context["selected_route"] = "UNLISTED_ROUTE"
    elif fault == "unresolved":
        context["material"]["primary_direction_domain"] = "UNRESOLVED"
        context["material"]["allowed_directions"] = ()
        from contracts.strategy_5scr_context_route_v31 import MaterialContextV31

        material = MaterialContextV31.model_validate(context["material"])
        context["material_context_hash"] = material_context_hash_v31(context["symbol"], material)
    elif fault == "legacy_policy":
        body["proof_policy_id"] = "S3_S5_HANDOFF_TEST_V1"
    elif fault == "missing_body":
        body.pop("context_route_receipt")
    body["context_route_receipt_hash"] = (
        H if fault == "hash" else context_route_receipt_hash_v31(ContextRouteReceiptV31.model_validate(context))
    )
    body["candidate"] = handoff.candidate
    body["target_universe"] = handoff.target_universe
    if fault != "missing_body":
        body["context_route_receipt"] = ContextRouteReceiptV31.model_validate(context)
    unsafe = CandidateHandoffV31.model_construct(**body)
    calls = []
    with pytest.raises(ValidationError, match=reason):
        propose_canonical_parent_v31(
            ledger,
            unsafe,
            request,
            reservation_id=UUID(int=21),
            expires_at=NOW + timedelta(seconds=1),
            now=NOW,
            owner_epoch=ledger.owner_epoch,
            expected_version=ledger.version,
            verify_handoff=lambda *args: calls.append(args),
            verify_universe=None,
            verify_risk_inputs=None,
        )
    assert not calls and ledger.reservations == ()


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_canonical_candidate_to_target_geometry_sizing_capacity_is_bound_and_nonexecutable(direction):
    ledger, handoff, request = bundle(direction)
    candidate_before = handoff.candidate.model_dump_json()
    result = propose(ledger, handoff, request)
    assert result.status == "APPLIED_TEST_ONLY" and result.ledger.version == 1
    assert result.reservation.strategy_candidate_receipt_hash == candidate_handoff_hash_v31(handoff)
    assert result.reservation.sizing.request_hash == parent_sizing_request_hash_v31(request)
    assert result.reservation.tradeplan_id == str(handoff.candidate.tradeplan_id)
    assert result.execution_authority is result.capital_reservation_authority is False
    assert handoff.candidate.model_dump_json() == candidate_before


def test_advisory_candidate_stops_before_verifiers_or_capacity():
    ledger, handoff, request = bundle()
    candidate = handoff.candidate.model_copy(
        update={
            "analysis_admission_class": "MATURE_ADVISORY",
            "promotion_eligibility": "SHADOW_ONLY",
            "risk_handoff_allowed": False,
            "strategy_next_required_stage": "SHADOW_TERMINAL_REVIEW",
        }
    )
    handoff = handoff.model_copy(update={"candidate": candidate})

    def forbidden(*_):
        raise AssertionError("advisory must stop before any verifier")

    with pytest.raises(CapacityRejectedError, match="STRATEGY_ADVISORY_RISK_HANDOFF_PROHIBITED"):
        propose(
            ledger, handoff, request, verify_handoff=forbidden, verify_universe=forbidden, verify_risk_inputs=forbidden
        )
    assert ledger.reservations == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("valid_for_execution", True),
        ("final_signal_allowed", True),
        ("execution_command_allowed", True),
        ("analysis_admission_class", "MATURE_ADVISORY"),
        ("profile", "DEMO"),
        ("tradeplan_id", "5scr-plan:" + "a" * 32),
    ],
)
def test_candidate_schema_rejects_escalation_or_legacy_id_relabeling(field, value):
    _, handoff, _ = bundle()
    payload = handoff.candidate.model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        TradePlanCandidateV31.model_validate(payload)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("receipt", "STRATEGY_HANDOFF_RECEIPT_MISMATCH"),
        ("plan", "STRATEGY_HANDOFF_IDENTITY_MISMATCH"),
        ("revision", "STRATEGY_HANDOFF_IDENTITY_MISMATCH"),
        ("thesis", "STRATEGY_HANDOFF_IDENTITY_MISMATCH"),
        ("direction", "STRATEGY_HANDOFF_CONTEXT_MISMATCH"),
        ("policy", "STRATEGY_HANDOFF_POLICY_MISMATCH"),
    ],
)
def test_risk_request_cannot_substitute_candidate_scope(change, reason):
    ledger, handoff, request = bundle()
    if change == "receipt":
        request = request.model_copy(update={"strategy_candidate_receipt_hash": None})
    elif change == "plan":
        request = request.model_copy(update={"tradeplan_id": str(UUID(int=99))})
    elif change == "revision":
        request = request.model_copy(update={"tradeplan_revision": 2})
    elif change == "thesis":
        request = request.model_copy(update={"thesis_id": str(UUID(int=99))})
    elif change == "direction":
        request = request.model_copy(update={"geometry": request.geometry.model_copy(update={"direction": "SELL"})})
    elif change == "policy":
        request = request.model_copy(update={"geometry": request.geometry.model_copy(update={"policy": None})})
    with pytest.raises(CapacityRejectedError, match=reason):
        propose(ledger, handoff, request)


@pytest.mark.parametrize("name", ["verify_handoff", "verify_universe", "verify_risk_inputs"])
def test_each_independent_verifier_is_mandatory(name):
    ledger, handoff, request = bundle()
    with pytest.raises(CapacityRejectedError):
        propose(ledger, handoff, request, **{name: None})
    assert ledger.reservations == ()


def test_farther_target_is_not_accepted_while_nearest_remains_live():
    ledger, handoff, request = bundle()
    farther = handoff.target_universe.targets[1]
    candidate = handoff.candidate.model_copy(update={"target_id": UUID(farther.target_id), "tp1": farther.price})
    handoff = handoff.model_copy(update={"candidate": candidate})
    request = request.model_copy(
        update={
            "strategy_candidate_receipt_hash": candidate_handoff_hash_v31(handoff),
            "geometry": request.geometry.model_copy(update={"target_price": farther.price}),
        }
    )
    with pytest.raises(CapacityRejectedError, match="STRATEGY_TARGET_IDENTITY_MISMATCH"):
        propose(ledger, handoff, request)


@pytest.mark.parametrize(
    "field,reason", [("gross_rr", "STRATEGY_GROSS_RR_MISMATCH"), ("net_rr", "STRATEGY_GEOMETRY_REPLAY_MISMATCH")]
)
def test_claimed_rr_is_recomputed_even_when_handoff_receipt_matches(field, reason):
    ledger, handoff, request = bundle()
    handoff = handoff.model_copy(update={"candidate": handoff.candidate.model_copy(update={field: Decimal("10")})})
    request = request.model_copy(update={"strategy_candidate_receipt_hash": candidate_handoff_hash_v31(handoff)})
    with pytest.raises(CapacityRejectedError, match=reason):
        propose(ledger, handoff, request)


def test_expired_receipt_denies_new_proposal_but_exact_lost_ack_retry_returns_existing():
    ledger, handoff, request = bundle()
    later = NOW + timedelta(seconds=2)
    with pytest.raises(CapacityRejectedError, match="STRATEGY_HANDOFF_RECEIPT_EXPIRED"):
        propose(ledger, handoff, request, now=later)
    committed = propose(ledger, handoff, request).ledger
    retry = propose(
        committed,
        handoff,
        request,
        now=later,
        expected_version=0,
        verify_handoff=None,
        verify_universe=None,
        verify_risk_inputs=None,
    )
    assert retry.status == "DUPLICATE_TEST_ONLY" and retry.ledger == committed
    assert retry.execution_authority is False


def test_universe_verifier_cannot_delete_nearest_target_after_hash_check():
    ledger, handoff, request = bundle()

    def mutate(universe, digest):
        object.__setattr__(universe, "targets", universe.targets[1:])
        return True

    with pytest.raises(CapacityRejectedError, match="TARGET_EVIDENCE_CHANGED_DURING_VERIFICATION"):
        propose(ledger, handoff, request, verify_universe=mutate)


def test_reservation_expiry_is_bounded_by_handoff_receipt():
    with pytest.raises(CapacityRejectedError, match="STRATEGY_RESERVATION_EXCEEDS_HANDOFF_WINDOW"):
        propose(*bundle(), expires_at=NOW + timedelta(seconds=2))


@pytest.mark.parametrize(
    "field",
    [
        "admission_receipt_hash",
        "thesis_structural_proof_hash",
        "context_route_receipt_hash",
        "price_quality_receipt_hash",
    ],
)
def test_missing_strategy_proof_reference_cannot_enter_handoff(field):
    _, handoff, _ = bundle()
    payload = handoff.model_dump()
    del payload[field]
    with pytest.raises(ValidationError):
        CandidateHandoffV31.model_validate(payload)


def test_selected_ssot_binding_cannot_be_substituted():
    _, handoff, _ = bundle()
    with pytest.raises(ValidationError):
        CandidateHandoffV31.model_validate({**handoff.model_dump(), "selected_ssot_hash": H})


def test_handoff_verifier_cannot_change_candidate_after_digest_verification():
    def mutate(handoff, digest):
        object.__setattr__(handoff.candidate, "gross_rr", Decimal("100"))
        return True

    with pytest.raises(CapacityRejectedError, match="STRATEGY_HANDOFF_EVIDENCE_CHANGED"):
        propose(*bundle(), verify_handoff=mutate)
