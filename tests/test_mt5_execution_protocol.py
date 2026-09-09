from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from contracts.mt5_execution_protocol import (
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorMode,
    MarginMode,
    build_signed_execution_envelope,
    canonical_json_bytes,
    derive_executor_command_verification_key,
    sha256_bytes_tag,
    sha256_tag,
    sign_execution_command,
    signed_execution_envelope_preimage,
    verify_execution_command,
    verify_signed_execution_envelope,
)
from execution.mt5_command_promotion import (
    PromotionContext,
    PromotionRejectedError,
    promote_final_signal_to_command,
)

SECRET = "s" * 64
GOLDEN_VECTOR_PATH = (
    Path(__file__).parents[1] / "ea_interface" / "wolf15_executor" / "test_vectors" / "signed_envelope_v2.json"
)


def _strategy_5scr_proof() -> dict:
    confirmed_at = datetime.now(UTC).isoformat()
    return {
        "strategy_model": "STRATEGY_5S_CR_FINAL",
        "rule_version": "5scr.final.2026-07-19",
        "rule_status": "FROZEN",
        "validation_status": "STRONG_PROVISIONAL",
        "out_of_sample_status": "NOT_YET_VALIDATED",
        "production_proven": False,
        "confirmation_policy": "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST",
        "authority_chain": ["PRESSURE", "CONTEXT_RESOLUTION", "H4", "H1", "M15", "M1", "RISK"],
        "pressure": {
            "selected_pair": "EURUSD",
            "lifecycle_id": "lifecycle-001",
            "selection_confirmed": True,
        },
        "context_resolution": {
            "status": "RESOLVED",
            "origin": "WAIT_FOR_CONFIRMATION",
            "price_location": "H4_DEMAND",
            "liquidity_context": "SELL_SIDE_REJECTED",
            "daily_bias": "BULLISH",
            "h4_structure": "BULLISH_PULLBACK",
            "allowed_playbook": "BUY_ON_CONFIRMED_BREAK_RETEST",
            "selected_playbook": "BUY_ON_CONFIRMED_BREAK_RETEST",
            "blocked_playbook": ["SELL_LIMIT"],
            "scenario_allowed": True,
        },
        "h4": {
            "target_mode": "FINAL_MARKET_STRUCTURE",
            "structural_tp1": 1.11,
            "target_room_valid": True,
        },
        "h1": {
            "direction": "BUY",
            "structure_state": "BULLISH_CONFIRMED",
            "structure_confirmed": True,
            "candle_closed": True,
            "confirmed_at_utc": confirmed_at,
        },
        "m15": {
            "direction": "BUY",
            "structural_break": True,
            "candle_closed": True,
            "acceptance_confirmed": True,
            "failed_reclaim_or_retest_confirmed": False,
            "rejection_candle_only": False,
            "confirmed_at_utc": confirmed_at,
        },
        "m1": {
            "box_id": "lifecycle-001:m1",
            "box_low": 1.0999,
            "box_high": 1.1001,
            "fill_price": 1.1,
            "return_to_box_invalidated": False,
        },
        "risk": {"structural_sl": 1.095, "sizing_basis": "STRUCTURAL_SL"},
    }


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
            "strategy_model": "STRATEGY_5S_CR_FINAL",
            "strategy_rule_version": "5scr.final.2026-07-19",
            "strategy_rule_status": "FROZEN",
            "strategy_proof_hash": "sha256:" + "c" * 64,
            "context_resolution_status": "RESOLVED",
            "confirmation_policy": "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST",
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
    now = datetime.now(UTC)
    return {
        "event": "signal_json",
        "schema_version": "wolf15.strategy-5scr.final-signal.v1",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD.a",
        "signal_id": "signal-001",
        "tradeplan_id": "5scr-plan:" + "a" * 32,
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
        "entry_reference_price": 1.1,
        "selected_sl": 1.095,
        "tp1": 1.11,
        "strategy_5scr": _strategy_5scr_proof(),
        "risk_reservation_id": "11111111-1111-4111-8111-111111111111",
        "risk_snapshot_id": "snapshot-001",
        "reserved_volume": 0.1,
        "risk_reservation": {
            "schema_version": "wolf15.strategy-5scr.risk-reservation.v1",
            "reservation_id": "11111111-1111-4111-8111-111111111111",
            "campaign_id": "lifecycle-001",
            "tradeplan_id": "5scr-plan:" + "a" * 32,
            "canonical_symbol": "EURUSD",
            "broker_symbol": "EURUSD.a",
            "direction": "BUY",
            "policy_id": "5scr.production-adjusted.parent-only.v1",
            "state": "HELD",
            "risk_snapshot_id": "snapshot-001",
            "entry_role": "PARENT",
            "risk_unit_usd": 50.0,
            "reserved_risk_usd": 49.0,
            "reserved_volume": 0.1,
            "reserved_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(minutes=5)).isoformat(),
        },
    }


