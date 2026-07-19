from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from contracts.mt5_execution_protocol import (
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorMode,
    MarginMode,
    sign_execution_command,
    verify_execution_command,
)
from execution.mt5_command_promotion import (
    PromotionContext,
    PromotionRejectedError,
    promote_final_signal_to_command,
)

SECRET = "s" * 64


def _unsigned_command() -> dict:
    now = datetime.now(UTC)
    executor_id = uuid4()
    return {
        "event": "execution_command",
        "protocol_version": "wolf15.mt5.exec.v1",
        "command_id": uuid4(),
        "idempotency_key": "acct:campaign:block:1:PLACE_PENDING",
        "revision": 1,
        "issued_at_utc": now,
        "not_before_utc": now,
        "expires_at_utc": now + timedelta(minutes=30),
        "executor_binding": {
            "executor_id": executor_id,
            "account_id": "acct-01",
            "login_hash": "sha256:" + "a" * 64,
            "broker_server": "Broker-Demo",
            "execution_mode": "SHADOW",
        },
        "source": {
            "source_event": "signal_json",
            "source_schema_version": "2.0-universal-pattern",
            "source_signal_id": "signal-001",
            "source_signal_hash": "sha256:" + "b" * 64,
            "campaign_id": "EURUSD-CAMPAIGN-001",
            "block_id": "EURUSD-PARENT-001",
            "block_role": "PARENT",
            "lifecycle_anchor": "lifecycle-001",
            "valid_for_execution": True,
            "execution_gate_passed": True,
            "tradeplan_valid": True,
        },
        "action": "PLACE_PENDING",
        "order": {
            "canonical_symbol": "EURUSD",
            "broker_symbol": "EURUSD.a",
            "side": "BUY",
            "order_type": "BUY_LIMIT",
            "volume": 0.1,
            "entry_price": 1.1,
            "stop_loss": 1.095,
            "take_profit": 1.11,
            "magic": 150015,
            "comment_tag": "W15:ABCDEF123456",
            "time_in_force": "SPECIFIED",
            "broker_expiration_utc": now + timedelta(minutes=30),
        },
        "guards": {
            "require_attached_sl": True,
            "require_attached_tp": True,
            "max_spread_points": 25,
            "max_price_drift_points": 15,
            "expected_margin_mode": "HEDGING",
            "max_submit_attempts": 1,
            "allow_volume_round_down": False,
            "allow_price_normalization": False,
            "risk_snapshot_id": "snapshot-001",
            "risk_reservation_id": "reservation-001",
            "balance_snapshot": 1000,
            "equity_snapshot": 1000,
        },
    }


def _final_signal() -> dict:
    return {
        "event": "signal_json",
        "schema_version": "2.0-universal-pattern",
        "symbol": "EURUSD",
        "signal_id": "signal-001",
        "lifecycle_id": "lifecycle-001",
        "is_final_signal": True,
        "valid_for_execution": True,
        "execution_valid_now": True,
        "tradeplan_valid": True,
        "analysis_valid": True,
        "direction_valid": True,
        "signal_valid": True,
        "final_direction": "BUY",
        "rr_status": "VALID",
    }


def _promotion_context() -> PromotionContext:
    now = datetime.now(UTC)
    return PromotionContext(
        executor_id=uuid4(),
        account_id="acct-01",
        login_hash="sha256:" + "a" * 64,
        broker_server="Broker-Demo",
        execution_mode=ExecutorMode.SHADOW,
        campaign_id="EURUSD-CAMPAIGN-001",
        block_id="EURUSD-PARENT-001",
        block_role="PARENT",
        action=ExecutionAction.PLACE_PENDING,
        canonical_symbol="EURUSD",
        broker_symbol="EURUSD.a",
        order_type="BUY_LIMIT",
        volume=0.1,
        entry_price=1.1,
        stop_loss=1.095,
        take_profit=1.11,
        magic=150015,
        issued_at_utc=now,
        not_before_utc=now,
        expires_at_utc=now + timedelta(minutes=30),
        broker_expiration_utc=now + timedelta(minutes=30),
        expected_margin_mode=MarginMode.HEDGING,
        max_spread_points=25,
        max_price_drift_points=15,
        risk_snapshot_id="snapshot-001",
        risk_reservation_id="reservation-001",
        balance_snapshot=1000,
        equity_snapshot=1000,
    )


def test_signed_command_round_trip() -> None:
    command = sign_execution_command(_unsigned_command(), secret=SECRET, key_id="exec-key-test")
    assert isinstance(command, ExecutionCommandV1)
    assert verify_execution_command(command, secret=SECRET)
    assert command.executor_binding.execution_mode == ExecutorMode.SHADOW


def test_command_tampering_breaks_signature() -> None:
    command = sign_execution_command(_unsigned_command(), secret=SECRET, key_id="exec-key-test")
    tampered = command.model_copy(
        update={"order": command.order.model_copy(update={"volume": 0.2}) if command.order else None}
    )
    assert not verify_execution_command(tampered, secret=SECRET)


def test_buy_price_order_is_fail_closed() -> None:
    payload = _unsigned_command()
    payload["order"]["stop_loss"] = 1.105
    with pytest.raises(ValidationError, match="BUY requires"):
        sign_execution_command(payload, secret=SECRET, key_id="exec-key-test")


@pytest.mark.parametrize(
    "event",
    [
        "signal_pressure_state_json",
        "signal_watch_json",
        "signal_decision_update_json",
        "signal_throttle_pressure_tier_snapshot",
    ],
)
def test_non_final_sources_cannot_be_promoted(event: str) -> None:
    signal = _final_signal()
    signal["event"] = event
    with pytest.raises(PromotionRejectedError) as exc:
        promote_final_signal_to_command(
            signal,
            context=_promotion_context(),
            signing_secret=SECRET,
            signing_key_id="exec-key-test",
        )
    assert exc.value.reason_code == "PROMOTION_SOURCE_DENIED"


def test_final_signal_promotes_to_shadow_command() -> None:
    command = promote_final_signal_to_command(
        _final_signal(),
        context=_promotion_context(),
        signing_secret=SECRET,
        signing_key_id="exec-key-test",
    )
    assert command.action == ExecutionAction.PLACE_PENDING
    assert command.executor_binding.execution_mode == ExecutorMode.SHADOW
    assert command.source.source_event == "signal_json"
    assert command.source.valid_for_execution is True
    assert verify_execution_command(command, secret=SECRET)


def test_final_signal_cannot_promote_to_lifecycle_action() -> None:
    context = _promotion_context().model_copy(update={"action": ExecutionAction.CLOSE_FULL})
    with pytest.raises(PromotionRejectedError) as exc:
        promote_final_signal_to_command(
            _final_signal(),
            context=context,
            signing_secret=SECRET,
            signing_key_id="exec-key-test",
        )
    assert exc.value.reason_code == "PROMOTION_ACTION_INVALID"


def test_invalid_execution_flag_cannot_be_promoted() -> None:
    signal = _final_signal()
    signal["valid_for_execution"] = False
    with pytest.raises(PromotionRejectedError) as exc:
        promote_final_signal_to_command(
            signal,
            context=_promotion_context(),
            signing_secret=SECRET,
            signing_key_id="exec-key-test",
        )
    assert exc.value.reason_code == "PROMOTION_EXECUTION_INVALID"
