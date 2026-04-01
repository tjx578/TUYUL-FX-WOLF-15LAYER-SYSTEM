from __future__ import annotations

import unittest

from constitution.phase3_chain_adapter import Phase3ChainAdapter, build_phase3_payloads_from_dict


class TestPhase3ChainAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = Phase3ChainAdapter()
        self.base = {
            "L7": {
                "input_ref": "EURUSD_H1_run_600",
                "timestamp": "2026-03-28T15:30:00+07:00",
                "upstream_continuation_allowed": True,
                "probability_sources_used": ["monte_carlo", "edge_validator"],
                "required_probability_sources": ["monte_carlo"],
                "available_probability_sources": ["monte_carlo", "edge_validator"],
                "win_probability": 0.71,
                "profit_factor": 1.8,
                "sample_count": 80,
                "edge_validation_available": True,
                "edge_status": "VALID",
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L8": {
                "input_ref": "EURUSD_H1_run_600",
                "timestamp": "2026-03-28T15:30:00+07:00",
                "integrity_sources_used": ["tii_engine", "twms_engine"],
                "required_integrity_sources": ["tii_engine"],
                "available_integrity_sources": ["tii_engine", "twms_engine"],
                "integrity_score": 0.91,
                "tii_available": True,
                "twms_available": True,
                "integrity_state": "VALID",
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L9": {
                "input_ref": "EURUSD_H1_run_600",
                "timestamp": "2026-03-28T15:30:00+07:00",
                "structure_sources_used": ["smc_engine", "timing_engine"],
                "required_structure_sources": ["smc_engine"],
                "available_structure_sources": ["smc_engine", "timing_engine"],
                "structure_score": 0.84,
                "structure_alignment_valid": True,
                "entry_timing_available": True,
                "liquidity_state": "VALID",
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
        }

    def test_build_phase_payloads_requires_all_layers(self) -> None:
        with self.assertRaises(ValueError):
            build_phase3_payloads_from_dict({"L7": {}, "L8": {}})

    def test_phase3_passes_clean_envelope(self) -> None:
        l7, l8, l9 = build_phase3_payloads_from_dict(self.base)
        result = self.adapter.run(l7, l8, l9)
        self.assertFalse(result.halted)
        self.assertIsNone(result.halted_at)
        self.assertEqual(result.chain_status, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, ["PHASE_4"])
        self.assertEqual(result.summary_status, {"L7": "PASS", "L8": "PASS", "L9": "PASS"})

    def test_phase3_warn_bubbles_without_halting(self) -> None:
        payload = {**self.base}
        payload["L8"] = {
            **self.base["L8"],
            "integrity_score": 0.80,
            "integrity_state": "DEGRADED",
            "tii_partial": True,
            "twms_partial": True,
            "governance_degraded": True,
            "stability_non_ideal": True,
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
        }
        l7, l8, l9 = build_phase3_payloads_from_dict(payload)
        result = self.adapter.run(l7, l8, l9)
        self.assertFalse(result.halted)
        self.assertEqual(result.chain_status, "WARN")
        self.assertEqual(result.summary_status["L8"], "WARN")
        self.assertEqual(result.next_legal_targets, ["PHASE_4"])

    def test_phase3_halts_at_l7(self) -> None:
        payload = {**self.base}
        payload["L7"] = {**self.base["L7"], "win_probability": 0.40}
        l7, l8, l9 = build_phase3_payloads_from_dict(payload)
        result = self.adapter.run(l7, l8, l9)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "L7")
        self.assertEqual(result.chain_status, "FAIL")
        self.assertNotIn("L8", result.summary_status)

    def test_phase3_halts_at_l8(self) -> None:
        payload = {**self.base}
        payload["L8"] = {**self.base["L8"], "integrity_score": 0.60}
        l7, l8, l9 = build_phase3_payloads_from_dict(payload)
        result = self.adapter.run(l7, l8, l9)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "L8")
        self.assertEqual(result.summary_status, {"L7": "PASS", "L8": "FAIL"})
        self.assertNotIn("L9", result.layer_results)

    def test_phase3_halts_at_l9(self) -> None:
        payload = {**self.base}
        payload["L9"] = {**self.base["L9"], "structure_score": 0.50}
        l7, l8, l9 = build_phase3_payloads_from_dict(payload)
        result = self.adapter.run(l7, l8, l9)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "L9")
        self.assertEqual(result.summary_status, {"L7": "PASS", "L8": "PASS", "L9": "FAIL"})

    def test_upstream_flags_are_injected_by_wrapper(self) -> None:
        payload = {**self.base}
        payload["L8"] = {k: v for k, v in self.base["L8"].items() if k != "upstream_l7_continuation_allowed"}
        payload["L9"] = {k: v for k, v in self.base["L9"].items() if k != "upstream_l8_continuation_allowed"}
        l7, l8, l9 = build_phase3_payloads_from_dict(payload)
        result = self.adapter.run(l7, l8, l9)
        self.assertEqual(result.summary_status, {"L7": "PASS", "L8": "PASS", "L9": "PASS"})


if __name__ == "__main__":
    unittest.main()
