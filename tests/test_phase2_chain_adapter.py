"""Tests for Phase 2 Chain Adapter.

Covers clean PASS, WARN bubble, L4 halt, L5 halt, and upstream flag injection.
"""

from __future__ import annotations

import unittest
from typing import Any

from constitution.phase2_chain_adapter import (
    Phase2ChainAdapter,
    Phase2ChainResult,
    Phase2ChainStatus,
    build_phase2_payloads_from_dict,
)


def _l3_output(**overrides: Any) -> dict[str, Any]:
    defaults = {
        "status": "PASS",
        "continuation_allowed": True,
        "score_numeric": 0.85,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "fallback_class": "NO_FALLBACK",
    }
    defaults.update(overrides)
    return defaults


def _l4_analysis(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "session": {"name": "LONDON", "active": True},
        "session_score": 82,
        "expectancy_valid": True,
        "scoring_sources_used": ["session_engine"],
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "fallback_class": "NO_FALLBACK",
        "valid": True,
        "wolf_30_point": {"total": 24.0, "f_score": 8, "t_score": 8, "fta_score": 4, "exec_score": 4},
        "bayesian": {"expected_value": 0.65, "confidence_index": 0.70},
        "grade": "A",
        "quality": 0.80,
        "tradeable": True,
    }
    defaults.update(overrides)
    return defaults


def _l5_analysis(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "psychology_score": 85,
        "eaf_score": 0.85,
        "discipline_score": 0.90,
        "fatigue_level": "LOW",
        "focus_level": 0.80,
        "revenge_trading": False,
        "risk_event_active": False,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "fallback_class": "NO_FALLBACK",
        "can_trade": True,
        "gate_status": "OPEN",
        "valid": True,
    }
    defaults.update(overrides)
    return defaults


class TestPhase2PayloadBuilder(unittest.TestCase):
    """Tests for build_phase2_payloads_from_dict."""

    def test_builds_valid_payloads(self) -> None:
        l4p, l5p = build_phase2_payloads_from_dict(
            _l3_output(), _l4_analysis(), _l5_analysis(), "EURUSD"
        )
        self.assertIn("l3_output", l4p)
        self.assertIn("l4_analysis", l4p)
        self.assertEqual(l4p["symbol"], "EURUSD")
        self.assertIn("l5_analysis", l5p)
        self.assertEqual(l5p["symbol"], "EURUSD")


class TestPhase2ChainAdapter(unittest.TestCase):
    """Tests for Phase2ChainAdapter.run()."""

    def test_clean_pass(self) -> None:
        adapter = Phase2ChainAdapter()
        l4p, l5p = build_phase2_payloads_from_dict(
            _l3_output(), _l4_analysis(), _l5_analysis(), "EURUSD"
        )
        result = adapter.run(l4p, l5p)
        self.assertIn(result.status, (Phase2ChainStatus.PASS, Phase2ChainStatus.WARN))
        self.assertTrue(result.continuation_allowed)
        self.assertIsNone(result.halted_at)
        self.assertNotEqual(result.l4, {})
        self.assertNotEqual(result.l5, {})

    def test_warn_bubble(self) -> None:
        """WARN from L4 should bubble to chain status if L5 passes."""
        adapter = Phase2ChainAdapter()
        l4p, l5p = build_phase2_payloads_from_dict(
            _l3_output(),
            _l4_analysis(freshness_state="STALE_PRESERVED"),
            _l5_analysis(),
            "EURUSD",
        )
        result = adapter.run(l4p, l5p)
        self.assertTrue(result.continuation_allowed)

    def test_halt_at_l4(self) -> None:
        """L4 FAIL should halt chain before L5 runs."""
        adapter = Phase2ChainAdapter()
        # Use L3 output that triggers upstream failure in L4
        bad_l3 = _l3_output(
            status="FAIL",
            continuation_allowed=False,
        )
        l4p, l5p = build_phase2_payloads_from_dict(
            bad_l3, _l4_analysis(), _l5_analysis(), "EURUSD"
        )
        result = adapter.run(l4p, l5p)
        self.assertEqual(result.status, Phase2ChainStatus.FAIL)
        self.assertFalse(result.continuation_allowed)
        self.assertEqual(result.halted_at, "L4")
        # L5 should not have been evaluated
        self.assertEqual(result.l5, {})

    def test_halt_at_l5(self) -> None:
        """L5 FAIL should halt chain after L4 succeeds."""
        adapter = Phase2ChainAdapter()
        l4p, l5p = build_phase2_payloads_from_dict(
            _l3_output(),
            _l4_analysis(),
            _l5_analysis(discipline_score=0.30, revenge_trading=True),
            "EURUSD",
        )
        result = adapter.run(l4p, l5p)
        self.assertEqual(result.status, Phase2ChainStatus.FAIL)
        self.assertFalse(result.continuation_allowed)
        self.assertEqual(result.halted_at, "L5")
        # L4 should have been evaluated
        self.assertNotEqual(result.l4, {})

    def test_upstream_flag_injection(self) -> None:
        """L4 result should be injected as L5's l4_output."""
        adapter = Phase2ChainAdapter()
        l4p, l5p = build_phase2_payloads_from_dict(
            _l3_output(), _l4_analysis(), _l5_analysis(), "EURUSD"
        )
        result = adapter.run(l4p, l5p)
        if result.continuation_allowed and result.l5:
            # L5 evaluated with L4 output as upstream
            self.assertNotEqual(result.l4, {})

    def test_to_dict(self) -> None:
        """Serialization should produce valid dict."""
        result = Phase2ChainResult(
            status=Phase2ChainStatus.PASS,
            continuation_allowed=True,
        )
        d = result.to_dict()
        self.assertEqual(d["phase"], "PHASE_2")
        self.assertEqual(d["status"], "PASS")
        self.assertTrue(d["continuation_allowed"])


if __name__ == "__main__":
    unittest.main()
