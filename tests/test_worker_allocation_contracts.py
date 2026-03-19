"""
P1-10: Worker & Allocation Contract Tests
============================================
Tests explicit contract schemas for execution queue payload,
worker job contracts, and signal contract immutability.
"""

from __future__ import annotations

import pytest

from contracts.execution_queue_contract import (
    CONTRACT_VERSION,
    ExecutionQueuePayload,
)

# ── Execution Queue Payload ──────────────────────────────────────────────


class TestExecutionQueuePayload:
    @pytest.fixture
    def valid_payload_data(self):
        return {
            "request_id": "req-test-001",
            "signal_id": "SIG-20260215-EURUSD-001",
            "account_id": "ACC-FTMO-001",
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "direction": "BUY",
            "entry_price": 1.0850,
            "stop_loss": 1.0800,
            "take_profit_1": 1.0950,
            "lot_size": 0.1,
            "order_type": "BUY_LIMIT",
            "operator": "admin",
        }

    def test_valid_payload(self, valid_payload_data):
        payload = ExecutionQueuePayload(**valid_payload_data)
        assert payload.contract_version == CONTRACT_VERSION
        assert payload.entry_price == 1.0850
        assert payload.lot_size == 0.1
        assert payload.direction == "BUY"

    def test_default_values(self, valid_payload_data):
        del valid_payload_data["order_type"]
        payload = ExecutionQueuePayload(**valid_payload_data)
        assert payload.order_type == "PENDING_ONLY"
        assert payload.execution_mode == "TP1_ONLY"
        assert payload.contract_version == CONTRACT_VERSION

    def test_rejects_zero_lot_size(self, valid_payload_data):
        valid_payload_data["lot_size"] = 0.0
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_negative_lot_size(self, valid_payload_data):
        valid_payload_data["lot_size"] = -0.1
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_zero_entry_price(self, valid_payload_data):
        valid_payload_data["entry_price"] = 0.0
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_zero_stop_loss(self, valid_payload_data):
        valid_payload_data["stop_loss"] = 0.0
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_zero_take_profit(self, valid_payload_data):
        valid_payload_data["take_profit_1"] = 0.0
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_excessive_lot_size(self, valid_payload_data):
        valid_payload_data["lot_size"] = 101.0
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_invalid_order_type(self, valid_payload_data):
        valid_payload_data["order_type"] = "INVALID_TYPE"
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_invalid_verdict(self, valid_payload_data):
        valid_payload_data["verdict"] = "MAYBE"
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_invalid_direction(self, valid_payload_data):
        valid_payload_data["direction"] = "LONG"
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_extra_fields(self, valid_payload_data):
        valid_payload_data["balance"] = 100_000  # FORBIDDEN — constitutional boundary
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(**valid_payload_data)

    def test_rejects_missing_required_fields(self):
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(
                request_id="req-001",
                # missing everything else
            )  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "order_type",
        ["BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY", "SELL", "PENDING_ONLY"],
    )
    def test_all_valid_order_types(self, valid_payload_data, order_type):
        valid_payload_data["order_type"] = order_type
        payload = ExecutionQueuePayload(**valid_payload_data)
        assert payload.order_type == order_type

    @pytest.mark.parametrize(
        "verdict",
        ["EXECUTE", "EXECUTE_REDUCED_RISK", "HOLD", "NO_TRADE", "ABORT"],
    )
    def test_all_valid_verdicts(self, valid_payload_data, verdict):
        valid_payload_data["verdict"] = verdict
        payload = ExecutionQueuePayload(**valid_payload_data)
        assert payload.verdict == verdict


# ── Stream Serialization ──────────────────────────────────────────────────


class TestStreamSerialization:
    def test_to_stream_fields_all_strings(self):
        payload = ExecutionQueuePayload(
            request_id="req-test-001",
            signal_id="SIG-001",
            account_id="ACC-001",
            symbol="EURUSD",
            verdict="EXECUTE",
            direction="BUY",
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit_1=1.0950,
            lot_size=0.1,
            operator="admin",
        )
        fields = payload.to_stream_fields()
        assert all(isinstance(v, str) for v in fields.values())
        assert fields["entry_price"] == "1.085"
        assert fields["lot_size"] == "0.1"

    def test_roundtrip_serialization(self):
        original = ExecutionQueuePayload(
            request_id="req-roundtrip",
            signal_id="SIG-RT",
            account_id="ACC-RT",
            symbol="GBPUSD",
            verdict="EXECUTE",
            direction="SELL",
            entry_price=1.2650,
            stop_loss=1.2700,
            take_profit_1=1.2550,
            lot_size=0.5,
            order_type="SELL_LIMIT",
            operator="tester",
        )
        fields = original.to_stream_fields()
        restored = ExecutionQueuePayload.from_stream_fields(fields)
        assert restored.request_id == original.request_id
        assert restored.entry_price == original.entry_price
        assert restored.lot_size == original.lot_size
        assert restored.direction == "SELL"


# ── Worker Job Contract Metadata ──────────────────────────────────────────


class TestWorkerJobContracts:
    def test_job_contracts_importable(self):
        from allocation.job_contracts import WORKER_JOB_CONTRACTS

        assert isinstance(WORKER_JOB_CONTRACTS, dict)
        assert len(WORKER_JOB_CONTRACTS) > 0

    def test_worker_contracts_are_frozen(self):
        from allocation.job_contracts import WORKER_JOB_CONTRACTS, WorkerJobContract

        for name, contract in WORKER_JOB_CONTRACTS.items():
            assert isinstance(contract, WorkerJobContract), f"{name} is not a WorkerJobContract"
            # Frozen dataclass — mutation should raise
            with pytest.raises(AttributeError):
                contract.job_name = "hack"  # type: ignore[misc]

    def test_known_workers_registered(self):
        from allocation.job_contracts import WORKER_JOB_CONTRACTS

        expected_names = {"montecarlo", "nightly_backtest", "regime_recalibration"}
        actual_names = set(WORKER_JOB_CONTRACTS.keys())
        assert expected_names.issubset(actual_names), f"Missing workers: {expected_names - actual_names}"


# ── Signal Contract Immutability ──────────────────────────────────────────


class TestSignalContractImmutability:
    def test_signal_contract_is_frozen(self):
        from schemas.signal_contract import SignalContract

        contract = SignalContract(
            signal_id="SIG-001",
            symbol="EURUSD",
            verdict="EXECUTE",
            confidence=0.87,
            timestamp=1700000000.0,
        )
        with pytest.raises(AttributeError):
            contract.verdict = "HOLD"  # type: ignore[misc]

    def test_signal_contract_version_pinned(self):
        from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION

        assert FROZEN_SIGNAL_CONTRACT_VERSION == "2026-03-03"
