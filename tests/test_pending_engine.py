"""Tests for Pending Execution Engine (execution/pending_engine.py)."""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from execution.pending_engine import (
    _BROKER_MAX_LOT,
    _BROKER_MIN_LOT,
    ExecutionMode,
    OrderRequest,
    OrderStatus,
    OrderType,
    PendingEngine,
    _generate_idempotency_key,
    _generate_order_id,
)

NOW = datetime(2026, 2, 15, 14, 0, 0, tzinfo=UTC)


# ── Helpers ──────────────────────────────────────────────────────────


def _now_factory():
    return NOW


def _make_request(**overrides: Any) -> OrderRequest:
    """Build a valid BUY order request with optional overrides."""
    defaults: dict[str, Any] = {
        "signal_id": "SIG-TEST-001",
        "pair": "GBPUSD",
        "order_type": OrderType.BUY,
        "lot_size": 0.10,
        "entry_price": 1.25000,
        "stop_loss": 1.24500,
        "take_profit": 1.26000,
        "comment": "test order",
    }
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _make_sell_request(**overrides: Any) -> OrderRequest:
    defaults: dict[str, Any] = {
        "signal_id": "SIG-TEST-002",
        "pair": "GBPUSD",
        "order_type": OrderType.SELL,
        "lot_size": 0.10,
        "entry_price": 1.25000,
        "stop_loss": 1.25500,
        "take_profit": 1.24000,
        "comment": "test sell",
    }
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _make_engine(mode=ExecutionMode.DRY, **kwargs) -> PendingEngine:
    return PendingEngine(mode=mode, now_factory=_now_factory, **kwargs)


