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
    HIGH_SCORES: dict[str, float] = {
        "L1": 0.91, "L2": 0.88, "L3": 0.87,
        "L4": 0.82, "L5": 0.78,
        "L7": 0.75, "L8": 0.92, "L9": 0.80,
        "L11": 0.85, "L6": 0.90,
    }

    MID_SCORES: dict[str, float] = {
        "L1": 0.62, "L2": 0.62, "L3": 0.62,
        "L4": 0.62, "L5": 0.62,
        "L7": 0.62, "L8": 0.62, "L9": 0.62,
        "L11": 0.62, "L6": 0.62,
    }

    LOW_SCORES: dict[str, float] = {
        "L1": 0.30, "L2": 0.30, "L3": 0.30,
        "L4": 0.30, "L5": 0.30,
        "L7": 0.30, "L8": 0.30, "L9": 0.30,
        "L11": 0.30, "L6": 0.30,
    }

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
            layer_scores=dict(self.HIGH_SCORES),
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
        self.assertEqual(result.layer_version, "2.0.0")

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
            layer_scores=dict(self.HIGH_SCORES),
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
            layer_scores=dict(self.MID_SCORES),
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.55,
            integrity_status="WARN",
            probability_status="WARN",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        # With WARN penalties on soft gates, penalized confidence < EXECUTE threshold
        self.assertIn(result.verdict, ("HOLD", "EXECUTE_REDUCED_RISK"))
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
            layer_scores=dict(self.HIGH_SCORES),
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
            layer_scores=dict(self.HIGH_SCORES),
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
            layer_scores=dict(self.HIGH_SCORES),
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
            layer_scores=dict(self.HIGH_SCORES),
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
            layer_scores=dict(self.LOW_SCORES),  # produces nav-weighted ~0.30
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.30,
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
            layer_scores=dict(self.HIGH_SCORES),
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
        # Enrichment FAIL is advisory → small penalty, should still EXECUTE
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

    def test_score_numeric_is_penalized_confidence(self) -> None:
        result = self.evaluator.evaluate(self.base_input)
        # score_numeric is now navigation-weighted penalized confidence
        self.assertGreater(result.score_numeric, 0.65)
        self.assertEqual(result.score_numeric, result.penalized_confidence)

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

    def test_build_input_prefers_l2_evidence_payload(self) -> None:
        upstream = {
            "input_ref": "EURUSD_H1_run_2000",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_5"],
            "phase4_result": {
                "chain_status": "PASS",
                "summary_status": {"L11": "PASS", "L6": "PASS", "L10": "PASS"},
                "layer_results": {"L11": {"score_numeric": 0.85}, "L6": {"score_numeric": 0.90}, "L10": {"score_numeric": 0.80}},
            },
            "upstream_result": {
                "upstream_result": {
                    "upstream_result": {
                        "phase_results": {
                            "PHASE_1": {
                                "chain_status": "WARN",
                                "summary_status": {"L1": "PASS", "L2": "WARN", "L3": "PASS"},
                                "layer_results": {
                                    "L1": {"score_numeric": 0.91},
                                    "L2": {
                                        "score_numeric": 0.88,
                                        "evidence_score": 0.52,
                                        "confidence_penalty": 0.25,
                                        "status": "WARN",
                                        "advisory_continuation": True,
                                        "hard_stop": False,
                                        "hard_blockers": [],
                                        "soft_blockers": ["LOW_ALIGNMENT_BAND", "STRUCTURE_NOT_FULLY_ALIGNED"],
                                        "mta_diagnostics": {"primary_conflict": "D1_H4_DIRECTION_CONFLICT"},
                                    },
                                    "L3": {"score_numeric": 0.87},
                                },
                            },
                            "PHASE_2": {
                                "chain_status": "PASS",
                                "summary_status": {"L4": "PASS", "L5": "PASS"},
                                "layer_results": {"L4": {"score_numeric": 0.82}, "L5": {"score_numeric": 0.78}},
                            },
                        },
                    },
                    "phase25_result": {"phase_status": "PASS"},
                },
                "phase3_result": {
                    "chain_status": "PASS",
                    "summary_status": {"L7": "PASS", "L8": "PASS", "L9": "PASS"},
                    "layer_results": {"L7": {"score_numeric": 0.75}, "L8": {"score_numeric": 0.92}, "L9": {"score_numeric": 0.80}},
                },
            },
        }

        result = build_l12_input_from_upstream(upstream)
        self.assertEqual(result.layer_scores["L2"], 0.52)
        self.assertEqual(result.l2_status, "WARN")
        self.assertEqual(result.l2_confidence_penalty, 0.25)
        self.assertFalse(result.l2_hard_stop)
        self.assertEqual(result.l2_soft_blockers, ["LOW_ALIGNMENT_BAND", "STRUCTURE_NOT_FULLY_ALIGNED"])
        self.assertEqual(result.l2_primary_conflict, "D1_H4_DIRECTION_CONFLICT")

    def test_build_input_extracts_l9_evidence_payload(self) -> None:
        upstream = {
            "input_ref": "EURUSD_H1_run_2001",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_5"],
            "phase4_result": {
                "chain_status": "PASS",
                "summary_status": {"L11": "PASS", "L6": "PASS", "L10": "PASS"},
                "layer_results": {"L11": {"score_numeric": 0.85}, "L6": {"score_numeric": 0.90}, "L10": {"score_numeric": 0.80}},
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
                                "layer_results": {"L4": {"score_numeric": 0.82}, "L5": {"score_numeric": 0.78}},
                            },
                        },
                    },
                    "phase25_result": {"phase_status": "PASS"},
                },
                "phase3_result": {
                    "chain_status": "WARN",
                    "summary_status": {"L7": "PASS", "L8": "PASS", "L9": "WARN"},
                    "layer_results": {
                        "L7": {"score_numeric": 0.75},
                        "L8": {"score_numeric": 0.92},
                        "L9": {
                            "status": "WARN",
                            "score_numeric": 0.85,
                            "evidence_score": 0.67,
                            "confidence_penalty": 0.18,
                            "hard_stop": False,
                            "advisory_continuation": True,
                            "hard_blockers": [],
                            "soft_blockers": ["DIVERGENCE_SOURCE_MISSING"],
                            "structure_diagnostics": {"source_builder_state": "partial"},
                        },
                    },
                },
            },
        }

        result = build_l12_input_from_upstream(upstream)
        self.assertEqual(result.layer_scores["L9"], 0.67)
        self.assertEqual(result.l9_status, "WARN")
        self.assertEqual(result.l9_confidence_penalty, 0.18)
        self.assertFalse(result.l9_hard_stop)
        self.assertEqual(result.l9_soft_blockers, ["DIVERGENCE_SOURCE_MISSING"])
        self.assertEqual(result.l9_source_builder_state, "partial")

    # ── v2.0 soft penalty / adaptive sizing / navigation confidence tests ──


