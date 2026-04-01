from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.phase4_chain_adapter import Phase4ChainAdapter, build_phase4_payloads_from_dict


class TestPhase4ChainAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = Phase4ChainAdapter()
        self.base = {
            "L11": {
                "input_ref": "EURUSD_H1_run_930",
                "timestamp": "2026-03-28T18:30:00+07:00",
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
            },
            "L6": {
                "input_ref": "EURUSD_H1_run_930",
                "timestamp": "2026-03-28T18:30:00+07:00",
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
            },
            "L10": {
                "input_ref": "EURUSD_H1_run_930",
                "timestamp": "2026-03-28T18:30:00+07:00",
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
            },
        }

    def test_build_phase_payloads_requires_all_layers(self) -> None:
        with self.assertRaises(ValueError):
            build_phase4_payloads_from_dict({"L11": {}, "L6": {}})

    def test_phase4_passes_clean_envelope(self) -> None:
        l11, l6, l10 = build_phase4_payloads_from_dict(self.base)
        result = self.adapter.run(l11, l6, l10)
        self.assertFalse(result.halted)
        self.assertIsNone(result.halted_at)
        self.assertEqual(result.chain_status, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, ["PHASE_5"])
        self.assertEqual(result.summary_status, {"L11": "PASS", "L6": "PASS", "L10": "PASS"})

    def test_phase4_warn_bubbles_without_halting(self) -> None:
        payload = {**self.base}
        payload["L6"] = {
            **self.base["L6"],
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
        l11, l6, l10 = build_phase4_payloads_from_dict(payload)
        result = self.adapter.run(l11, l6, l10)
        self.assertFalse(result.halted)
        self.assertEqual(result.chain_status, "WARN")
        self.assertEqual(result.summary_status["L6"], "WARN")
        self.assertEqual(result.next_legal_targets, ["PHASE_5"])

    def test_phase4_halts_at_l11(self) -> None:
        payload = {**self.base}
        payload["L11"] = {**self.base["L11"], "rr_score": 0.50}
        l11, l6, l10 = build_phase4_payloads_from_dict(payload)
        result = self.adapter.run(l11, l6, l10)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "L11")
        self.assertEqual(result.chain_status, "FAIL")
        self.assertNotIn("L6", result.summary_status)

    def test_phase4_halts_at_l6(self) -> None:
        payload = {**self.base}
        payload["L6"] = {**self.base["L6"], "firewall_score": 0.50}
        l11, l6, l10 = build_phase4_payloads_from_dict(payload)
        result = self.adapter.run(l11, l6, l10)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "L6")
        self.assertEqual(result.summary_status, {"L11": "PASS", "L6": "FAIL"})
        self.assertNotIn("L10", result.layer_results)

    def test_phase4_halts_at_l10(self) -> None:
        payload = {**self.base}
        payload["L10"] = {**self.base["L10"], "sizing_score": 0.50}
        l11, l6, l10 = build_phase4_payloads_from_dict(payload)
        result = self.adapter.run(l11, l6, l10)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "L10")
        self.assertEqual(result.summary_status, {"L11": "PASS", "L6": "PASS", "L10": "FAIL"})

    def test_upstream_flags_are_injected_by_wrapper(self) -> None:
        payload = {**self.base}
        payload["L6"] = {k: v for k, v in self.base["L6"].items() if k != "upstream_l11_continuation_allowed"}
        payload["L10"] = {k: v for k, v in self.base["L10"].items() if k != "upstream_l6_continuation_allowed"}
        l11, l6, l10 = build_phase4_payloads_from_dict(payload)
        result = self.adapter.run(l11, l6, l10)
        self.assertEqual(result.summary_status, {"L11": "PASS", "L6": "PASS", "L10": "PASS"})


if __name__ == "__main__":
    unittest.main()
