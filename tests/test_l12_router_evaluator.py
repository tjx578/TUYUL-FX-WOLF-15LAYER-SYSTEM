from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.l12_router_evaluator import (
    L12BlockerCode,
    L12EvaluationResult,
    L12GateName,
    L12Input,
    L12RouterEvaluator,
    build_l12_input_from_upstream,
)


class TestL12RouterEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = L12RouterEvaluator()
        self.base_input = L12Input(
            input_ref="EURUSD_H1_run_1000",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.82,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )

    # ── Basic contract tests ──

    def test_result_type(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        self.assertIsInstance(result, L12EvaluationResult)

    def test_result_layer(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        self.assertEqual(result.layer, "L12")
        self.assertEqual(result.layer_version, "1.0.0")

    def test_result_to_dict(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        d = result.to_dict()
        self.assertEqual(d["layer"], "L12")
        self.assertIn("verdict", d)
        self.assertIn("gate_summary", d)
        self.assertIn("blocker_codes", d)
        self.assertIn("warning_codes", d)
        self.assertIn("score_numeric", d)

    # ── EXECUTE tests ──

    def test_all_pass_high_score_execute(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        self.assertEqual(result.verdict, "EXECUTE")
        self.assertEqual(result.verdict_status, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertIn("PHASE_6", result.next_legal_targets)
        self.assertEqual(result.blocker_codes, [])

    def test_execute_with_enrichment_warn(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1010",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="WARN",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.75,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "EXECUTE")
        self.assertIn("ENRICHMENT_OK_WARN", result.warning_codes)

    # ── HOLD tests ──

    def test_medium_score_hold(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1020",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="WARN",
            enrichment_status="WARN",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.55,  # above HOLD_MIN but below EXECUTE_MIN
            integrity_status="WARN",
            probability_status="WARN",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "HOLD")
        self.assertEqual(result.verdict_status, "WARN")
        self.assertTrue(result.continuation_allowed)

    # ── NO_TRADE tests ──

    def test_upstream_not_continuable(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1030",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=False,
            upstream_next_legal_targets=[],
            foundation_status="FAIL",
            scoring_status="FAIL",
            enrichment_status="FAIL",
            structure_status="FAIL",
            risk_chain_status="FAIL",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.10,
            integrity_status="FAIL",
            probability_status="FAIL",
            firewall_status="FAIL",
            governance_status="FAIL",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertEqual(result.verdict_status, "FAIL")
        self.assertFalse(result.continuation_allowed)
        self.assertIn(L12BlockerCode.UPSTREAM_NOT_CONTINUABLE.value, result.blocker_codes)

    def test_foundation_fail_no_trade(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1031",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="FAIL",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.70,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.FOUNDATION_FAIL.value, result.blocker_codes)

    def test_structure_fail_no_trade(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1032",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="FAIL",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.70,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.STRUCTURE_FAIL.value, result.blocker_codes)

    def test_firewall_fail_no_trade(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1033",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.70,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="FAIL",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.FIREWALL_FAIL.value, result.blocker_codes)

    def test_risk_chain_fail_no_trade(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1034",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="FAIL",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.70,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.RISK_CHAIN_FAIL.value, result.blocker_codes)

    def test_synthesis_score_too_low(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1035",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.30,  # below HOLD_MIN
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.SYNTHESIS_SCORE_TOO_LOW.value, result.blocker_codes)

    def test_phase_missing_blockers(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1036",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=False,
            phase2_available=False,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.PHASE1_MISSING.value, result.blocker_codes)
        self.assertIn(L12BlockerCode.PHASE2_MISSING.value, result.blocker_codes)

    def test_contract_payload_malformed(self) -> None:
        inp = L12Input(
            input_ref="",
            timestamp="",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertIn(L12BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value, result.blocker_codes)

    def test_upstream_target_not_phase5(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1037",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_4"],  # wrong target
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertIn(L12BlockerCode.UPSTREAM_TARGET_NOT_PHASE5.value, result.blocker_codes)

    # ── Enrichment non-fatal test ──

    def test_enrichment_fail_non_fatal(self) -> None:
        inp = L12Input(
            input_ref="EURUSD_H1_run_1038",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="FAIL",
            structure_status="PASS",
            risk_chain_status="PASS",
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.75,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        # Enrichment FAIL is non-fatal → should still EXECUTE
        self.assertEqual(result.verdict, "EXECUTE")
        self.assertIn("ENRICHMENT_DEGRADED", result.warning_codes)

    # ── Gate summary tests ──

    def test_gate_summary_has_all_9_gates(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        expected_gates = {g.value for g in L12GateName}
        self.assertEqual(set(result.gate_summary.keys()), expected_gates)

    def test_gate_summary_all_pass(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        for _gate_name, gate_status in result.gate_summary.items():
            self.assertIn(gate_status, {"PASS", "WARN", "FAIL"})

    # ── Score numeric ──

    def test_score_numeric_matches_input(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        self.assertEqual(round(result.score_numeric, 2), 0.82)

    # ── Blocker deduplication ──

    def test_blocker_deduplicated(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        self.assertEqual(len(result.blocker_codes), len(set(result.blocker_codes)))


class TestBuildL12InputFromUpstream(unittest.TestCase):
    def test_empty_upstream_defaults(self) -> None:
        result = build_l12_input_from_upstream({
            "input_ref": "TEST_REF",
            "timestamp": "2026-04-02T10:00:00+07:00",
        })
        self.assertEqual(result.input_ref, "TEST_REF")
        self.assertFalse(result.upstream_continuation_allowed)
        self.assertEqual(result.foundation_status, "FAIL")

    def test_minimal_upstream(self) -> None:
        upstream = {
            "input_ref": "EURUSD_H1_run_1000",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_5"],
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
        result = build_l12_input_from_upstream(upstream)
        self.assertTrue(result.upstream_continuation_allowed)
        self.assertEqual(result.foundation_status, "PASS")
        self.assertEqual(result.scoring_status, "PASS")
        self.assertEqual(result.structure_status, "PASS")
        self.assertEqual(result.risk_chain_status, "PASS")
        self.assertTrue(result.phase1_available)
        self.assertTrue(result.phase4_available)
        self.assertGreater(result.synthesis_score, 0.0)


if __name__ == "__main__":
    unittest.main()
