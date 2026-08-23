"""Contract and pure-promotion gates for one C3 SHADOW projection command."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_shadow_risk_projection import Strategy5SCRShadowRiskProjectionEvaluatorV1
from contracts.mt5_execution_protocol import (
    ExecutorMode,
    ShadowProjectionCommandGuards,
    ShadowProjectionCommandSource,
    verify_execution_command,
)
from contracts.mt5_shadow_projection_command import (
    C3ShadowProjectionCommandRequest,
    c3_shadow_projection_command_id,
)
from contracts.strategy_5scr_shadow_risk_projection import C2_SHADOW_SOURCE_ADMISSION_CLASS
from execution.mt5_shadow_projection_command_promotion import (
    ShadowProjectionCommandPromotionError,
    promote_shadow_projection_to_command,
)
from risk.s5_campaign_risk import CampaignRiskPolicy
from tests.test_strategy_5scr_candidate_c2_shadow_v2 import _evidence

_SIGNING_SECRET = "shadow-projection-test-signing-secret-value-0123456789"
_SIGNING_KEY_ID = "shadow-projection-test.v1"


def _projection_fixture(*, would_reject: bool = False):  # type: ignore[no-untyped-def]
    evidence = _evidence("BUY", kill_switch="ENGAGED")
    policy = None
    if would_reject:
        policy = CampaignRiskPolicy(
            risk_percent_per_entry=Decimal("0.04"),
            max_total_open_risk_percent=Decimal("0.10"),
        )
    result = Strategy5SCRShadowRiskProjectionEvaluatorV1(policy).evaluate(
        evidence,
        source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
    )
    assert result.projection is not None
    return evidence, result.projection


def _request(projection, *, run_id: str = "c3-shadow-projection-001", **updates):  # type: ignore[no-untyped-def]
    values = {
        "operator_run_id": run_id,
        "confirm_run_id": run_id,
        "actor": "operator:test",
        "reason": "manual natural strategy SHADOW rehearsal",
        "shadow_authority_id": projection.shadow_authority_id,
        "source_candidate_id": projection.tradeplan_id,
        "source_candidate_revision": projection.candidate_revision,
        "executor_id": projection.executor_id,
        "account_id": projection.account_id,
        "broker_symbol": projection.broker_symbol,
        "expected_governance_version": 7,
        "max_spread_points": 100,
        "max_price_drift_points": 50,
        "magic": 150015,
        "requested_at_utc": projection.projected_at_utc + timedelta(seconds=1),
        "expires_at_utc": projection.projected_at_utc + timedelta(seconds=30),
    }
    values.update(updates)
    return C3ShadowProjectionCommandRequest.model_validate(values)


def _promote(*, would_reject: bool = False):  # type: ignore[no-untyped-def]
    evidence, projection = _projection_fixture(would_reject=would_reject)
    request = _request(projection)
    command = promote_shadow_projection_to_command(
        projection,
        request,
        evidence.account_snapshot,
        executor_login_hash="sha256:" + "a" * 64,
        governance_version=request.expected_governance_version,
        issued_at_utc=request.requested_at_utc,
        signing_secret=_SIGNING_SECRET,
        signing_key_id=_SIGNING_KEY_ID,
    )
    return evidence, projection, request, command


def test_would_reserve_promotes_to_one_signed_broker_inert_shadow_command() -> None:
    _, projection, request, command = _promote()

    assert command.command_id == request.command_id == c3_shadow_projection_command_id(projection.shadow_authority_id)
    assert command.executor_binding.execution_mode is ExecutorMode.SHADOW
    assert isinstance(command.source, ShadowProjectionCommandSource)
    assert isinstance(command.guards, ShadowProjectionCommandGuards)
    assert command.source.source_shadow_authority_id == projection.shadow_authority_id
    assert command.source.source_candidate_id == projection.tradeplan_id
    assert command.source.execution_authority is False
    assert command.source.capital_reserved is False
    assert command.source.broker_side_effect_allowed is False
    assert command.source.order_send_eligible is False
    assert command.guards.execution_authority is False
    assert command.guards.capital_reserved is False
    assert command.guards.broker_side_effect_allowed is False
    assert command.guards.order_send_eligible is False
    assert verify_execution_command(command, secret=_SIGNING_SECRET)
    serialized = command.model_dump(mode="json")
    assert "risk_reservation_id" not in str(serialized)


def test_same_projection_and_operator_request_is_byte_stable_and_idempotent() -> None:
    evidence, projection = _projection_fixture()
    request = _request(projection)

    def promote():  # type: ignore[no-untyped-def]
        return promote_shadow_projection_to_command(
            projection,
            request,
            evidence.account_snapshot,
            executor_login_hash="sha256:" + "a" * 64,
            governance_version=7,
            issued_at_utc=request.requested_at_utc,
            signing_secret=_SIGNING_SECRET,
            signing_key_id=_SIGNING_KEY_ID,
        )

    first = promote()
    replay = promote()
    assert replay == first
    assert first.command_id == c3_shadow_projection_command_id(projection.shadow_authority_id)
    assert first.idempotency_key == f"c3-shadow-projection:{request.operator_run_id}"


@pytest.mark.parametrize("mode", ["DEMO", "LIVE"])
def test_operator_request_contract_rejects_demo_and_live(mode: str) -> None:
    _, projection = _projection_fixture()

    with pytest.raises(ValidationError):
        _request(projection, requested_execution_mode=mode)


def test_would_reject_projection_cannot_issue_a_command() -> None:
    evidence, projection = _projection_fixture(would_reject=True)
    request = _request(projection)

    with pytest.raises(ShadowProjectionCommandPromotionError) as caught:
        promote_shadow_projection_to_command(
            projection,
            request,
            evidence.account_snapshot,
            executor_login_hash="sha256:" + "a" * 64,
            governance_version=7,
            issued_at_utc=request.requested_at_utc,
            signing_secret=_SIGNING_SECRET,
            signing_key_id=_SIGNING_KEY_ID,
        )
    assert caught.value.reason_code == "C3_PROJECTION_NOT_WOULD_RESERVE"


def test_operator_target_revision_mismatch_is_rejected() -> None:
    evidence, projection = _projection_fixture()
    request = _request(projection, source_candidate_revision=2)

    with pytest.raises(ShadowProjectionCommandPromotionError) as caught:
        promote_shadow_projection_to_command(
            projection,
            request,
            evidence.account_snapshot,
            executor_login_hash="sha256:" + "a" * 64,
            governance_version=7,
            issued_at_utc=request.requested_at_utc,
            signing_secret=_SIGNING_SECRET,
            signing_key_id=_SIGNING_KEY_ID,
        )
    assert caught.value.reason_code == "C3_OPERATOR_TARGET_MISMATCH"