class MockJournalWriter:
    """Test double for JournalWriter protocol."""

    def __init__(self):
        self.entries: list[dict[str, Any]] = []

    def write_j3(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


# ── Order ID Generation ──────────────────────────────────────────────


class TestOrderIdGeneration:
    def test_order_id_contains_signal_prefix(self):
        oid = _generate_order_id("SIG-ABCD-1234")
        assert oid.startswith("TWF-SIG-ABCD")

    def test_order_id_unique(self):
        ids = {_generate_order_id("SIG-001") for _ in range(100)}
        assert len(ids) == 100  # UUID-based, must be unique

    def test_empty_signal_id(self):
        oid = _generate_order_id("")
        assert "NOSIG" in oid


class TestIdempotencyKey:
    def test_same_request_same_key(self):
        r1 = _make_request()
        r2 = _make_request()
        assert _generate_idempotency_key(r1) == _generate_idempotency_key(r2)

    def test_different_signal_different_key(self):
        r1 = _make_request(signal_id="SIG-A")
        r2 = _make_request(signal_id="SIG-B")
        assert _generate_idempotency_key(r1) != _generate_idempotency_key(r2)

    def test_different_price_different_key(self):
        r1 = _make_request(entry_price=1.25000)
        r2 = _make_request(entry_price=1.25100)
        assert _generate_idempotency_key(r1) != _generate_idempotency_key(r2)

    def test_different_lot_different_key(self):
        r1 = _make_request(lot_size=0.10)
        r2 = _make_request(lot_size=0.20)
        assert _generate_idempotency_key(r1) != _generate_idempotency_key(r2)


# ── Structural Validation ────────────────────────────────────────────


class TestStructuralValidation:
    def test_valid_buy_passes(self):
        engine = _make_engine()
        result = engine.submit(_make_request())
        assert result.status == OrderStatus.DRY_RUN
        assert result.errors == ()

    def test_valid_sell_passes(self):
        engine = _make_engine()
        result = engine.submit(_make_sell_request())
        assert result.status == OrderStatus.DRY_RUN

    def test_missing_signal_id_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(signal_id=""))
        assert result.status == OrderStatus.REJECTED
        assert any("signal_id" in e for e in result.errors)

    def test_whitespace_signal_id_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(signal_id="   "))
        assert result.status == OrderStatus.REJECTED

    def test_negative_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(entry_price=-1.0))
        assert result.status == OrderStatus.REJECTED
        assert any("entry_price" in e for e in result.errors)

    def test_zero_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(entry_price=0.0))
        assert result.status == OrderStatus.REJECTED

    def test_negative_sl_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(stop_loss=-0.5))
        assert result.status == OrderStatus.REJECTED

    def test_negative_tp_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(take_profit=-0.5))
        assert result.status == OrderStatus.REJECTED

    def test_lot_below_min_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(lot_size=0.001))
        assert result.status == OrderStatus.REJECTED
        assert any("lot_size" in e for e in result.errors)

    def test_lot_above_max_rejected(self):
        engine = _make_engine()
        result = engine.submit(_make_request(lot_size=200.0))
        assert result.status == OrderStatus.REJECTED

    def test_lot_above_override_max_rejected(self):
        engine = _make_engine(max_lot_override=0.50)
        result = engine.submit(_make_request(lot_size=0.60))
        assert result.status == OrderStatus.REJECTED
        assert any("0.5" in e for e in result.errors)

    def test_buy_sl_above_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                order_type=OrderType.BUY,
                entry_price=1.25000,
                stop_loss=1.26000,  # Above entry
                take_profit=1.27000,
            )
        )
        assert result.status == OrderStatus.REJECTED
        assert any("SL must be below" in e for e in result.errors)

    def test_buy_tp_below_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                order_type=OrderType.BUY,
                entry_price=1.25000,
                stop_loss=1.24000,
                take_profit=1.24000,  # Below entry
            )
        )
        assert result.status == OrderStatus.REJECTED
        assert any("TP must be above" in e for e in result.errors)

    def test_sell_sl_below_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(
            _make_sell_request(
                stop_loss=1.24000,  # Below entry
            )
        )
        assert result.status == OrderStatus.REJECTED
        assert any("SL must be above" in e for e in result.errors)

    def test_sell_tp_above_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(
            _make_sell_request(
                take_profit=1.26000,  # Above entry
            )
        )
        assert result.status == OrderStatus.REJECTED
        assert any("TP must be below" in e for e in result.errors)

    def test_sl_equals_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                entry_price=1.25000,
                stop_loss=1.25000,
            )
        )
        assert result.status == OrderStatus.REJECTED
        assert any("SL cannot equal" in e for e in result.errors)

    def test_tp_equals_entry_rejected(self):
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                entry_price=1.25000,
                take_profit=1.25000,
            )
        )
        assert result.status == OrderStatus.REJECTED
        assert any("TP cannot equal" in e for e in result.errors)

    def test_buy_limit_validates_as_buy(self):
        engine = _make_engine()
        result = engine.submit(_make_request(order_type=OrderType.BUY_LIMIT))
        assert result.status == OrderStatus.DRY_RUN

    def test_sell_stop_validates_as_sell(self):
        engine = _make_engine()
        result = engine.submit(_make_sell_request(order_type=OrderType.SELL_STOP))
        assert result.status == OrderStatus.DRY_RUN


# ── Constitutional: No Strategy Logic ────────────────────────────────


class TestConstitutionalNoStrategy:
    """Execution must NOT enforce strategy constraints."""

    def test_no_rr_enforcement(self):
        """R:R < 1 should NOT be rejected by execution.
        A 0.5 R:R is bad strategy but structurally valid."""
        engine = _make_engine()
        # BUY: 50 pip SL, 25 pip TP -> R:R = 0.5
        result = engine.submit(
            _make_request(
                entry_price=1.25000,
                stop_loss=1.24500,
                take_profit=1.25250,
            )
        )
        assert result.status == OrderStatus.DRY_RUN, "Execution must not reject based on R:R ratio"

    def test_no_min_sl_pips_enforcement(self):
        """Very tight SL (1 pip) is structurally valid."""
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                entry_price=1.25000,
                stop_loss=1.24990,  # 1 pip SL
                take_profit=1.25100,
            )
        )
        assert result.status == OrderStatus.DRY_RUN, "Execution must not enforce minimum SL distance"

    def test_no_max_sl_pips_enforcement(self):
        """Very wide SL (1000 pips) is structurally valid."""
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                entry_price=1.25000,
                stop_loss=1.15000,  # 1000 pips
                take_profit=1.35000,
            )
        )
        assert result.status == OrderStatus.DRY_RUN, "Execution must not enforce maximum SL distance"

    def test_no_pip_value_lookup(self):
        """Engine must not derive pip values -- that's L10 analysis."""
        engine = _make_engine()
        result = engine.submit(_make_request(pair="ZARJPY"))
        # Unknown pair is fine -- engine doesn't need pip values
        assert result.status == OrderStatus.DRY_RUN

    def test_no_account_balance_access(self):
        """Engine has no concept of account balance."""
        engine = _make_engine()
        # There's nowhere to even pass balance -- by design
        assert not hasattr(engine, "balance")
        assert not hasattr(engine, "equity")