class TestL12V2SoftPenalty(unittest.TestCase):
    """Tests for v2.0 soft penalty + adaptive sizing + navigation-weighted confidence."""

    HIGH_SCORES: dict[str, float] = {
        "L1": 0.91, "L2": 0.88, "L3": 0.87,
        "L4": 0.82, "L5": 0.78,
        "L7": 0.75, "L8": 0.92, "L9": 0.80,
        "L11": 0.85, "L6": 0.90,
    }

    def setUp(self) -> None:
        self.evaluator = L12RouterEvaluator()

    def test_scoring_fail_not_blocker(self) -> None:
        """SCORING_FAIL should produce warning, not blocker."""
        inp = L12Input(
            input_ref="TEST_SOFT_1",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="FAIL",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
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
        # Scoring is SOFT — should NOT be in blocker_codes
        self.assertNotIn("SCORING_FAIL", result.blocker_codes)
        self.assertIn("SCORING_DEGRADED", result.warning_codes)
        # Should still allow execution with reduced risk
        self.assertIn(result.verdict, ("EXECUTE", "EXECUTE_REDUCED_RISK"))
        self.assertTrue(result.continuation_allowed)

    def test_integrity_fail_produces_reduced_risk(self) -> None:
        """INTEGRITY_FAIL should degrade to EXECUTE_REDUCED_RISK, not NO_TRADE."""
        inp = L12Input(
            input_ref="TEST_SOFT_2",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="FAIL",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertNotIn("INTEGRITY_FAIL", result.blocker_codes)
        self.assertIn("INTEGRITY_DEGRADED", result.warning_codes)
        self.assertIn(result.verdict, ("EXECUTE", "EXECUTE_REDUCED_RISK"))

    def test_sizing_multiplier_reduced_on_soft_fail(self) -> None:
        """Sizing multiplier should be < 1.0 when soft gates fail."""
        inp = L12Input(
            input_ref="TEST_SOFT_3",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="FAIL",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
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
        self.assertLess(result.sizing_multiplier, 1.0)
        self.assertGreater(result.sizing_multiplier, 0.0)

    def test_sizing_multiplier_1_when_all_pass(self) -> None:
        """Sizing multiplier should be 1.0 when no penalties apply."""
        inp = L12Input(
            input_ref="TEST_SOFT_4",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
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
        self.assertEqual(result.sizing_multiplier, 1.0)

    def test_raw_confidence_populated(self) -> None:
        """raw_confidence should reflect navigation-weighted score."""
        inp = L12Input(
            input_ref="TEST_SOFT_5",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
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
        self.assertGreater(result.raw_confidence, 0.0)
        self.assertLessEqual(result.raw_confidence, 1.0)

    def test_penalty_breakdown_in_audit(self) -> None:
        """Audit should contain penalty_engine details."""
        inp = L12Input(
            input_ref="TEST_SOFT_6",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="FAIL",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
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
        self.assertIn("penalty_engine", result.audit)
        pe = result.audit["penalty_engine"]
        self.assertIn("raw_confidence", pe)
        self.assertIn("penalized_confidence", pe)
        self.assertIn("sizing_multiplier", pe)
        self.assertIn("penalty_breakdown", pe)

    def test_multiple_soft_fails_stack_penalties(self) -> None:
        """Multiple soft gate FAILs should stack penalties and reduce sizing."""
        inp = L12Input(
            input_ref="TEST_SOFT_7",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="FAIL",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="FAIL",
            probability_status="FAIL",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.soft_fail_count, 3)
        # Sizing should be heavily reduced
        self.assertLess(result.sizing_multiplier, 0.25)
        # Still not a hard veto
        self.assertNotIn("SCORING_FAIL", result.blocker_codes)

    def test_hard_gate_still_vetoes(self) -> None:
        """Hard gate FAIL must still produce NO_TRADE even with high scores."""
        inp = L12Input(
            input_ref="TEST_SOFT_8",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="FAIL",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.95,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn("FOUNDATION_FAIL", result.blocker_codes)

    def test_to_dict_includes_v2_fields(self) -> None:
        """to_dict() should include v2 fields."""
        result = self.evaluator.evaluate(L12Input(
            input_ref="TEST_V2_DICT",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES),
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
        ))
        d = result.to_dict()
        self.assertIn("raw_confidence", d)
        self.assertIn("penalized_confidence", d)
        self.assertIn("sizing_multiplier", d)
        self.assertIn("soft_fail_count", d)
        self.assertIn("penalty_breakdown", d)

    def test_l2_weak_evidence_emits_warning_not_blocker(self) -> None:
        inp = L12Input(
            input_ref="TEST_L2_SOFT",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES) | {"L2": 0.52},
            l2_status="WARN",
            l2_evidence_score=0.52,
            l2_confidence_penalty=0.25,
            l2_hard_stop=False,
            l2_advisory_continuation=True,
            l2_hard_blockers=[],
            l2_soft_blockers=["LOW_ALIGNMENT_BAND", "STRUCTURE_NOT_FULLY_ALIGNED"],
            l2_primary_conflict="D1_H4_DIRECTION_CONFLICT",
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
        self.assertNotIn(L12BlockerCode.L2_HARD_ILLEGALITY.value, result.blocker_codes)
        self.assertIn("L2_WEAK_EVIDENCE", result.warning_codes)
        self.assertIn("D1_H4_DIRECTION_CONFLICT", result.warning_codes)
        self.assertEqual(result.audit["l2_evidence"]["status"], "WARN")
        self.assertFalse(result.audit["l2_evidence"]["hard_stop"])

    def test_l2_hard_illegality_emits_dedicated_blocker(self) -> None:
        inp = L12Input(
            input_ref="TEST_L2_HARD",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="PASS",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES) | {"L2": 0.0},
            l2_status="FAIL",
            l2_evidence_score=0.0,
            l2_confidence_penalty=1.0,
            l2_hard_stop=True,
            l2_advisory_continuation=False,
            l2_hard_blockers=["REQUIRED_TIMEFRAME_MISSING"],
            l2_soft_blockers=[],
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
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.L2_HARD_ILLEGALITY.value, result.blocker_codes)
        self.assertEqual(result.audit["l2_evidence"]["hard_blockers"], ["REQUIRED_TIMEFRAME_MISSING"])

    def test_l9_weak_structure_evidence_emits_warning_not_blocker(self) -> None:
        inp = L12Input(
            input_ref="TEST_L9_SOFT",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="WARN",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES) | {"L9": 0.67},
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
            l9_status="WARN",
            l9_evidence_score=0.67,
            l9_confidence_penalty=0.18,
            l9_hard_stop=False,
            l9_advisory_continuation=True,
            l9_hard_blockers=[],
            l9_soft_blockers=["DIVERGENCE_SOURCE_MISSING"],
            l9_source_builder_state="partial",
        )
        result = self.evaluator.evaluate(inp)
        self.assertNotIn(L12BlockerCode.L9_HARD_STRUCTURE_ILLEGALITY.value, result.blocker_codes)
        self.assertIn("L9_WEAK_STRUCTURE_EVIDENCE", result.warning_codes)
        self.assertIn("L9_SOURCE_BUILDER_PARTIAL", result.warning_codes)
        self.assertEqual(result.audit["l9_evidence"]["status"], "WARN")

    def test_l9_hard_structure_illegality_emits_dedicated_blocker(self) -> None:
        inp = L12Input(
            input_ref="TEST_L9_HARD",
            timestamp="2026-04-02T10:00:00+07:00",
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status="PASS",
            scoring_status="PASS",
            enrichment_status="PASS",
            structure_status="FAIL",
            risk_chain_status="PASS",
            layer_scores=dict(self.HIGH_SCORES) | {"L9": 0.0},
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=0.80,
            integrity_status="PASS",
            probability_status="PASS",
            firewall_status="PASS",
            governance_status="PASS",
            l9_status="FAIL",
            l9_evidence_score=0.0,
            l9_confidence_penalty=1.0,
            l9_hard_stop=True,
            l9_advisory_continuation=False,
            l9_hard_blockers=["REQUIRED_STRUCTURE_SOURCE_MISSING"],
            l9_soft_blockers=[],
            l9_source_builder_state="not_ready",
        )
        result = self.evaluator.evaluate(inp)
        self.assertEqual(result.verdict, "NO_TRADE")
        self.assertIn(L12BlockerCode.L9_HARD_STRUCTURE_ILLEGALITY.value, result.blocker_codes)
        self.assertEqual(result.audit["l9_evidence"]["hard_blockers"], ["REQUIRED_STRUCTURE_SOURCE_MISSING"])


if __name__ == "__main__":
    unittest.main()
