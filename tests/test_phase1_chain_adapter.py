"""Tests for Phase 1 Chain Adapter — always-forward scoring chain."""

from __future__ import annotations

import constitution.phase1_chain_adapter as phase1_chain_adapter_module
from constitution.phase1_chain_adapter import (
    ChainStatus,
    Phase1ChainAdapter,
)

# ── Helpers ───────────────────────────────────────────────────


def _l1_pass() -> dict:
    return {"valid": True, "continuation_allowed": True, "status": "PASS", "blocker_codes": []}


def _l1_warn() -> dict:
    return {
        "valid": True,
        "continuation_allowed": True,
        "status": "WARN",
        "blocker_codes": [],
        "warning_codes": ["STALE_PRESERVED"],
    }


def _l1_fail() -> dict:
    return {
        "valid": False,
        "continuation_allowed": False,
        "status": "FAIL",
        "blocker_codes": ["DATA_UNAVAILABLE"],
    }


def _l2_pass() -> dict:
    return {"valid": True, "continuation_allowed": True, "status": "PASS", "blocker_codes": []}


def _l2_fail() -> dict:
    return {
        "valid": False,
        "continuation_allowed": False,
        "status": "FAIL",
        "blocker_codes": ["MTA_MISALIGNED"],
    }


def _l3_pass() -> dict:
    return {"valid": True, "continuation_allowed": True, "status": "PASS", "blocker_codes": []}


def _l3_warn() -> dict:
    return {
        "valid": True,
        "continuation_allowed": True,
        "status": "WARN",
        "blocker_codes": [],
        "warning_codes": ["STALE_CLOSE_DATA"],
    }


def _l3_fail() -> dict:
    return {
        "valid": False,
        "continuation_allowed": False,
        "status": "FAIL",
        "blocker_codes": ["TREND_CONFIRMATION_UNAVAILABLE"],
    }


# ═══════════════════════════════════════════════════════════════
# §1  Chain completes successfully
# ═══════════════════════════════════════════════════════════════


