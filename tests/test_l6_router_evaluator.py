from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.l6_router_evaluator import L6RouterEvaluator, build_l6_input_from_dict


class TestL6RouterEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = L6RouterEvaluator()
        self.base = {
            "input_ref": "EURUSD_H1_run_910",
            "timestamp": "2026-03-28T17:30:00+07:00",
            "upstream_l11_continuation_allowed": True,
            "risk_sources_used": ["account_state", "correlation_engine"],
            "required_risk_sources": ["account_state"],
            "available_risk_sources": ["account_state", "correlation_engine"],
            "firewall_score": 0.89,
            "account_state_available": True,
            "drawdown_pct": 0.02,
            "daily_loss_pct": 0.01,
            "correlation_exposure": 0.30,
            "vol_cluster": "NORMAL",
            "firewall_state": "VALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        }

    def test_pass_on_clean_envelope(self) -> None:
        result = self.evaluator.evaluate(build_l6_input_from_dict(self.base))
        self.assertEqual(result.status.value, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.routing["next_legal_targets"], ["L10"])

    def test_warn_on_mid_firewall_and_elevated_risk(self) -> None:
        payload = {
            **self.base,
            "firewall_score": 0.75,
            "drawdown_pct": 0.06,
            "daily_loss_pct": 0.03,
            "correlation_exposure": 0.60,
            "vol_cluster": "HIGH",
            "firewall_state": "DEGRADED",
            "drawdown_elevated": True,
            "daily_loss_elevated": True,
            "correlation_elevated": True,
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
        }
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "WARN")
        self.assertTrue(result.continuation_allowed)
        self.assertIn("VOL_CLUSTER_HIGH", result.warning_codes)

    def test_fail_if_upstream_l11_not_continuable(self) -> None:
        payload = {**self.base, "upstream_l11_continuation_allowed": False}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("UPSTREAM_L11_NOT_CONTINUABLE", result.blocker_codes)

    def test_fail_if_required_risk_source_missing(self) -> None:
        payload = {**self.base, "available_risk_sources": ["correlation_engine"]}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("REQUIRED_RISK_SOURCE_MISSING", result.blocker_codes)

    def test_fail_if_account_state_unavailable(self) -> None:
        payload = {**self.base, "account_state_available": False}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("ACCOUNT_STATE_UNAVAILABLE", result.blocker_codes)

    def test_fail_if_drawdown_limit_breached(self) -> None:
        payload = {**self.base, "drawdown_pct": 0.12}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("DRAWDOWN_LIMIT_BREACHED", result.blocker_codes)

    def test_fail_if_daily_loss_limit_breached(self) -> None:
        payload = {**self.base, "daily_loss_pct": 0.06}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("DAILY_LOSS_LIMIT_BREACHED", result.blocker_codes)

    def test_fail_if_correlation_exposure_exceeded(self) -> None:
        payload = {**self.base, "correlation_exposure": 0.90}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("CORRELATION_EXPOSURE_EXCEEDED", result.blocker_codes)

    def test_fail_if_vol_cluster_extreme(self) -> None:
        payload = {**self.base, "vol_cluster": "EXTREME"}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("VOL_CLUSTER_EXTREME", result.blocker_codes)

    def test_fail_if_firewall_state_invalid(self) -> None:
        payload = {**self.base, "firewall_state": "INVALID"}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertIn("FIREWALL_STATE_INVALID", result.blocker_codes)

    def test_fail_if_low_firewall_score(self) -> None:
        payload = {**self.base, "firewall_score": 0.50}
        result = self.evaluator.evaluate(build_l6_input_from_dict(payload))
        self.assertEqual(result.status.value, "FAIL")
        self.assertFalse(result.continuation_allowed)
        self.assertEqual(result.coherence_band, "LOW")
        self.assertIn("FIREWALL_SCORE_BELOW_MINIMUM", result.blocker_codes)


if __name__ == "__main__":
    unittest.main()
