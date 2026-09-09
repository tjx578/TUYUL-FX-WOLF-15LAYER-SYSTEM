from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_risk_reservation import (
    DurableRiskReservation,
    RiskReservationRequest,
    validate_final_signal_reservation,
)
from storage.strategy_5scr_risk_reservation_repository import (
    RiskReservationRejectedError,
    build_final_signal_payload,
)
from tests.test_strategy_5scr_pressure_to_tradeplan import _evidence, _legacy_builder, _lifecycle


def _candidate_and_plan():
    result = _legacy_builder().build(_lifecycle(), _evidence())
    assert result.tradeplan is not None
    assert result.candidate_payload is not None
    return result.candidate_payload, result.tradeplan


def _reservation(*, reserved_at: datetime | None = None) -> DurableRiskReservation:
    _candidate, plan = _candidate_and_plan()
    now = reserved_at or datetime.now(UTC)
    return DurableRiskReservation(
        reservation_id=UUID("11111111-1111-4111-8111-111111111111"),
        campaign_id=plan.campaign_id,
        tradeplan_id=plan.tradeplan_id,
        executor_id=UUID("22222222-2222-4222-8222-222222222222"),
        account_id="internal-account-id",
        account_snapshot_id="snapshot-risk-001",
        canonical_symbol=plan.symbol,
        broker_symbol="CHFJPY",
        direction=plan.direction,
        volume=0.1,
        entry_price=plan.entry,
        stop_loss=plan.stop_loss,
        take_profit=plan.tp1,
        risk_unit_usd=50.0,
        reserved_risk_usd=49.5,
        balance_snapshot=1000.0,
        equity_snapshot=1000.0,
        reserved_at_utc=now,
        expires_at_utc=now + timedelta(minutes=5),
    )


def test_final_signal_promotion_is_credential_free_and_does_not_mutate_candidate() -> None:
    candidate, plan = _candidate_and_plan()
    original = deepcopy(candidate)
    reservation = _reservation()

    signal = build_final_signal_payload(
        candidate_payload=candidate,
        tradeplan=plan,
        reservation=reservation,
        signal_id="5scr-signal:" + "a" * 32,
    )

    assert candidate == original
    assert signal["event"] == "signal_json"
    assert signal["final_direction"] == plan.direction
    assert signal["valid_for_execution"] is True
    assert signal["risk_reservation_id"] == str(reservation.reservation_id)
    assert signal["reserved_volume"] == reservation.volume
    assert validate_final_signal_reservation(signal).reservation_id == reservation.reservation_id
    serialized = str(signal).lower()
    for forbidden in (
        "internal-account-id",
        str(reservation.executor_id),
        "balance_snapshot",
        "equity_snapshot",
        "login_hash",
        "verification_key",
    ):
        assert forbidden.lower() not in serialized


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("risk_reservation_id",), str(uuid4()), "does not match proof"),
        (("risk_snapshot_id",), "other-snapshot", "does not match proof"),
        (("reserved_volume",), 0.2, "does not match proof"),
        (("broker_symbol",), "CHFJPY.other", "does not match reservation proof"),
        (("schema_version",), "2.0-universal-pattern", "wrong event or schema"),
        (("valid_for_execution",), False, "requires valid_for_execution=true"),
    ],
)
def test_final_signal_reservation_tamper_fails_closed(
    path: tuple[str, ...],
    value: object,
    match: str,
) -> None:
    candidate, plan = _candidate_and_plan()
    signal = build_final_signal_payload(
        candidate_payload=candidate,
        tradeplan=plan,
        reservation=_reservation(),
        signal_id="5scr-signal:" + "b" * 32,
    )
    signal[path[0]] = value

    with pytest.raises(ValueError, match=match):
        validate_final_signal_reservation(signal)


def test_reservation_request_is_parent_only_and_ttl_is_bounded() -> None:
    now = datetime.now(UTC)
    candidate, _plan = _candidate_and_plan()

    with pytest.raises(ValidationError, match="PARENT"):
        RiskReservationRequest.model_validate(
            {
                "tradeplan_id": candidate["tradeplan_id"],
                "executor_id": uuid4(),
                "broker_symbol": "CHFJPY",
                "entry_role": "CHILD",
                "requested_at_utc": now,
                "expires_at_utc": now + timedelta(minutes=1),
            }
        )
    with pytest.raises(ValidationError, match="TTL cannot exceed 300 seconds"):
        RiskReservationRequest(
            tradeplan_id=candidate["tradeplan_id"],
            executor_id=uuid4(),
            broker_symbol="CHFJPY",
            requested_at_utc=now,
            expires_at_utc=now + timedelta(seconds=301),
        )


def test_candidate_with_premature_execution_authority_is_rejected() -> None:
    candidate, plan = _candidate_and_plan()
    candidate["valid_for_execution"] = True

    with pytest.raises(RiskReservationRejectedError, match="candidate authority fields drifted"):
        build_final_signal_payload(
            candidate_payload=candidate,
            tradeplan=plan,
            reservation=_reservation(),
            signal_id="5scr-signal:" + "c" * 32,
        )