# ── Idempotency ──────────────────────────────────────────────────────


class TestIdempotency:
    def test_duplicate_rejected(self):
        engine = _make_engine()
        req = _make_request()
        r1 = engine.submit(req)
        r2 = engine.submit(req)

        assert r1.status == OrderStatus.DRY_RUN
        assert r2.status == OrderStatus.REJECTED
        assert "DUPLICATE_ORDER" in r2.errors

    def test_duplicate_references_original(self):
        engine = _make_engine()
        req = _make_request()
        r1 = engine.submit(req)
        r2 = engine.submit(req)

        assert r1.order_id in r2.message

    def test_different_signals_not_duplicate(self):
        engine = _make_engine()
        r1 = engine.submit(_make_request(signal_id="SIG-001"))
        r2 = engine.submit(_make_request(signal_id="SIG-002"))

        assert r1.status == OrderStatus.DRY_RUN
        assert r2.status == OrderStatus.DRY_RUN

    def test_duplicate_still_journaled(self):
        journal = MockJournalWriter()
        engine = _make_engine(journal_writer=journal)
        req = _make_request()

        engine.submit(req)
        engine.submit(req)  # Duplicate

        assert len(journal.entries) == 2
        assert journal.entries[1]["status"] == "REJECTED"

    def test_executed_count_excludes_duplicates(self):
        engine = _make_engine()
        req = _make_request()
        engine.submit(req)
        engine.submit(req)

        assert engine.executed_count == 1


# ── DRY Mode ─────────────────────────────────────────────────────────


class TestDryMode:
    def test_dry_returns_dry_run(self):
        engine = _make_engine(mode=ExecutionMode.DRY)
        result = engine.submit(_make_request())
        assert result.status == OrderStatus.DRY_RUN
        assert result.execution_mode == "DRY"

    def test_dry_populates_all_fields(self):
        engine = _make_engine(mode=ExecutionMode.DRY)
        result = engine.submit(_make_request())
        assert result.pair == "GBPUSD"
        assert result.order_type == "BUY"
        assert result.lot_size == 0.10
        assert result.signal_id == "SIG-TEST-001"


# ── PAPER Mode ───────────────────────────────────────────────────────


class TestPaperMode:
    def test_paper_returns_paper_filled(self):
        engine = _make_engine(mode=ExecutionMode.PAPER)
        result = engine.submit(_make_request())
        assert result.status == OrderStatus.PAPER_FILLED
        assert result.execution_mode == "PAPER"

    def test_paper_logs_to_journal(self):
        journal = MockJournalWriter()
        engine = _make_engine(mode=ExecutionMode.PAPER, journal_writer=journal)
        engine.submit(_make_request())

        assert len(journal.entries) == 1
        assert journal.entries[0]["journal_type"] == "J3"
        assert journal.entries[0]["status"] == "PAPER_FILLED"


# ── LIVE Mode ────────────────────────────────────────────────────────


