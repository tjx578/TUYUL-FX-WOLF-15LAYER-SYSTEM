from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.final_normalized_payload_exporter import (
    FinalNormalizedPayload,
    FinalNormalizedPayloadExporter,
    export_final_normalized_payload_json,
)


class TestFinalNormalizedPayloadExporter(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = FinalNormalizedPayloadExporter()
        self.phase5_result = {
            "wrapper": "END_TO_END_TO_PHASE5",
            "wrapper_version": "1.0.0",
            "input_ref": "EURUSD_H1_run_1000",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "halted": False,
            "halted_at": None,
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_6"],
            "wrapper_status": "PASS",
            "final_verdict": "EXECUTE",
            "final_verdict_status": "PASS",
            "phase5_result": {
                "phase": "PHASE_5_VERDICT",
                "phase_status": "PASS",
                "l12_result": {
                    "verdict": "EXECUTE",
                    "verdict_status": "PASS",
                    "score_numeric": 0.84,
                    "gate_summary": {
                        "FOUNDATION_OK": "PASS",
                        "SCORING_OK": "PASS",
                        "ENRICHMENT_OK": "PASS",
                        "STRUCTURE_OK": "PASS",
                        "RISK_CHAIN_OK": "PASS",
                        "INTEGRITY_OK": "PASS",
                        "PROBABILITY_OK": "PASS",
                        "FIREWALL_OK": "PASS",
                        "GOVERNANCE_OK": "PASS",
                    },
                    "blocker_codes": [],
                    "warning_codes": [],
                },
                "synthesis_payload": {
                    "foundation_status": "PASS",
                    "scoring_status": "PASS",
                    "enrichment_status": "PASS",
                    "structure_status": "PASS",
                    "risk_chain_status": "PASS",
                },
            },
            "upstream_result": {
                "phase4_result": {
                    "chain_status": "PASS",
                    "summary_status": {"L11": "PASS", "L6": "PASS", "L10": "PASS"},
                    "blocker_map": {"L11": [], "L6": [], "L10": []},
                    "warning_map": {"L11": [], "L6": [], "L10": []},
                    "layer_results": {
                        "L11": {"score_numeric": 0.85},
                        "L6": {"score_numeric": 0.90},
                        "L10": {"score_numeric": 0.80},
                    },
                },
                "upstream_result": {
                    "phase3_result": {
                        "chain_status": "PASS",
                        "summary_status": {"L7": "PASS", "L8": "PASS", "L9": "PASS"},
                        "blocker_map": {"L7": [], "L8": [], "L9": []},
                        "warning_map": {"L7": [], "L8": [], "L9": []},
                        "layer_results": {
                            "L7": {"score_numeric": 0.75},
                            "L8": {"score_numeric": 0.92},
                            "L9": {"score_numeric": 0.80},
                        },
                    },
                    "upstream_result": {
                        "upstream_result": {
                            "phase_results": {
                                "PHASE_1": {
                                    "chain_status": "PASS",
                                    "summary_status": {"L1": "PASS", "L2": "PASS", "L3": "PASS"},
                                    "blocker_map": {"L1": [], "L2": [], "L3": []},
                                    "warning_map": {"L1": [], "L2": [], "L3": []},
                                    "layer_results": {
                                        "L1": {"score_numeric": 0.91},
                                        "L2": {"score_numeric": 0.88},
                                        "L3": {"score_numeric": 0.87},
                                    },
                                },
                                "PHASE_2": {
                                    "chain_status": "PASS",
                                    "summary_status": {"L4": "PASS", "L5": "PASS"},
                                    "blocker_map": {"L4": [], "L5": []},
                                    "warning_map": {"L4": [], "L5": []},
                                    "layer_results": {
                                        "L4": {"score_numeric": 0.82},
                                        "L5": {"score_numeric": 0.78},
                                    },
                                },
                            },
                        },
                        "phase25_result": {"phase_status": "PASS"},
                    },
                },
            },
            "audit": {"halt_safe": True, "steps": [], "reason": "done"},
        }

    # ── Schema tests ──

    def test_schema_name(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.schema, "FINAL_NORMALIZED_PAYLOAD_V1")

    def test_schema_version(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.schema_version, "1.0.0")

    def test_result_type(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertIsInstance(payload, FinalNormalizedPayload)

    def test_to_dict(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        d = payload.to_dict()
        self.assertIn("schema", d)
        self.assertIn("pipeline", d)
        self.assertIn("phase_status", d)
        self.assertIn("verdict", d)
        self.assertIn("layer_status", d)
        self.assertIn("scores", d)
        self.assertIn("blockers", d)
        self.assertIn("warnings", d)
        self.assertIn("trace", d)
        self.assertIn("audit", d)

    def test_to_json(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        j = payload.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["schema"], "FINAL_NORMALIZED_PAYLOAD_V1")

    # ── Pipeline section ──

    def test_pipeline_verdict(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.pipeline["final_verdict"], "EXECUTE")
        self.assertEqual(payload.pipeline["final_verdict_status"], "PASS")
        self.assertTrue(payload.pipeline["continuation_allowed"])

    # ── Phase status ──

    def test_phase_status_all_phases(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        expected_phases = {"PHASE_1", "PHASE_2", "PHASE_2_5", "PHASE_3", "PHASE_4", "PHASE_5"}
        self.assertEqual(set(payload.phase_status.keys()), expected_phases)

    def test_phase_status_values(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        for status in payload.phase_status.values():
            self.assertIn(status, {"PASS", "WARN", "FAIL"})

    # ── Verdict section ──

    def test_verdict_fields(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.verdict["verdict"], "EXECUTE")
        self.assertEqual(payload.verdict["verdict_status"], "PASS")
        self.assertAlmostEqual(payload.verdict["synthesis_score"], 0.84, places=2)
        self.assertIn("gate_summary", payload.verdict)

    # ── Layer status ──

    def test_layer_status_has_l12(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertIn("L12", payload.layer_status)

    def test_layer_status_from_phases(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        for layer in ("L1", "L2", "L3", "L4", "L5", "L7", "L8", "L9", "L11", "L6", "L10"):
            self.assertIn(layer, payload.layer_status)

    # ── Scores ──

    def test_scores_numeric(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        for layer in ("L1", "L2", "L3", "L4", "L5", "L7", "L8", "L9", "L11", "L6", "L10"):
            self.assertIsNotNone(payload.scores[layer])
            self.assertIsInstance(payload.scores[layer], float)

    def test_l12_score(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        score = payload.scores["L12"]
        self.assertIsNotNone(score)
        assert score is not None  # narrow type for Pyright
        self.assertEqual(round(score, 2), 0.84)

    # ── Blockers / Warnings ──

    def test_no_blockers_on_pass(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.blockers, [])

    def test_no_warnings_on_pass(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.warnings, [])

    def test_blockers_aggregated(self) -> None:
        result = dict(self.phase5_result)
        result["phase5_result"] = dict(result["phase5_result"])
        result["phase5_result"]["l12_result"] = dict(result["phase5_result"]["l12_result"])
        result["phase5_result"]["l12_result"]["blocker_codes"] = ["TEST_BLOCKER"]
        result["phase5_result"]["l12_result"]["verdict"] = "NO_TRADE"
        result["final_verdict"] = "NO_TRADE"
        payload = self.exporter.export(result)
        self.assertIn("TEST_BLOCKER", payload.blockers)

    # ── Trace / Audit ──

    def test_trace_has_upstream(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertIn("upstream_result", payload.trace)
        self.assertIn("phase5_result", payload.trace)

    def test_audit_metadata(self) -> None:
        payload = self.exporter.export(self.phase5_result)
        self.assertEqual(payload.audit["exporter_version"], "1.0.0")
        self.assertEqual(payload.audit["source_wrapper"], "END_TO_END_TO_PHASE5")

    # ── Missing meta raises ──

    def test_missing_meta_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.exporter.export({"input_ref": "", "timestamp": ""})


class TestExportFunction(unittest.TestCase):
    def test_export_json_function(self) -> None:
        result = {
            "wrapper": "END_TO_END_TO_PHASE5",
            "wrapper_version": "1.0.0",
            "input_ref": "EURUSD_run_1",
            "timestamp": "2026-04-02T10:00:00+07:00",
            "wrapper_status": "FAIL",
            "final_verdict": "NO_TRADE",
            "final_verdict_status": "FAIL",
            "continuation_allowed": False,
            "next_legal_targets": [],
            "phase5_result": {
                "phase_status": "FAIL",
                "l12_result": {
                    "verdict": "NO_TRADE",
                    "verdict_status": "FAIL",
                    "score_numeric": 0.2,
                    "gate_summary": {},
                    "blocker_codes": ["FOUNDATION_FAIL"],
                    "warning_codes": [],
                },
                "synthesis_payload": {
                    "foundation_status": "FAIL",
                    "scoring_status": "FAIL",
                    "enrichment_status": "WARN",
                    "structure_status": "FAIL",
                    "risk_chain_status": "FAIL",
                },
            },
            "upstream_result": {
                "phase4_result": {},
                "upstream_result": {
                    "phase3_result": {},
                    "upstream_result": {
                        "upstream_result": {"phase_results": {}},
                        "phase25_result": {},
                    },
                },
            },
        }
        j = export_final_normalized_payload_json(result)
        parsed = json.loads(j)
        self.assertEqual(parsed["pipeline"]["final_verdict"], "NO_TRADE")
        self.assertEqual(parsed["schema"], "FINAL_NORMALIZED_PAYLOAD_V1")
        self.assertIn("FOUNDATION_FAIL", parsed["blockers"])


if __name__ == "__main__":
    unittest.main()
