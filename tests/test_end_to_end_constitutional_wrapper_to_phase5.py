from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.end_to_end_constitutional_wrapper_to_phase5 import (
    EndToEndConstitutionalWrapperToPhase5,
    EndToEndPhase5Result,
)


class TestEndToEndConstitutionalWrapperToPhase5(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = EndToEndConstitutionalWrapperToPhase5()
        self.base = {
            "L1": {
                "input_ref": "EURUSD_H1_run_1000",
                "timestamp": "2026-04-02T10:00:00+07:00",
                "context_coherence": 0.91,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L2": {
                "input_ref": "EURUSD_H1_run_1000",
                "timestamp": "2026-04-02T10:00:00+07:00",
                "alignment_score": 0.88,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L3": {
                "input_ref": "EURUSD_H1_run_1000",
                "timestamp": "2026-04-02T10:00:00+07:00",
                "confirmation_score": 0.87,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
        }

    def test_result_type(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertIsInstance(result, EndToEndPhase5Result)

    def test_wrapper_name(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertEqual(result.wrapper, "END_TO_END_TO_PHASE5")
        self.assertEqual(result.wrapper_version, "1.0.0")

    def test_result_to_dict(self) -> None:
        result = self.wrapper.run(self.base)
        d = result.to_dict()
        self.assertIn("final_verdict", d)
        self.assertIn("final_verdict_status", d)
        self.assertIn("phase5_result", d)
        self.assertIn("upstream_result", d)
        self.assertIn("audit", d)

    def test_pass_through_to_verdict(self) -> None:
        result = self.wrapper.run(self.base)
        # With synthetic intermediate layers, we get WARN/HOLD at best
        self.assertIn(result.final_verdict, {"EXECUTE", "EXECUTE_REDUCED_RISK", "HOLD", "NO_TRADE"})
        self.assertIn(result.final_verdict_status, {"PASS", "WARN", "FAIL"})

    def test_phase5_result_embedded(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertIn("l12_result", result.phase5_result)
        self.assertIn("synthesis_payload", result.phase5_result)

    def test_halt_at_upstream(self) -> None:
        payload = {**self.base}
        payload["L1"] = {**self.base["L1"], "freshness_state": "NO_PRODUCER"}
        result = self.wrapper.run(payload)
        # L12 still runs as constitutional sink
        self.assertIn(result.final_verdict, {"NO_TRADE"})
        self.assertEqual(result.final_verdict_status, "FAIL")

    def test_audit_trail(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertIn("steps", result.audit)
        self.assertGreater(len(result.audit["steps"]), 2)
        self.assertTrue(result.audit["halt_safe"])

    def test_continuation_metadata(self) -> None:
        result = self.wrapper.run(self.base)
        if result.final_verdict == "NO_TRADE":
            self.assertTrue(result.halted)
            self.assertEqual(result.halted_at, "L12")
        else:
            self.assertFalse(result.halted)
            self.assertIsNone(result.halted_at)

    def test_input_ref_propagation(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertEqual(result.input_ref, "EURUSD_H1_run_1000")

    def test_missing_input_ref_raises(self) -> None:
        payload = {"L1": {}, "L2": {}, "L3": {}}
        with self.assertRaises(ValueError):
            self.wrapper.run(payload)


if __name__ == "__main__":
    unittest.main()
