"""Tests for Reflex Gate Controller (analysis/reflex_gate.py)."""

from __future__ import annotations

import pytest

from analysis.reflex_gate import GateDecision, ReflexGateController

# ── GateDecision dataclass ────────────────────────────────────────────────────


class TestGateDecision:
    def test_to_dict(self) -> None:
        gd = GateDecision(gate="OPEN", lot_scale=1.0, rqi=0.92, reason="test")
        d = gd.to_dict()
        assert d["gate"] == "OPEN"
        assert d["lot_scale"] == 1.0
        assert d["rqi"] == 0.92
        assert d["reason"] == "test"

    def test_frozen(self) -> None:
        gd = GateDecision(gate="LOCK", lot_scale=0.0, rqi=0.3, reason="blocked")
        with pytest.raises(AttributeError):
            gd.gate = "OPEN"  # type: ignore[misc]


# ── Gate threshold bands ──────────────────────────────────────────────────────


class TestReflexGateController:
    def test_open_at_high_rqi(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(0.92)
        assert decision.gate == "OPEN"
        assert decision.lot_scale == 1.0

    def test_open_at_exact_threshold(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(0.85)
        assert decision.gate == "OPEN"

    def test_caution_below_open(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(0.72)
        assert decision.gate == "CAUTION"
        assert decision.lot_scale == 0.5

    def test_caution_at_exact_threshold(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(0.70)
        assert decision.gate == "CAUTION"

    def test_lock_below_caution(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(0.40)
        assert decision.gate == "LOCK"
        assert decision.lot_scale == 0.0

    def test_lock_at_zero(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(0.0)
        assert decision.gate == "LOCK"
        assert decision.lot_scale == 0.0

    def test_open_at_one(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(1.0)
        assert decision.gate == "OPEN"

    def test_clamps_above_one(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(1.5)
        assert decision.gate == "OPEN"
        assert 0.0 <= decision.rqi <= 1.0

    def test_clamps_below_zero(self) -> None:
        gate = ReflexGateController()
        decision = gate.evaluate(-0.5)
        assert decision.gate == "LOCK"
        assert decision.rqi == 0.0


# ── Custom thresholds ─────────────────────────────────────────────────────────


class TestCustomThresholds:
    def test_custom_open_threshold(self) -> None:
        gate = ReflexGateController(open_threshold=0.90, caution_threshold=0.50)
        assert gate.evaluate(0.89).gate == "CAUTION"
        assert gate.evaluate(0.90).gate == "OPEN"

    def test_custom_caution_threshold(self) -> None:
        gate = ReflexGateController(open_threshold=0.90, caution_threshold=0.50)
        assert gate.evaluate(0.49).gate == "LOCK"
        assert gate.evaluate(0.50).gate == "CAUTION"

    def test_custom_lot_scales(self) -> None:
        gate = ReflexGateController(
            caution_lot_scale=0.3,
            lock_lot_scale=0.1,
        )
        assert gate.evaluate(0.75).lot_scale == 0.3
        assert gate.evaluate(0.40).lot_scale == 0.1

    def test_invalid_threshold_order_raises(self) -> None:
        with pytest.raises(ValueError, match="caution_threshold"):
            ReflexGateController(open_threshold=0.50, caution_threshold=0.80)

    def test_equal_thresholds_raises(self) -> None:
        with pytest.raises(ValueError, match="caution_threshold"):
            ReflexGateController(open_threshold=0.70, caution_threshold=0.70)


# ── Thresholds property ──────────────────────────────────────────────────────


class TestThresholdsProperty:
    def test_returns_config(self) -> None:
        gate = ReflexGateController(
            open_threshold=0.90,
            caution_threshold=0.50,
            open_lot_scale=1.0,
            caution_lot_scale=0.4,
            lock_lot_scale=0.0,
        )
        t = gate.thresholds
        assert t["open_threshold"] == 0.90
        assert t["caution_threshold"] == 0.50
        assert t["caution_lot_scale"] == 0.4
