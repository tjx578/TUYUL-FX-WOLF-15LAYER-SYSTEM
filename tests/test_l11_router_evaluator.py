from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.l11_router_evaluator import L11RouterEvaluator, build_l11_input_from_dict


class TestL11RouterEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = L11RouterEvaluator()
        self.base = {
            "input_ref": "EURUSD_H1_run_900",
            "timestamp": "2026-03-28T17:00:00+07:00",
            "upstream_continuation_allowed": True,
            "rr_sources_used": ["rr_engine", "atr_context"],
            "required_rr_sources": ["rr_engine"],
            "available_rr_sources": ["rr_engine", "atr_context"],
            "entry_available": True,
            "stop_loss_available": True,
            "take_profit_available": True,
            "rr_score": 0.84,
            "rr_ratio": 2.1,
            "rr_valid": True,
            "battle_plan_available": True,
            "atr_context_available": True,
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        }

    def test_pass_on_clean_envelope(self) -> None:
        result = self.evaluator.evaluate(build_l11_input_from_dict(self.base))
        self.assertEqual(result.status.value, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.routing["next_legal_targets"], ["L6"])

    def test_warn_on_mid_rr_and_degraded_plan(self) -> None:
        payload = {
            **self.base,
            "rr_score": 0.70,
            "rr_ratio": 1.4,
            "battle_plan_degraded": True,
            "atr_context_partial": True,
            "target_geometry_non_ideal": True,
            "multi_target_incomplete": True,
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
        }
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "WARN")
        self.assertTrue(result.continuation_allowed)
        self.assertIn("BATTLE_PLAN_DEGRADED", result.warning_codes)

    def test_fail_if_upstream_not_continuable(self) -> None:
        payload = {**self.base, "upstream_continuation_allowed": False}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("UPSTREAM_NOT_CONTINUABLE", result.blocker_codes)

    def test_fail_if_required_rr_source_missing(self) -> None:
        payload = {**self.base, "available_rr_sources": ["atr_context"]}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("REQUIRED_RR_SOURCE_MISSING", result.blocker_codes)

    def test_fail_if_entry_stop_tp_unavailable(self) -> None:
        payload = {**self.base, "entry_available": False, "stop_loss_available": False, "take_profit_available": False}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("ENTRY_UNAVAILABLE", result.blocker_codes)
        self.assertIn("STOP_LOSS_UNAVAILABLE", result.blocker_codes)
        self.assertIn("TAKE_PROFIT_UNAVAILABLE", result.blocker_codes)

    def test_fail_if_rr_invalid(self) -> None:
        payload = {**self.base, "rr_valid": False, "rr_ratio": 0.0}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("RR_INVALID", result.blocker_codes)

    def test_fail_if_battle_plan_unavailable(self) -> None:
        payload = {**self.base, "battle_plan_available": False}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("BATTLE_PLAN_UNAVAILABLE", result.blocker_codes)

    def test_fail_if_atr_context_unavailable(self) -> None:
        payload = {**self.base, "atr_context_available": False}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("ATR_CONTEXT_UNAVAILABLE", result.blocker_codes)

    def test_fail_if_low_rr_score(self) -> None:
        payload = {**self.base, "rr_score": 0.50}
        result = self.evaluator.evaluate(build_l11_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertFalse(result.continuation_allowed)
        self.assertEqual(result.coherence_band, "LOW")
        self.assertIn("RR_SCORE_BELOW_MINIMUM", result.blocker_codes)


if __name__ == "__main__":
    unittest.main()
