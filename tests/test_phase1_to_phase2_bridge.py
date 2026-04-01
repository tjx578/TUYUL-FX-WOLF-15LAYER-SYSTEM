"""Tests for Phase 1 → Phase 2 Bridge Adapter.

Covers score derivation, freshness/warmup/fallback aggregation,
warning pressure computation, and payload construction.
"""

from __future__ import annotations

import unittest
from typing import Any

from constitution.phase1_to_phase2_bridge_adapter import (
    Phase1ToPhase2BridgeAdapter,
    _compute_warning_pressure,
    _derive_fallback,
    _derive_freshness,
    _derive_l4_score,
    _derive_l5_score,
    _derive_warmup,
)


def _layer(
    score: float = 0.85,
    freshness: str = "FRESH",
    warmup: str = "READY",
    fallback: str = "NO_FALLBACK",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "PASS",
        "continuation_allowed": True,
        "score_numeric": score,
        "freshness_state": freshness,
        "warmup_state": warmup,
        "fallback_class": fallback,
        "warning_codes": warnings or [],
    }


def _phase1_result(
    l1: dict[str, Any] | None = None,
    l2: dict[str, Any] | None = None,
    l3: dict[str, Any] | None = None,
    status: str = "PASS",
) -> dict[str, Any]:
    return {
        "phase": "PHASE_1",
        "status": status,
        "continuation_allowed": True,
        "l1": l1 or _layer(),
        "l2": l2 or _layer(),
        "l3": l3 or _layer(),
        "warnings": [],
    }


def _l4_analysis(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "session_score": 82,
        "valid": True,
    }
    defaults.update(overrides)
    return defaults


def _l5_analysis(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "psychology_score": 85,
        "eaf_score": 0.85,
        "valid": True,
    }
    defaults.update(overrides)
    return defaults


class TestScoreDerivation(unittest.TestCase):
    """Tests for upstream score derivation helpers."""

    def test_l4_score_average(self) -> None:
        score = _derive_l4_score(
            _layer(score=0.90), _layer(score=0.80), _layer(score=0.70)
        )
        self.assertAlmostEqual(score, 0.80)

    def test_l4_score_fallback_no_data(self) -> None:
        score = _derive_l4_score({}, {}, {})
        self.assertAlmostEqual(score, 0.50)

    def test_l5_score_capped_on_warn(self) -> None:
        score = _derive_l5_score(
            _layer(score=0.90), _layer(score=0.90), _layer(score=0.90), "WARN"
        )
        self.assertAlmostEqual(score, 0.65)

    def test_l5_score_uncapped_on_pass(self) -> None:
        score = _derive_l5_score(
            _layer(score=0.90), _layer(score=0.90), _layer(score=0.90), "PASS"
        )
        self.assertAlmostEqual(score, 0.90)


class TestStateAggregation(unittest.TestCase):
    """Tests for worst-case state aggregation."""

    def test_freshness_worst_case(self) -> None:
        result = _derive_freshness(
            _layer(freshness="FRESH"),
            _layer(freshness="DEGRADED"),
            _layer(freshness="STALE_PRESERVED"),
        )
        self.assertEqual(result, "DEGRADED")

    def test_freshness_no_producer_wins(self) -> None:
        result = _derive_freshness(
            _layer(freshness="NO_PRODUCER"),
            _layer(freshness="FRESH"),
            _layer(freshness="FRESH"),
        )
        self.assertEqual(result, "NO_PRODUCER")

    def test_warmup_worst_case(self) -> None:
        result = _derive_warmup(
            _layer(warmup="READY"),
            _layer(warmup="PARTIAL"),
            _layer(warmup="READY"),
        )
        self.assertEqual(result, "PARTIAL")

    def test_fallback_worst_case(self) -> None:
        result = _derive_fallback(
            _layer(fallback="NO_FALLBACK"),
            _layer(fallback="LEGAL_EMERGENCY_PRESERVE"),
            _layer(fallback="LEGAL_PRIMARY_SUBSTITUTE"),
        )
        self.assertEqual(result, "LEGAL_EMERGENCY_PRESERVE")

    def test_all_fresh_ready(self) -> None:
        f = _derive_freshness(_layer(), _layer(), _layer())
        w = _derive_warmup(_layer(), _layer(), _layer())
        fb = _derive_fallback(_layer(), _layer(), _layer())
        self.assertEqual(f, "FRESH")
        self.assertEqual(w, "READY")
        self.assertEqual(fb, "NO_FALLBACK")


class TestWarningPressure(unittest.TestCase):
    """Tests for warning pressure computation."""

    def test_zero_warnings(self) -> None:
        wp = _compute_warning_pressure(_layer(), _layer(), _layer())
        self.assertAlmostEqual(wp, 0.0)

    def test_capped_at_one(self) -> None:
        heavy = _layer(warnings=["a", "b", "c", "d"])
        wp = _compute_warning_pressure(heavy, heavy, heavy)
        self.assertAlmostEqual(wp, 1.0)

    def test_partial_pressure(self) -> None:
        wp = _compute_warning_pressure(
            _layer(warnings=["a"]),
            _layer(warnings=["b"]),
            _layer(warnings=["c"]),
        )
        self.assertAlmostEqual(wp, 0.50)


class TestBridgeAdapter(unittest.TestCase):
    """Tests for Phase1ToPhase2BridgeAdapter.build()."""

    def setUp(self) -> None:
        self.bridge = Phase1ToPhase2BridgeAdapter()

    def test_clean_build(self) -> None:
        result = self.bridge.build(
            _phase1_result(), _l4_analysis(), _l5_analysis(), "EURUSD"
        )
        self.assertIn("l3_output", result.l4_payload)
        self.assertIn("l4_analysis", result.l4_payload)
        self.assertEqual(result.l4_payload["symbol"], "EURUSD")
        self.assertIn("l5_analysis", result.l5_payload)
        self.assertEqual(result.l5_payload["symbol"], "EURUSD")
        self.assertEqual(result.freshness_state, "FRESH")
        self.assertEqual(result.warmup_state, "READY")
        self.assertEqual(result.fallback_class, "NO_FALLBACK")

    def test_degraded_freshness_propagated(self) -> None:
        p1 = _phase1_result(
            l2=_layer(freshness="DEGRADED"),
        )
        result = self.bridge.build(p1, _l4_analysis(), _l5_analysis(), "EURUSD")
        self.assertEqual(result.freshness_state, "DEGRADED")
        # L4 payload should carry degraded freshness
        self.assertEqual(
            result.l4_payload["l4_analysis"]["freshness_state"], "DEGRADED"
        )

    def test_warn_chain_caps_l5_score(self) -> None:
        p1 = _phase1_result(status="WARN")
        result = self.bridge.build(p1, _l4_analysis(), _l5_analysis(), "EURUSD")
        l5_upstream = result.l5_payload["l5_analysis"].get("upstream_context_score", 1.0)
        self.assertLessEqual(l5_upstream, 0.65)

    def test_to_dict(self) -> None:
        result = self.bridge.build(
            _phase1_result(), _l4_analysis(), _l5_analysis(), "EURUSD"
        )
        d = result.to_dict()
        self.assertIn("upstream_score", d)
        self.assertIn("freshness_state", d)
        self.assertIn("warning_pressure", d)


if __name__ == "__main__":
    unittest.main()
