"""Frozen DEMO-canary envelope checker: positives, negatives, and reuse parity."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from contracts.mt5_execution_protocol import ENGINEERING_DEMO_CANARY_EA_VERSION, AccountSnapshotV1
from execution.mt5_command_repository import engineering_canary_latest_state_veto
from ops.demo_canary_verifier.envelope import (
    ENVELOPE_V1_PATH,
    ENVELOPE_V1_SHA256,
    PRESUBMIT_BUNDLE_SCHEMA,
    CanaryEnvelopeV1,
    EnvelopeError,
    check_presubmit_bundle,
    envelope_sha256,
    load_envelope,
)

T0 = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
EXECUTOR_ID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_ID = "demo-acct-01"
SNAPSHOT_ID = "snapshot-pinned-001"
TRADEPLAN_ID = "5scr-plan:" + "a" * 32
RISK_DECISION_ID = "22222222-2222-4222-8222-222222222222"
COMMAND_ID = "33333333-3333-4333-8333-333333333333"
MAGIC = 150015
BROKER_SYMBOL = "EURUSD.a"


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def command(
    *,
    command_id: str = COMMAND_ID,
    idempotency_key: str = "demo-acct-01:5scr:plan-a:1:PLACE_MARKET",
    revision: int = 1,
    execution_mode: str = "DEMO",
    block_role: str = "PARENT",
    volume: float = 0.01,
) -> dict[str, Any]:
    return {
        "event": "execution_command",
        "protocol_version": "wolf15.mt5.exec.v1",
        "command_id": command_id,
        "idempotency_key": idempotency_key,
        "revision": revision,
        "issued_at_utc": iso(T0),
        "not_before_utc": iso(T0),
        "expires_at_utc": iso(T0 + timedelta(minutes=5)),
        "executor_binding": {
            "executor_id": EXECUTOR_ID,
            "account_id": ACCOUNT_ID,
            "login_hash": "sha256:" + "a" * 64,
            "broker_server": "Broker-Demo",
            "execution_mode": execution_mode,
        },
        "source": {
            "source_event": "signal_json",
            "source_schema_version": "wolf15.strategy-5scr.final-signal.v1",
            "source_signal_id": "5scr-signal:" + "b" * 32,
            "source_signal_hash": "sha256:" + "b" * 64,
            "campaign_id": "EURUSD-CAMPAIGN-001",
            "block_id": TRADEPLAN_ID,
            "block_role": block_role,
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
        "action": "PLACE_MARKET",
        "order": {
            "canonical_symbol": "EURUSD",
            "broker_symbol": BROKER_SYMBOL,
            "side": "BUY",
            "order_type": "BUY",
            "volume": volume,
            "entry_price": 1.1,
            "stop_loss": 1.095,
            "take_profit": 1.11,
            "magic": MAGIC,
            "comment_tag": "W15:ABCDEF123456",
            "time_in_force": "GTC",
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
            "risk_snapshot_id": SNAPSHOT_ID,
            "risk_reservation_id": RISK_DECISION_ID,
            "balance_snapshot": 1000,
            "equity_snapshot": 1000,
        },
        "signature": {"algorithm": "HMAC-SHA256", "key_id": "k1", "value": "base64:" + "A" * 43 + "="},
    }


def snapshot(*, snapshot_id: str = SNAPSHOT_ID, captured: datetime = T0, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "captured_at_utc": iso(captured),
        "executor_id": EXECUTOR_ID,
        "account_id": ACCOUNT_ID,
        "currency": "USD",
        "balance": 1000,
        "equity": 1000,
        "floating_pnl": 0,
        "used_margin": 0,
        "free_margin": 1000,
        "margin_mode": "HEDGING",
        "trade_allowed": True,
        "autotrading_enabled": True,
        "open_positions": [],
        "pending_orders": [],
        "symbols": [
            {
                "canonical_symbol": "EURUSD",
                "broker_symbol": BROKER_SYMBOL,
                "digits": 5,
                "point": 0.00001,
                "tick_size": 0.00001,
                "tick_value_profit": 1,
                "tick_value_loss": 1,
                "volume_min": 0.01,
                "volume_max": 100,
                "volume_step": 0.01,
                "stops_level_points": 0,
                "freeze_level_points": 0,
            }
        ],
    }
    payload.update(overrides)
    return payload


OPEN_POSITION = {
    "position_id": 7001,
    "symbol": BROKER_SYMBOL,
    "side": "BUY",
    "volume": 0.01,
    "entry_price": 1.1,
    "current_price": 1.1,
    "magic": MAGIC,
    "floating_pnl": 0,
}


def bundle(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PRESUBMIT_BUNDLE_SCHEMA,
        "envelope_sha256": ENVELOPE_V1_SHA256,
        "account": {"trade_mode": 0},
        "commands": [command()],
        "pinned_snapshot": snapshot(),
        "latest_snapshot": snapshot(snapshot_id="snapshot-latest-002", captured=T0 + timedelta(seconds=5)),
        "latest_state_veto": {
            "pinned_snapshot_id": SNAPSHOT_ID,
            "latest_snapshot_id": "snapshot-latest-002",
            "result": None,
        },
        "ea_final_preflight": {"ea_version": ENGINEERING_DEMO_CANARY_EA_VERSION, "final_preflight": "REQUIRED"},
    }
    payload.update(overrides)
    return payload


def check(payload: dict[str, Any]) -> dict[str, Any]:
    return check_presubmit_bundle(payload, envelope=load_envelope())


def test_shipped_envelope_is_frozen_exact_and_pinned() -> None:
    raw = json.loads(ENVELOPE_V1_PATH.read_text(encoding="utf-8"))
    assert raw == {
        "schema_version": "wolf15.demo-canary.envelope.v1",
        "ACCOUNT": "DEMO",
        "MAX_SUBMIT": 1,
        "AUTO_RETRY": False,
        "PYRAMIDING": False,
        "MULTIPLE_POSITION": False,
        "FLAT_STATE_REQUIRED": True,
        "LATEST_STATE_VETO": "REQUIRED",
        "EA_FINAL_PREFLIGHT": "REQUIRED",
    }
    assert envelope_sha256(load_envelope()) == ENVELOPE_V1_SHA256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ACCOUNT", "LIVE"),
        ("MAX_SUBMIT", 2),
        ("AUTO_RETRY", True),
        ("PYRAMIDING", True),
        ("MULTIPLE_POSITION", True),
        ("FLAT_STATE_REQUIRED", False),
        ("LATEST_STATE_VETO", "OPTIONAL"),
        ("EA_FINAL_PREFLIGHT", "OPTIONAL"),
    ],
)
def test_envelope_cannot_be_loosened(tmp_path: Path, field: str, value: object) -> None:
    raw = json.loads(ENVELOPE_V1_PATH.read_text(encoding="utf-8"))
    raw[field] = value
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(EnvelopeError, match="ENVELOPE_INVALID"):
        load_envelope(path)


def test_envelope_with_extra_field_or_wrong_pin_is_refused(tmp_path: Path) -> None:
    raw = json.loads(ENVELOPE_V1_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps({**raw, "MAX_LOSS": 5}), encoding="utf-8")
    with pytest.raises(EnvelopeError, match="ENVELOPE_INVALID"):
        load_envelope(path)
    with pytest.raises(EnvelopeError, match="ENVELOPE_SHA256_MISMATCH"):
        load_envelope(expected_sha256="sha256:" + "0" * 64)


def test_clean_bundle_is_within_envelope_but_never_submit_authority() -> None:
    decision = check(bundle())
    assert decision["status"] == "WITHIN_ENVELOPE", decision["refusals"]
    assert decision["refusals"] == []
    assert decision["SUBMIT_AUTHORITY"] is False
    assert decision["envelope_sha256"] == ENVELOPE_V1_SHA256


def test_checker_never_mutates_the_bundle() -> None:
    payload = bundle(commands=[command(), command(command_id="44444444-4444-4444-8444-444444444444")])
    before = copy.deepcopy(payload)
    check(payload)
    assert payload == before


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"account": {"trade_mode": 2}}, "ACCOUNT_NOT_DEMO"),
        ({"account": {"trade_mode": False}}, "ACCOUNT_NOT_DEMO"),
        ({"account": None}, "ACCOUNT_EVIDENCE_MISSING"),
        ({"commands": [command(execution_mode="LIVE")]}, "EXECUTOR_NOT_DEMO"),
        (
            {
                "commands": [
                    command(),
                    command(command_id="44444444-4444-4444-8444-444444444444", idempotency_key="other-key-0002"),
                ]
            },
            "MULTIPLE_COMMANDS",
        ),
        ({"commands": [command(), command()]}, "DUPLICATE_IDEMPOTENCY_KEY"),
        ({"commands": []}, "NO_COMMAND"),
        ({"commands": None}, "COMMAND_EVIDENCE_MISSING"),
        ({"commands": [command(revision=2)]}, "AUTO_RETRY_REVISION_PRESENT"),
        ({"commands": [command(block_role="CHILD")]}, "PYRAMIDING_NON_PARENT_ROLE"),
        ({"pinned_snapshot": snapshot(open_positions=[OPEN_POSITION])}, "NOT_FLAT_OPEN_POSITIONS"),
        ({"pinned_snapshot": snapshot(trade_allowed=False)}, "TERMINAL_TRADING_DISABLED"),
        ({"pinned_snapshot": None}, "PINNED_SNAPSHOT_MISSING"),
        ({"pinned_snapshot": snapshot(snapshot_id="other-snapshot")}, "COMMAND_SNAPSHOT_BINDING_MISMATCH"),
        ({"latest_state_veto": None}, "LATEST_STATE_VETO_EVIDENCE_MISSING"),
        ({"latest_snapshot": None}, "LATEST_STATE_VETO_EVIDENCE_MISSING"),
        ({"ea_final_preflight": None}, "EA_FINAL_PREFLIGHT_EVIDENCE_MISSING"),
        (
            {"ea_final_preflight": {"ea_version": "0.0-legacy", "final_preflight": "REQUIRED"}},
            "EA_FINAL_PREFLIGHT_EA_VERSION_MISMATCH",
        ),
        (
            {"ea_final_preflight": {"ea_version": ENGINEERING_DEMO_CANARY_EA_VERSION}},
            "EA_FINAL_PREFLIGHT_EVIDENCE_INVALID",
        ),
        ({"envelope_sha256": "sha256:" + "0" * 64}, "ENVELOPE_SHA256_MISMATCH"),
        ({"envelope_sha256": None}, "ENVELOPE_SHA256_MISSING"),
        ({"schema_version": "other"}, "BUNDLE_SCHEMA_INVALID"),
    ],
)
def test_out_of_envelope_bundle_is_refused(overrides: dict[str, Any], code: str) -> None:
    decision = check(bundle(**overrides))
    assert decision["status"] == "REFUSED"
    assert code in decision["refusals"]
    assert decision["SUBMIT_AUTHORITY"] is False


def test_command_referencing_existing_position_is_pyramiding() -> None:
    raw = command()
    raw["order"]["broker_position_id"] = 7001
    decision = check(bundle(commands=[raw]))
    assert "PYRAMIDING_EXISTING_BROKER_REFERENCE" in decision["refusals"]


def test_not_flat_latest_state_is_vetoed_by_the_canonical_predicate() -> None:
    latest = snapshot(snapshot_id="snapshot-latest-002", open_positions=[OPEN_POSITION])
    decision = check(
        bundle(
            latest_snapshot=latest,
            latest_state_veto={
                "pinned_snapshot_id": SNAPSHOT_ID,
                "latest_snapshot_id": "snapshot-latest-002",
                "result": "latest account state is not flat",
            },
        )
    )
    assert decision["status"] == "REFUSED"
    assert decision["refusals"] == ["LATEST_STATE_VETOED"]


def test_recorded_veto_that_disagrees_with_recomputation_is_refused() -> None:
    latest = snapshot(snapshot_id="snapshot-latest-002", open_positions=[OPEN_POSITION])
    decision = check(bundle(latest_snapshot=latest))
    assert {"LATEST_STATE_VETO_RECORD_MISMATCH", "LATEST_STATE_VETOED"} <= set(decision["refusals"])


def test_veto_reuses_repository_predicate_exactly() -> None:
    pinned = AccountSnapshotV1.model_validate(snapshot())
    cases = [
        snapshot(snapshot_id="snap-002"),
        snapshot(snapshot_id="snap-002", trade_allowed=False),
        snapshot(snapshot_id="snap-002", margin_mode="NETTING"),
        snapshot(snapshot_id="snap-002", symbols=[]),
    ]
    seen: list[Any] = []

    def spy(*args: Any, **kwargs: Any) -> str | None:
        result = engineering_canary_latest_state_veto(*args, **kwargs)
        seen.append(result)
        return result

    for latest in cases:
        expected = engineering_canary_latest_state_veto(
            AccountSnapshotV1.model_validate(latest), pinned, canonical_symbol="EURUSD", broker_symbol=BROKER_SYMBOL
        )
        payload = bundle(
            latest_snapshot=latest,
            latest_state_veto={"pinned_snapshot_id": SNAPSHOT_ID, "latest_snapshot_id": "snap-002", "result": expected},
        )
        decision = check_presubmit_bundle(payload, envelope=load_envelope(), latest_state_veto=spy)
        assert ("LATEST_STATE_VETOED" in decision["refusals"]) is (expected is not None)
        assert "LATEST_STATE_VETO_RECORD_MISMATCH" not in decision["refusals"]
    assert len(seen) == len(cases)


def test_envelope_model_is_immutable() -> None:
    envelope = load_envelope()
    with pytest.raises(ValueError):
        envelope.MAX_SUBMIT = 2  # type: ignore[misc]
    assert isinstance(envelope, CanaryEnvelopeV1)
