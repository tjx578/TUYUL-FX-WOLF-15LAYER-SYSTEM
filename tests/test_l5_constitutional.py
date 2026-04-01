"""Tests for L5 Constitutional Governor.

Covers all L5 blocker codes, PASS/WARN/FAIL compression, score band
classification, and upstream L4 legality checks.
"""

from __future__ import annotations

import unittest
from typing import Any

from analysis.layers.L5_constitutional import (
    L5ConstitutionalGovernor,
    _collect_blockers,
    _compute_psychology_score,
    _score_band,
)


def _base_l4(*, continuation_allowed: bool = True) -> dict[str, Any]:
    return {
        "status": "PASS" if continuation_allowed else "FAIL",
        "continuation_allowed": continuation_allowed,
        "valid": continuation_allowed,
    }


def _base_l5(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "psychology_score": 85,
        "eaf_score": 0.85,
        "discipline_score": 0.90,
        "fatigue_level": "LOW",
        "focus_level": 0.80,
        "revenge_trading": False,
        "fomo_level": 0.20,
        "emotional_bias": 0.10,
        "risk_event_active": False,
        "caution_event": False,
        "can_trade": True,
        "gate_status": "OPEN",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "fallback_class": "NO_FALLBACK",
        "valid": True,
    }
    defaults.update(overrides)
    return defaults


class TestL5ConstitutionalGovernor(unittest.TestCase):
    """L5 governor full evaluation tests."""

    def setUp(self) -> None:
        self.gov = L5ConstitutionalGovernor()

    def test_clean_pass(self) -> None:
        result = self.gov.evaluate(_base_l4(), _base_l5(), "EURUSD")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["continuation_allowed"])
        self.assertEqual(result["blocker_codes"], [])
        self.assertIn("PHASE_2_5", result["routing"]["next_legal_targets"])

    def test_warn_on_mid_band(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(psychology_score=70, eaf_score=0.70),
            "EURUSD",
        )
        self.assertEqual(result["status"], "WARN")
        self.assertTrue(result["continuation_allowed"])

    def test_fail_upstream_l4_not_continuable(self) -> None:
        result = self.gov.evaluate(
            _base_l4(continuation_allowed=False),
            _base_l5(),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("UPSTREAM_L4_NOT_CONTINUABLE", result["blocker_codes"])

    def test_fail_missing_input_low_score(self) -> None:
        """LOW band score triggers FAIL without explicit blocker."""
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(psychology_score=30, eaf_score=0.30),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])

    def test_fail_discipline_below_minimum(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(discipline_score=0.40),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("DISCIPLINE_BELOW_MINIMUM", result["blocker_codes"])

    def test_fail_revenge_trading(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(revenge_trading=True),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("REVENGE_TRADING_ACTIVE", result["blocker_codes"])

    def test_fail_risk_event(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(risk_event_active=True),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("RISK_EVENT_HARD_BLOCK", result["blocker_codes"])

    def test_fail_fatigue_critical(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(fatigue_level="CRITICAL"),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("FATIGUE_CRITICAL", result["blocker_codes"])

    def test_fail_focus_critical(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(focus_level=0.20),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("FOCUS_CRITICAL", result["blocker_codes"])

    def test_fail_freshness_no_producer(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(freshness_state="NO_PRODUCER"),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("FRESHNESS_GOVERNANCE_HARD_FAIL", result["blocker_codes"])

    def test_fail_warmup_insufficient(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(warmup_state="INSUFFICIENT"),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("WARMUP_INSUFFICIENT", result["blocker_codes"])

    def test_fail_illegal_fallback(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(fallback_class="ILLEGAL_FALLBACK"),
            "EURUSD",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["continuation_allowed"])
        self.assertIn("FALLBACK_DECLARED_BUT_NOT_ALLOWED", result["blocker_codes"])

    def test_warn_stale_preserved(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(freshness_state="STALE_PRESERVED"),
            "EURUSD",
        )
        # STALE_PRESERVED with high score → WARN (not PASS, because not FRESH)
        self.assertEqual(result["status"], "WARN")
        self.assertTrue(result["continuation_allowed"])
        self.assertIn("STALE_PRESERVED_CONTEXT", result["warning_codes"])

    def test_warn_partial_warmup(self) -> None:
        result = self.gov.evaluate(
            _base_l4(),
            _base_l5(warmup_state="PARTIAL"),
            "EURUSD",
        )
        self.assertEqual(result["status"], "WARN")
        self.assertTrue(result["continuation_allowed"])
        self.assertIn("PARTIAL_WARMUP", result["warning_codes"])

    def test_output_contract_fields(self) -> None:
        result = self.gov.evaluate(_base_l4(), _base_l5(), "XAUUSD")
        self.assertEqual(result["layer"], "L5")
        self.assertIn("layer_version", result)
        self.assertIn("timestamp", result)
        self.assertEqual(result["input_ref"], "XAUUSD_L5")
        self.assertIn("coherence_band", result)
        self.assertIn("score_numeric", result)
        self.assertIn("features", result)
        self.assertIn("routing", result)
        self.assertIn("audit", result)


class TestScoreBand(unittest.TestCase):
    """Score band classification tests."""

    def test_high(self) -> None:
        self.assertEqual(_score_band(0.90).value, "HIGH")

    def test_mid(self) -> None:
        self.assertEqual(_score_band(0.70).value, "MID")

    def test_low(self) -> None:
        self.assertEqual(_score_band(0.50).value, "LOW")


class TestPsychologyScore(unittest.TestCase):
    """Score derivation from different L5 output formats."""

    def test_normalized(self) -> None:
        result = _compute_psychology_score({"psychology_score_normalized": 0.88})
        self.assertAlmostEqual(result, 0.88)

    def test_eaf_fallback(self) -> None:
        result = _compute_psychology_score({"eaf_score": 0.75})
        self.assertAlmostEqual(result, 0.75)

    def test_raw_100_scale(self) -> None:
        result = _compute_psychology_score({"psychology_score": 85})
        self.assertAlmostEqual(result, 0.85)

    def test_default_fallback(self) -> None:
        result = _compute_psychology_score({})
        self.assertAlmostEqual(result, 0.5)


class TestBlockerCollection(unittest.TestCase):
    """Blocker collection edge cases."""

    def test_multiple_blockers(self) -> None:
        blockers = _collect_blockers(
            _base_l4(continuation_allowed=False),
            {
                "discipline_score": 0.30,
                "fatigue_level": "CRITICAL",
                "focus_level": 0.10,
                "revenge_trading": True,
                "risk_event_active": True,
            },
        )
        codes = [b.value for b in blockers]
        self.assertIn("UPSTREAM_L4_NOT_CONTINUABLE", codes)
        self.assertIn("DISCIPLINE_BELOW_MINIMUM", codes)
        self.assertIn("FATIGUE_CRITICAL", codes)
        self.assertIn("FOCUS_CRITICAL", codes)
        self.assertIn("REVENGE_TRADING_ACTIVE", codes)
        self.assertIn("RISK_EVENT_HARD_BLOCK", codes)

    def test_no_blockers_on_clean_input(self) -> None:
        blockers = _collect_blockers(_base_l4(), _base_l5())
        self.assertEqual(blockers, [])


if __name__ == "__main__":
    unittest.main()