class TestChainAllPass:
    def test_all_pass(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.PASS
        assert result.continuation_allowed is True
        assert result.halted_at is None
        assert result.l1["status"] == "PASS"
        assert result.l2["status"] == "PASS"
        assert result.l3["status"] == "PASS"
        assert result.errors == []
        assert "L1" in result.timing_ms
        assert "L2" in result.timing_ms
        assert "L3" in result.timing_ms

    def test_all_pass_to_dict(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("GBPUSD")
        d = result.to_dict()
        assert d["phase"] == "PHASE_1"
        assert d["status"] == "PASS"
        assert d["continuation_allowed"] is True
        assert d["halted_at"] is None


# ═══════════════════════════════════════════════════════════════
# §2  Chain always-forward on L1 failure
# ═══════════════════════════════════════════════════════════════


class TestChainL1Failure:
    def test_l1_fail_continues(self):
        l2_called = False
        l3_called = False

        def _l2(sym):
            nonlocal l2_called
            l2_called = True
            return _l2_pass()

        def _l3(sym):
            nonlocal l3_called
            l3_called = True
            return _l3_pass()

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_fail(),
            l2_callable=_l2,
            l3_callable=_l3,
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True  # Always forward to L12
        assert result.halted_at is None  # Chain never halts
        assert result.failed_at == "L1"
        assert l2_called, "L2 MUST be called even when L1 fails"
        assert l3_called, "L3 MUST be called even when L1 fails"
        assert any("L1_FAIL" in e for e in result.errors)
        assert any("L1_BLOCKER:DATA_UNAVAILABLE" in e for e in result.errors)

    def test_l1_exception_continues(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: (_ for _ in ()).throw(RuntimeError("L1 boom")),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True
        assert result.failed_at == "L1"
        assert any("L1_EXCEPTION" in e for e in result.errors)


# ═══════════════════════════════════════════════════════════════
# §3  Chain always-forward on L2 failure
# ═══════════════════════════════════════════════════════════════


class TestChainL2Failure:
    def test_l2_fail_continues(self):
        l3_called = False

        def _l3(sym):
            nonlocal l3_called
            l3_called = True
            return _l3_pass()

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_fail(),
            l3_callable=_l3,
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True  # Always forward to L12
        assert result.failed_at == "L2"
        assert l3_called, "L3 MUST be called even when L2 fails"
        assert result.l1["status"] == "PASS"  # L1 completed
        assert any("L2_FAIL" in e for e in result.errors)

    def test_l2_exception_continues(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: (_ for _ in ()).throw(ValueError("L2 crash")),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True
        assert result.failed_at == "L2"


# ═══════════════════════════════════════════════════════════════
# §4  Chain always-forward on L3 failure
# ═══════════════════════════════════════════════════════════════


class TestChainL3Failure:
    def test_l3_fail_continues(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_fail(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True  # Always forward to L12
        assert result.halted_at is None
        assert result.failed_at == "L3"
        assert result.l1["status"] == "PASS"
        assert result.l2["status"] == "PASS"
        assert result.l3["status"] == "FAIL"
        assert any("L3_FAIL" in e for e in result.errors)

    def test_l3_exception_continues(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: (_ for _ in ()).throw(RuntimeError("L3 boom")),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True
        assert result.failed_at == "L3"

    def test_l3_exception_log_interpolates_exception(self, monkeypatch):
        messages: list[str] = []

        class _FakeLogger:
            def error(self, message: str, *args, **kwargs) -> None:
                messages.append(message)
                assert args == ()

            def warning(self, message: str, *args, **kwargs) -> None:
                messages.append(message)
                assert args == ()

            def info(self, message: str, *args, **kwargs) -> None:
                messages.append(message)
                assert args == ()

        monkeypatch.setattr(phase1_chain_adapter_module, "logger", _FakeLogger())

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: (_ for _ in ()).throw(RuntimeError("L3 boom")),
        )

        result = adapter.execute("EURUSD")

        assert result.failed_at == "L3"
        assert any("[Phase1] L3 raised: RuntimeError: L3 boom" in msg for msg in messages)
        assert not any("%s" in msg for msg in messages)


# ═══════════════════════════════════════════════════════════════
# §5  WARN propagation
# ═══════════════════════════════════════════════════════════════


class TestWarnPropagation:
    def test_l1_warn_propagates(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_warn(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.WARN
        assert result.continuation_allowed is True
        assert result.halted_at is None
        assert any("L1:" in w for w in result.warnings)

    def test_l3_warn_propagates(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_warn(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.WARN
        assert result.continuation_allowed is True
        assert any("L3:" in w for w in result.warnings)

    def test_multiple_warns(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_warn(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_warn(),
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.WARN
        assert result.continuation_allowed is True


# ═══════════════════════════════════════════════════════════════
# §6  L2 injection
# ═══════════════════════════════════════════════════════════════


class TestL2Injection:
    def test_l2_output_injected_before_l3(self):
        injected_l2 = {}

        def _injector(l2_out):
            injected_l2.update(l2_out)

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
            l3_l2_injector=_injector,
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.PASS
        assert injected_l2.get("continuation_allowed") is True

    def test_l2_injection_called_even_if_l1_fails(self):
        injector_called = False

        def _injector(l2_out):
            nonlocal injector_called
            injector_called = True

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_fail(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
            l3_l2_injector=_injector,
        )
        adapter.execute("EURUSD")
        assert injector_called, "L2 always runs → injector MUST be called"


# ═══════════════════════════════════════════════════════════════
# §7  Legacy backward compatibility
# ═══════════════════════════════════════════════════════════════


class TestLegacyCompat:
    def test_legacy_valid_field_accepted(self):
        """Layers that only have 'valid' (no continuation_allowed) should work."""
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: {"valid": True},
            l2_callable=lambda sym: {"valid": True},
            l3_callable=lambda sym: {"valid": True},
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.PASS
        assert result.continuation_allowed is True

    def test_legacy_valid_false_continues(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: {"valid": False},
            l2_callable=lambda sym: {"valid": True},
            l3_callable=lambda sym: {"valid": True},
        )
        result = adapter.execute("EURUSD")
        assert result.status == ChainStatus.FAIL
        assert result.continuation_allowed is True
        assert result.failed_at == "L1"
        assert result.halted_at is None


# ═══════════════════════════════════════════════════════════════
# §8  Timing
# ═══════════════════════════════════════════════════════════════


class TestTiming:
    def test_timing_populated_on_success(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_pass(),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("EURUSD")
        assert "L1" in result.timing_ms
        assert "L2" in result.timing_ms
        assert "L3" in result.timing_ms
        assert all(t >= 0 for t in result.timing_ms.values())

    def test_timing_complete_even_on_failure(self):
        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: _l1_pass(),
            l2_callable=lambda sym: _l2_fail(),
            l3_callable=lambda sym: _l3_pass(),
        )
        result = adapter.execute("EURUSD")
        assert "L1" in result.timing_ms
        assert "L2" in result.timing_ms
        assert "L3" in result.timing_ms  # All layers always run
