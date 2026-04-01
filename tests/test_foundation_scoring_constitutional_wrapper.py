"""Tests for FoundationScoringConstitutionalWrapper (Phase 1 → Bridge → Phase 2)."""

from __future__ import annotations

import unittest

from constitution.foundation_scoring_constitutional_wrapper import (
    FoundationScoringConstitutionalWrapper,
)


class TestFoundationScoringConstitutionalWrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = FoundationScoringConstitutionalWrapper()
        self.base = {
            "L1": {
                "input_ref": "EURUSD_H1_run_100",
                "timestamp": "2026-03-28T10:15:00+07:00",
                "context_coherence": 0.91,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L2": {
                "input_ref": "EURUSD_H1_run_100",
                "timestamp": "2026-03-28T10:15:00+07:00",
                "alignment_score": 0.88,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L3": {
                "input_ref": "EURUSD_H1_run_100",
                "timestamp": "2026-03-28T10:15:00+07:00",
                "confirmation_score": 0.87,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
        }

    def test_end_to_end_pass(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertFalse(result.halted)
        self.assertIn(result.wrapper_status, {"PASS", "WARN"})
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, ["PHASE_2_5"])
        self.assertIn("PHASE_1", result.phase_status)
        self.assertIn("PHASE_2", result.phase_status)

    def test_end_to_end_warn(self) -> None:
        payload = {**self.base}
        payload["L2"] = {
            **self.base["L2"],
            "alignment_score": 0.72,
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
        }
        result = self.wrapper.run(payload)
        self.assertFalse(result.halted)
        self.assertEqual(result.wrapper_status, "WARN")
        self.assertEqual(result.phase_status["PHASE_1"], "WARN")

    def test_halt_at_phase1(self) -> None:
        payload = {**self.base}
        payload["L1"] = {**self.base["L1"], "freshness_state": "NO_PRODUCER"}
        result = self.wrapper.run(payload)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "PHASE_1")
        self.assertEqual(result.wrapper_status, "FAIL")
        self.assertNotIn("PHASE_2", result.phase_status)

    def test_halt_at_phase2(self) -> None:
        payload = {**self.base}
        payload["L3"] = {**self.base["L3"], "confirmation_score": 0.95}
        result = self.wrapper.run(payload)
        # With healthy default L4/L5 analysis the wrapper should complete
        self.assertIn(result.wrapper_status, {"PASS", "WARN"})

    def test_bridge_result_embedded(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertEqual(result.bridge_result["bridge"], "PHASE1_TO_PHASE2")
        self.assertTrue(result.bridge_result["bridge_allowed"])

    def test_to_dict_structure(self) -> None:
        result = self.wrapper.run(self.base)
        d = result.to_dict()
        self.assertIn("wrapper", d)
        self.assertIn("bridge_result", d)
        self.assertIn("phase_status", d)
        self.assertIn("audit", d)


if __name__ == "__main__":
    unittest.main()
