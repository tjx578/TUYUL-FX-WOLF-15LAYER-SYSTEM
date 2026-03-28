"""Tests for inter-service Redis contract validation (ARCH-GAP-01).

Validates that Pydantic contracts reject malformed data at service boundaries
and that round-trip serialization (model → stream fields → model) is lossless.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from contracts.execution_queue_contract import ExecutionQueuePayload
from contracts.redis_stream_contracts import (
    ExecutionIntentPayload,
    OrchestratorCommand,
    VerdictPayload,
    WorkerResultPayload,
)

# ── Helpers ───────────────────────────────────────────────────────


def _valid_execution_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "request_id": uuid.uuid4().hex,
        "signal_id": "sig_abc123",
        "account_id": "acc_001",
        "symbol": "EURUSD",
        "verdict": "EXECUTE",
        "direction": "BUY",
        "entry_price": 1.1234,
        "stop_loss": 1.1200,
        "take_profit_1": 1.1300,
        "lot_size": 0.5,
        "order_type": "BUY_LIMIT",
        "execution_mode": "TP1_ONLY",
        "operator": "system",
    }
    base.update(overrides)
    return base


def _valid_verdict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "signal_id": "sig_001",
        "symbol": "GBPUSD",
        "verdict": "EXECUTE",
        "confidence": 0.85,
        "direction": "SELL",
        "entry_price": 1.2700,
        "stop_loss": 1.2750,
        "take_profit_1": 1.2600,
    }
    base.update(overrides)
    return base


def _valid_execution_intent(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "execution_intent_id": "ei_abcdef",
        "take_id": "take_001",
        "signal_id": "sig_001",
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": "1.1234",
        "stop_loss": "1.1200",
        "take_profit_1": "1.1300",
        "account_id": "acc_001",
        "firewall_id": "fw_001",
        "timestamp": "2026-03-18T12:00:00+00:00",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════
# ExecutionQueuePayload
# ═══════════════════════════════════════════════════════════════════


class TestExecutionQueuePayload:
    def test_valid_payload_accepted(self) -> None:
        p = ExecutionQueuePayload(**_valid_execution_payload())
        assert p.symbol == "EURUSD"
        assert p.lot_size == 0.5

    def test_round_trip_stream_fields(self) -> None:
        original = ExecutionQueuePayload(**_valid_execution_payload())
        fields = original.to_stream_fields()
        assert all(isinstance(v, str) for v in fields.values())
        # Reconstruct from string fields (as consumer would receive)
        rebuilt = ExecutionQueuePayload.model_validate(fields)
        assert rebuilt.symbol == original.symbol
        assert rebuilt.lot_size == original.lot_size

    def test_zero_entry_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="entry_price"):
            ExecutionQueuePayload(**_valid_execution_payload(entry_price=0.0))

    def test_zero_lot_size_rejected(self) -> None:
        with pytest.raises(ValidationError, match="lot_size"):
            ExecutionQueuePayload(**_valid_execution_payload(lot_size=0.0))

    def test_negative_stop_loss_rejected(self) -> None:
        with pytest.raises(ValidationError, match="stop_loss"):
            ExecutionQueuePayload(**_valid_execution_payload(stop_loss=-1.0))

    def test_invalid_direction_rejected(self) -> None:
        with pytest.raises(ValidationError, match="direction"):
            ExecutionQueuePayload(**_valid_execution_payload(direction="LONG"))

    def test_invalid_verdict_rejected(self) -> None:
        with pytest.raises(ValidationError, match="verdict"):
            ExecutionQueuePayload(**_valid_execution_payload(verdict="GO"))

    def test_invalid_order_type_rejected(self) -> None:
        with pytest.raises(ValidationError, match="order_type"):
            ExecutionQueuePayload(**_valid_execution_payload(order_type="MARKET_IF_TOUCHED"))

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ExecutionQueuePayload(**_valid_execution_payload(rogue_field="hack"))

    def test_missing_required_field_rejected(self) -> None:
        data = _valid_execution_payload()
        del data["account_id"]
        with pytest.raises(ValidationError, match="account_id"):
            ExecutionQueuePayload(**data)

    def test_lot_size_over_100_rejected(self) -> None:
        with pytest.raises(ValidationError, match="lot_size"):
            ExecutionQueuePayload(**_valid_execution_payload(lot_size=101.0))


# ═══════════════════════════════════════════════════════════════════
# VerdictPayload
# ═══════════════════════════════════════════════════════════════════


class TestVerdictPayload:
    def test_valid_verdict_accepted(self) -> None:
        v = VerdictPayload(**_valid_verdict())
        assert v.symbol == "GBPUSD"
        assert v.confidence == 0.85

    def test_confidence_above_1_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            VerdictPayload(**_valid_verdict(confidence=1.5))

    def test_confidence_below_0_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            VerdictPayload(**_valid_verdict(confidence=-0.1))

    def test_missing_signal_id_rejected(self) -> None:
        data = _valid_verdict()
        del data["signal_id"]
        with pytest.raises(ValidationError, match="signal_id"):
            VerdictPayload(**data)

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            VerdictPayload(**_valid_verdict(symbol=""))

    def test_extra_analysis_fields_allowed(self) -> None:
        v = VerdictPayload(**_valid_verdict(wolf_score=0.8, tii_score=0.95))
        assert v.symbol == "GBPUSD"  # no ValidationError

    def test_negative_entry_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="entry_price"):
            VerdictPayload(**_valid_verdict(entry_price=-1.0))


# ═══════════════════════════════════════════════════════════════════
# ExecutionIntentPayload
# ═══════════════════════════════════════════════════════════════════


class TestExecutionIntentPayload:
    def test_valid_intent_accepted(self) -> None:
        p = ExecutionIntentPayload(**_valid_execution_intent())
        assert p.execution_intent_id == "ei_abcdef"
        assert p.symbol == "EURUSD"

    def test_round_trip_stream_fields(self) -> None:
        original = ExecutionIntentPayload(**_valid_execution_intent())
        fields = original.to_stream_fields()
        assert all(isinstance(v, str) for v in fields.values())
        rebuilt = ExecutionIntentPayload(**fields)
        assert rebuilt.execution_intent_id == original.execution_intent_id

    def test_missing_take_id_rejected(self) -> None:
        data = _valid_execution_intent()
        del data["take_id"]
        with pytest.raises(ValidationError, match="take_id"):
            ExecutionIntentPayload(**data)

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            ExecutionIntentPayload(**_valid_execution_intent(symbol=""))

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            ExecutionIntentPayload(**_valid_execution_intent(rogue="x"))

    def test_missing_timestamp_rejected(self) -> None:
        data = _valid_execution_intent()
        del data["timestamp"]
        with pytest.raises(ValidationError, match="timestamp"):
            ExecutionIntentPayload(**data)


# ═══════════════════════════════════════════════════════════════════
# WorkerResultPayload
# ═══════════════════════════════════════════════════════════════════


class TestWorkerResultPayload:
    def test_valid_result_accepted(self) -> None:
        w = WorkerResultPayload(job="montecarlo", timestamp="2026-03-18T12:00:00")
        assert w.job == "montecarlo"

    def test_empty_job_rejected(self) -> None:
        with pytest.raises(ValidationError, match="job"):
            WorkerResultPayload(job="", timestamp="2026-03-18T12:00:00")

    def test_extra_job_fields_allowed(self) -> None:
        w = WorkerResultPayload.model_validate({"job": "backtest", "timestamp": "now", "sharpe": 1.5})
        assert w.job == "backtest"


# ═══════════════════════════════════════════════════════════════════
# OrchestratorCommand
# ═══════════════════════════════════════════════════════════════════


class TestOrchestratorCommand:
    def test_valid_command_accepted(self) -> None:
        c = OrchestratorCommand(command="set_mode", mode="LIVE", reason="manual")
        assert c.command == "set_mode"

    def test_empty_command_rejected(self) -> None:
        with pytest.raises(ValidationError, match="command"):
            OrchestratorCommand(command="", mode="LIVE")

    def test_empty_mode_rejected(self) -> None:
        with pytest.raises(ValidationError, match="mode"):
            OrchestratorCommand(command="set_mode", mode="")