class TestLiveMode:
    def test_live_success(self):
        engine = _make_engine(mode=ExecutionMode.LIVE)

        mock_response = json.dumps({"result": "OK", "ticket": 12345, "price": 1.25010})

        # Since _execute_live does a local import, we patch socket directly
        with patch("socket.socket") as mock_socket_cls:
            mock_conn = MagicMock()
            mock_conn.recv.return_value = mock_response.encode()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = engine.submit(_make_request())

        assert result.status == OrderStatus.FILLED
        assert result.mt5_ticket == 12345
        assert result.entry_price == 1.25010

    def test_live_mt5_rejection(self):
        engine = _make_engine(mode=ExecutionMode.LIVE)

        mock_response = json.dumps({"result": "ERROR", "error": "Invalid volume"})

        with patch("socket.socket") as mock_socket_cls:
            mock_conn = MagicMock()
            mock_conn.recv.return_value = mock_response.encode()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = engine.submit(_make_request())

        assert result.status == OrderStatus.REJECTED
        assert any("Invalid volume" in e for e in result.errors)

    def test_live_connection_refused(self):
        engine = _make_engine(mode=ExecutionMode.LIVE)

        with patch("socket.socket") as mock_socket_cls:
            mock_conn = MagicMock()
            mock_conn.connect.side_effect = ConnectionRefusedError("refused")
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = engine.submit(_make_request())

        assert result.status == OrderStatus.REJECTED
        assert any("CONNECTION_FAILED" in e for e in result.errors)

    def test_live_timeout(self):
        engine = _make_engine(mode=ExecutionMode.LIVE)

        with patch("socket.socket") as mock_socket_cls:
            mock_conn = MagicMock()
            mock_conn.connect.side_effect = TimeoutError("timed out")
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = engine.submit(_make_request())

        assert result.status == OrderStatus.REJECTED

    def test_live_empty_response(self):
        engine = _make_engine(mode=ExecutionMode.LIVE)

        with patch("socket.socket") as mock_socket_cls:
            mock_conn = MagicMock()
            mock_conn.recv.return_value = b""
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = engine.submit(_make_request())

        assert result.status == OrderStatus.REJECTED
        assert any("EMPTY_RESPONSE" in e for e in result.errors)

    def test_live_invalid_json_response(self):
        engine = _make_engine(mode=ExecutionMode.LIVE)

        with patch("socket.socket") as mock_socket_cls:
            mock_conn = MagicMock()
            mock_conn.recv.return_value = b"NOT JSON"
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = engine.submit(_make_request())

        assert result.status == OrderStatus.REJECTED
        assert any("INVALID_RESPONSE" in e for e in result.errors)


# ── Journal Integration ──────────────────────────────────────────────


class TestJournalIntegration:
    def test_successful_order_journaled(self):
        journal = MockJournalWriter()
        engine = _make_engine(journal_writer=journal)
        engine.submit(_make_request())

        assert len(journal.entries) == 1
        entry = journal.entries[0]
        assert entry["journal_type"] == "J3"
        assert entry["signal_id"] == "SIG-TEST-001"
        assert entry["order_id"].startswith("TWF-")

    def test_rejected_order_journaled(self):
        journal = MockJournalWriter()
        engine = _make_engine(journal_writer=journal)
        engine.submit(_make_request(entry_price=-1.0))

        assert len(journal.entries) == 1
        assert journal.entries[0]["status"] == "REJECTED"

    def test_all_j3_fields_present(self):
        journal = MockJournalWriter()
        engine = _make_engine(journal_writer=journal)
        engine.submit(_make_request())

        entry = journal.entries[0]
        for key in (
            "journal_type",
            "order_id",
            "signal_id",
            "status",
            "pair",
            "order_type",
            "lot_size",
            "entry_price",
            "stop_loss",
            "take_profit",
            "execution_mode",
            "message",
            "errors",
            "mt5_ticket",
            "timestamp",
        ):
            assert key in entry, f"missing J3 key: {key}"

    def test_journal_failure_doesnt_block(self):
        """If journal write fails, the result is still returned."""

        class FailingJournal:
            def write_j3(self, entry):
                raise RuntimeError("disk full")

        engine = _make_engine(journal_writer=FailingJournal())
        result = engine.submit(_make_request())

        # Engine still returns a result
        assert result.status == OrderStatus.DRY_RUN

    def test_get_journal_with_internal(self):
        engine = _make_engine()
        engine.submit(_make_request())
        journal = engine.get_journal()
        assert len(journal) == 1

    def test_get_journal_empty_with_external(self):
        """When using external writer, get_journal returns empty."""
        journal = MockJournalWriter()
        engine = _make_engine(journal_writer=journal)
        engine.submit(_make_request())

        # get_journal only returns internal entries
        assert engine.get_journal() == []
        # But the external journal has the entry
        assert len(journal.entries) == 1


