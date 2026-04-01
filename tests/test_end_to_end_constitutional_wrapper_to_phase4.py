from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.end_to_end_constitutional_wrapper_to_phase4 import EndToEndConstitutionalWrapperToPhase4


class TestEndToEndConstitutionalWrapperToPhase4(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = EndToEndConstitutionalWrapperToPhase4()
        self.base = {
            "L1": {
                "input_ref": "EURUSD_H1_run_950",
                "timestamp": "2026-03-28T19:30:00+07:00",
                "context_coherence": 0.91,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L2": {
                "input_ref": "EURUSD_H1_run_950",
                "timestamp": "2026-03-28T19:30:00+07:00",
                "alignment_score": 0.88,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L3": {
                "input_ref": "EURUSD_H1_run_950",
                "timestamp": "2026-03-28T19:30:00+07:00",
                "confirmation_score": 0.87,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
        }

    def test_end_to_end_pass_to_phase4(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertFalse(result.halted)
        # With only L1/L2/L3 inputs, synthetic intermediate layers produce WARN
        self.assertEqual(result.wrapper_status, "WARN")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, ["PHASE_5"])
        self.assertEqual(result.phase4_result["phase"], "PHASE_4_RISK_CHAIN")
        self.assertEqual(result.phase4_result["chain_status"], "WARN")

    def test_end_to_end_warn_to_phase4(self) -> None:
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
        self.assertEqual(result.phase4_result["chain_status"], "WARN")
        self.assertEqual(result.next_legal_targets, ["PHASE_5"])

    def test_halt_at_upstream(self) -> None:
        payload = {**self.base}
        payload["L1"] = {**self.base["L1"], "freshness_state": "NO_PRODUCER"}
        result = self.wrapper.run(payload)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "UPSTREAM")
        self.assertEqual(result.wrapper_status, "FAIL")
        self.assertEqual(result.bridge_result, {})
        self.assertEqual(result.phase4_result, {})

    def test_bridge_result_embedded(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertEqual(result.bridge_result["bridge"], "PHASE3_TO_PHASE4")
        self.assertTrue(result.bridge_result["bridge_allowed"])

    def test_phase4_result_embedded(self) -> None:
        result = self.wrapper.run(self.base)
        # With only L1/L2/L3 inputs, synthetic intermediate layers produce WARN
        self.assertEqual(result.phase4_result["summary_status"], {"L11": "WARN", "L6": "WARN", "L10": "WARN"})


if __name__ == "__main__":
    unittest.main()