def _promotion_context() -> PromotionContext:
    now = datetime.now(UTC)
    return PromotionContext(
        executor_id=uuid4(),
        account_id="acct-01",
        login_hash="sha256:" + "a" * 64,
        broker_server="Broker-Demo",
        execution_mode=ExecutorMode.SHADOW,
        campaign_id="lifecycle-001",
        block_id="5scr-plan:" + "a" * 32,
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
        expires_at_utc=now + timedelta(minutes=4),
        broker_expiration_utc=now + timedelta(minutes=4),
        expected_margin_mode=MarginMode.HEDGING,
        max_spread_points=25,
        max_price_drift_points=15,
        risk_snapshot_id="snapshot-001",
        risk_reservation_id="11111111-1111-4111-8111-111111111111",
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


def test_signed_wire_envelope_round_trips_exact_frozen_bytes() -> None:
    command = sign_execution_command(_unsigned_command(), secret=SECRET, key_id="exec-key-test")
    envelope = build_signed_execution_envelope(
        command,
        root_secret=SECRET,
        key_id="exec-key-test.v2",
    )
    verification_key = derive_executor_command_verification_key(
        command.executor_binding.executor_id,
        root_secret=SECRET,
    )

    verified = verify_signed_execution_envelope(envelope, verification_key=verification_key)

    assert verified == command
    assert envelope.payload_sha256 == sha256_tag(command.model_dump(mode="json"))
    assert envelope.payload_b64.endswith("=") is False


def test_signed_wire_envelope_rejects_a_key_scoped_to_another_executor() -> None:
    command = sign_execution_command(_unsigned_command(), secret=SECRET, key_id="exec-key-test")
    envelope = build_signed_execution_envelope(
        command,
        root_secret=SECRET,
        key_id="exec-key-test.v2",
    )
    wrong_executor_key = derive_executor_command_verification_key(
        uuid4(),
        root_secret=SECRET,
    )

    assert verify_signed_execution_envelope(envelope, verification_key=wrong_executor_key) is None


@pytest.mark.parametrize("field", ["payload_b64", "payload_sha256", "signature", "key_id", "executor_id"])
def test_signed_wire_envelope_rejects_every_bound_field_tamper(field: str) -> None:
    command = sign_execution_command(_unsigned_command(), secret=SECRET, key_id="exec-key-test")
    envelope = build_signed_execution_envelope(
        command,
        root_secret=SECRET,
        key_id="exec-key-test.v2",
    )
    verification_key = derive_executor_command_verification_key(
        command.executor_binding.executor_id,
        root_secret=SECRET,
    )
    replacements = {
        "payload_b64": ("A" if envelope.payload_b64[0] != "A" else "B") + envelope.payload_b64[1:],
        "payload_sha256": "sha256:" + "0" * 64,
        "signature": "base64url:" + "A" * 43,
        "key_id": "wrong-key.v2",
        "executor_id": uuid4(),
    }

    tampered = envelope.model_copy(update={field: replacements[field]})

    assert verify_signed_execution_envelope(tampered, verification_key=verification_key) is None


def test_signed_wire_payload_is_python_canonical_json_not_a_reconstructed_object() -> None:
    payload = _unsigned_command()
    payload["guards"]["max_balance_drift_pct"] = 0.30000000000000004
    command = sign_execution_command(payload, secret=SECRET, key_id="exec-key-test")
    envelope = build_signed_execution_envelope(command, root_secret=SECRET, key_id="exec-key-test.v2")

    decoded = base64.urlsafe_b64decode(envelope.payload_b64 + "=" * (-len(envelope.payload_b64) % 4))

    assert decoded == canonical_json_bytes(command.model_dump(mode="json"))
    assert b"0.30000000000000004" in decoded


def test_signed_wire_golden_vector_is_stable_for_the_mql5_verifier() -> None:
    vector = json.loads(GOLDEN_VECTOR_PATH.read_text(encoding="utf-8"))
    payload = vector["payload_ascii"].encode("ascii")
    verification_key = derive_executor_command_verification_key(
        vector["executor_id"],
        root_secret=vector["root_secret_utf8"],
    )
    preimage = signed_execution_envelope_preimage(
        key_id=vector["key_id"],
        executor_id=vector["executor_id"],
        payload_sha256=vector["payload_sha256"],
        payload_b64=vector["payload_b64"],
    )
    signature = "base64url:" + base64.urlsafe_b64encode(
        hmac.new(verification_key, preimage, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")

    assert base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=") == vector["payload_b64"]
    assert sha256_bytes_tag(payload) == vector["payload_sha256"]
    assert verification_key.hex() == vector["verification_key_hex"]
    assert preimage.decode("ascii") == vector["preimage_ascii"]
    assert signature == vector["signature"]


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
    assert command.source.strategy_model == "STRATEGY_5S_CR_FINAL"
    assert command.source.context_resolution_status == "RESOLVED"
    assert verify_execution_command(command, secret=SECRET)


@pytest.mark.parametrize(
    ("update", "reason_code"),
    [
        ({"execution_mode": ExecutorMode.DEMO}, "PROMOTION_RISK_AUTHORITY_SHADOW_ONLY"),
        ({"block_role": "CHILD"}, "PROMOTION_RISK_AUTHORITY_PARENT_ONLY"),
        ({"volume": 0.2}, "PROMOTION_RESERVED_VOLUME_MISMATCH"),
        ({"risk_snapshot_id": "snapshot-other"}, "PROMOTION_RISK_SNAPSHOT_MISMATCH"),
        ({"risk_reservation_id": "22222222-2222-4222-8222-222222222222"}, "PROMOTION_RISK_RESERVATION_MISMATCH"),
        ({"broker_symbol": "EURUSD.other"}, "PROMOTION_RESERVED_SYMBOL_MISMATCH"),
    ],
)
def test_final_signal_promotion_is_bound_to_exact_parent_reservation(
    update: dict[str, object],
    reason_code: str,
) -> None:
    context = _promotion_context().model_copy(update=update)

    with pytest.raises(PromotionRejectedError) as caught:
        promote_final_signal_to_command(
            _final_signal(),
            context=context,
            signing_secret=SECRET,
            signing_key_id="exec-key-test",
        )
    assert caught.value.reason_code == reason_code


def test_final_signal_without_5scr_proof_cannot_be_promoted() -> None:
    signal = _final_signal()
    signal.pop("strategy_5scr")
    with pytest.raises(PromotionRejectedError) as exc:
        promote_final_signal_to_command(
            signal,
            context=_promotion_context(),
            signing_secret=SECRET,
            signing_key_id="exec-key-test",
        )
    assert exc.value.reason_code == "PROMOTION_5SCR_GATE_REJECTED"


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