# ── Mode Resolution ──────────────────────────────────────────────────


class TestModeResolution:
    def test_explicit_mode(self):
        engine = PendingEngine(mode=ExecutionMode.PAPER)
        assert engine.mode == ExecutionMode.PAPER

    def test_env_mode(self, monkeypatch):
        monkeypatch.setenv("TUYUL_EXECUTION_MODE", "PAPER")
        engine = PendingEngine()
        assert engine.mode == ExecutionMode.PAPER

    def test_invalid_env_defaults_dry(self, monkeypatch):
        monkeypatch.setenv("TUYUL_EXECUTION_MODE", "YOLO")
        engine = PendingEngine()
        assert engine.mode == ExecutionMode.DRY

    def test_missing_env_defaults_dry(self, monkeypatch):
        monkeypatch.delenv("TUYUL_EXECUTION_MODE", raising=False)
        engine = PendingEngine()
        assert engine.mode == ExecutionMode.DRY

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TUYUL_EXECUTION_MODE", "LIVE")
        engine = PendingEngine(mode=ExecutionMode.DRY)
        assert engine.mode == ExecutionMode.DRY


# ── OrderResult Immutability ─────────────────────────────────────────


class TestOrderResultImmutable:
    def test_frozen(self):
        engine = _make_engine()
        result = engine.submit(_make_request())
        with pytest.raises(AttributeError):
            result.status = OrderStatus.FILLED  # type: ignore

    def test_errors_is_tuple(self):
        engine = _make_engine()
        result = engine.submit(_make_request())
        assert isinstance(result.errors, tuple)


# ── OrderRequest Immutability ────────────────────────────────────────


class TestOrderRequestImmutable:
    def test_frozen(self):
        req = _make_request()
        with pytest.raises(AttributeError):
            req.lot_size = 1.0  # type: ignore


# ── Timestamp Injection ─────────────────────────────────────────────


class TestTimestampInjection:
    def test_uses_injected_now(self):
        engine = _make_engine()
        result = engine.submit(_make_request())
        assert result.timestamp == NOW.isoformat()

    def test_deterministic_across_calls(self):
        engine = _make_engine()
        r1 = engine.submit(_make_request(signal_id="SIG-A"))
        r2 = engine.submit(_make_request(signal_id="SIG-B"))
        assert r1.timestamp == r2.timestamp


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_gold_pair_structurally_valid(self):
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                pair="XAUUSD",
                entry_price=2000.00,
                stop_loss=1995.00,
                take_profit=2015.00,
            )
        )
        assert result.status == OrderStatus.DRY_RUN

    def test_jpy_pair_structurally_valid(self):
        engine = _make_engine()
        result = engine.submit(
            _make_request(
                pair="USDJPY",
                entry_price=155.000,
                stop_loss=154.500,
                take_profit=156.000,
            )
        )
        assert result.status == OrderStatus.DRY_RUN

    def test_many_orders_different_signals(self):
        engine = _make_engine()
        for i in range(50):
            result = engine.submit(_make_request(signal_id=f"SIG-{i:04d}"))
            assert result.status == OrderStatus.DRY_RUN
        assert engine.executed_count == 50

    def test_min_lot_accepted(self):
        engine = _make_engine()
        result = engine.submit(_make_request(lot_size=_BROKER_MIN_LOT))
        assert result.status == OrderStatus.DRY_RUN

    def test_max_lot_accepted(self):
        engine = _make_engine()
        result = engine.submit(_make_request(lot_size=_BROKER_MAX_LOT))
        assert result.status == OrderStatus.DRY_RUN

    def test_signal_id_preserved_in_result(self):
        engine = _make_engine()
        result = engine.submit(_make_request(signal_id="MY-VERDICT-XYZ"))
        assert result.signal_id == "MY-VERDICT-XYZ"


# ── Import JSON for LIVE tests ──────────────────────────────────────
