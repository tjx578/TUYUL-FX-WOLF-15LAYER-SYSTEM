from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.l10_router_evaluator import L10RouterEvaluator, build_l10_input_from_dict


class TestL10RouterEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = L10RouterEvaluator()
        self.base = {
            "input_ref": "EURUSD_H1_run_920",
            "timestamp": "2026-03-28T18:00:00+07:00",
            "upstream_l6_continuation_allowed": True,
            "sizing_sources_used": ["sizing_engine", "risk_geometry"],
            "required_sizing_sources": ["sizing_engine"],
            "available_sizing_sources": ["sizing_engine", "risk_geometry"],
            "sizing_score": 0.89,
            "entry_available": True,
            "stop_loss_available": True,
            "risk_input_available": True,
            "geometry_valid": True,
            "position_sizing_available": True,
            "compliance_state": "VALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        }

    def test_pass_on_clean_envelope(self) -> None:
        result = self.evaluator.evaluate(build_l10_input_from_dict(self.base))
        self.assertEqual(result.status.value, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.routing["next_legal_targets"], ["PHASE_5"])

    def test_warn_on_mid_sizing_and_degraded_compliance(self) -> None:
        payload = {
            **self.base,
            "sizing_score": 0.76,
            "compliance_state": "DEGRADED",
            "geometry_non_ideal": True,
            "sizing_partial": True,
            "account_limit_proximity_elevated": True,
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
        }
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "WARN")
        self.assertTrue(result.continuation_allowed)
        self.assertIn("COMPLIANCE_DEGRADED", result.warning_codes)

    def test_fail_if_upstream_l6_not_continuable(self) -> None:
        payload = {**self.base, "upstream_l6_continuation_allowed": False}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("UPSTREAM_L6_NOT_CONTINUABLE", result.blocker_codes)

    def test_fail_if_required_sizing_source_missing(self) -> None:
        payload = {**self.base, "available_sizing_sources": ["risk_geometry"]}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("REQUIRED_SIZING_SOURCE_MISSING", result.blocker_codes)

    def test_fail_if_entry_stop_risk_input_unavailable(self) -> None:
        payload = {**self.base, "entry_available": False, "stop_loss_available": False, "risk_input_available": False}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("ENTRY_UNAVAILABLE", result.blocker_codes)
        self.assertIn("STOP_LOSS_UNAVAILABLE", result.blocker_codes)
        self.assertIn("RISK_INPUT_UNAVAILABLE", result.blocker_codes)

    def test_fail_if_geometry_invalid(self) -> None:
        payload = {**self.base, "geometry_valid": False}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("GEOMETRY_INVALID", result.blocker_codes)

    def test_fail_if_position_sizing_unavailable(self) -> None:
        payload = {**self.base, "position_sizing_available": False}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("POSITION_SIZING_UNAVAILABLE", result.blocker_codes)

    def test_fail_if_compliance_invalid(self) -> None:
        payload = {**self.base, "compliance_state": "INVALID"}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("COMPLIANCE_INVALID", result.blocker_codes)

    def test_fail_if_low_sizing_score(self) -> None:
        payload = {**self.base, "sizing_score": 0.50}
        result = self.evaluator.evaluate(build_l10_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertFalse(result.continuation_allowed)
        self.assertEqual(result.coherence_band, "LOW")
        self.assertIn("SIZING_SCORE_BELOW_MINIMUM", result.blocker_codes)


if __name__ == "__main__":
    unittest.main()
