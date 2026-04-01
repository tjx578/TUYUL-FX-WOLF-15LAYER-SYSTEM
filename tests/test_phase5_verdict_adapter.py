from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.l12_router_evaluator import L12RouterEvaluator
from constitution.phase5_constitutional_verdict_adapter import (
    Phase5ConstitutionalVerdictAdapter,
    Phase5Result,
)


class TestPhase5ConstitutionalVerdictAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = Phase5ConstitutionalVerdictAdapter()
        self.pass_upstream = {
            "input_ref": "EURUSD_H1_run_1000",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_5"],
            "wrapper_status": "PASS",
            "halted": False,
            "phase4_result": {
                "chain_status": "PASS",
                "summary_status": {"L11": "PASS", "L6": "PASS", "L10": "PASS"},
                "layer_results": {
                    "L11": {"score_numeric": 0.85},
                    "L6": {"score_numeric": 0.90},
                    "L10": {"score_numeric": 0.80},
                },
            },
            "upstream_result": {
                "upstream_result": {
                    "upstream_result": {
                        "phase_results": {
                            "PHASE_1": {
                                "chain_status": "PASS",
                                "summary_status": {"L1": "PASS", "L2": "PASS", "L3": "PASS"},
                                "layer_results": {
                                    "L1": {"score_numeric": 0.91},
                                    "L2": {"score_numeric": 0.88},
                                    "L3": {"score_numeric": 0.87},
                                },
                            },
                            "PHASE_2": {
                                "chain_status": "PASS",
                                "summary_status": {"L4": "PASS", "L5": "PASS"},
                                "layer_results": {
                                    "L4": {"score_numeric": 0.82},
                                    "L5": {"score_numeric": 0.78},
                                },
                            },
                        },
                    },
                    "phase25_result": {"phase_status": "PASS"},
                },
                "phase3_result": {
                    "chain_status": "PASS",
                    "summary_status": {"L7": "PASS", "L8": "PASS", "L9": "PASS"},
                    "layer_results": {
                        "L7": {"score_numeric": 0.75},
                        "L8": {"score_numeric": 0.92},
                        "L9": {"score_numeric": 0.80},
                    },
                },
            },
        }

    def test_result_type(self) -> None:
        result = self.adapter.run(self.pass_upstream)
        self.assertIsInstance(result, Phase5Result)

    def test_phase_name(self) -> None:
        result = self.adapter.run(self.pass_upstream)
        self.assertEqual(result.phase, "PHASE_5_VERDICT")
        self.assertEqual(result.phase_version, "1.0.0")

    def test_result_to_dict(self) -> None:
        result = self.adapter.run(self.pass_upstream)
        d = result.to_dict()
        self.assertIn("l12_result", d)
        self.assertIn("synthesis_payload", d)
        self.assertIn("phase_status", d)

    def test_execute_verdict(self) -> None:
        result = self.adapter.run(self.pass_upstream)
        self.assertEqual(result.l12_result["verdict"], "EXECUTE")
        self.assertTrue(result.continuation_allowed)
        self.assertIn("PHASE_6", result.next_legal_targets)

    def test_synthesis_payload_assembled(self) -> None:
        result = self.adapter.run(self.pass_upstream)
        sp = result.synthesis_payload
        self.assertEqual(sp["foundation_status"], "PASS")
        self.assertEqual(sp["scoring_status"], "PASS")
        self.assertEqual(sp["structure_status"], "PASS")
        self.assertEqual(sp["risk_chain_status"], "PASS")

    def test_halted_upstream_no_trade(self) -> None:
        upstream = {
            "input_ref": "EURUSD_H1_run_1001",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "continuation_allowed": False,
            "next_legal_targets": [],
            "wrapper_status": "FAIL",
            "halted": True,
            "phase4_result": {},
            "upstream_result": {
                "upstream_result": {
                    "upstream_result": {"phase_results": {}},
                    "phase25_result": {},
                },
                "phase3_result": {},
            },
        }
        result = self.adapter.run(upstream)
        self.assertEqual(result.l12_result["verdict"], "NO_TRADE")
        self.assertFalse(result.continuation_allowed)

    def test_missing_meta_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter.run({"input_ref": "", "timestamp": ""})

    def test_audit_trail(self) -> None:
        result = self.adapter.run(self.pass_upstream)
        self.assertIn("steps", result.audit)
        self.assertGreater(len(result.audit["steps"]), 0)


class TestPhase5WithCustomEvaluator(unittest.TestCase):
    def test_injectable_evaluator(self) -> None:
        evaluator = L12RouterEvaluator()
        adapter = Phase5ConstitutionalVerdictAdapter(l12_evaluator=evaluator)
        upstream = {
            "input_ref": "EURUSD_H1_run_1002",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_5"],
            "phase4_result": {"chain_status": "WARN", "summary_status": {}, "layer_results": {}},
            "upstream_result": {
                "upstream_result": {
                    "upstream_result": {"phase_results": {}},
                    "phase25_result": {},
                },
                "phase3_result": {},
            },
        }
        result = adapter.run(upstream)
        # With empty phase results, should be NO_TRADE
        self.assertEqual(result.l12_result["verdict"], "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
