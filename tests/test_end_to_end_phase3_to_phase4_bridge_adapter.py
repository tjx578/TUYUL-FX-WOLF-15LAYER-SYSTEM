from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constitution.end_to_end_phase3_to_phase4_bridge_adapter import EndToEndPhase3ToPhase4BridgeAdapter


class TestEndToEndPhase3ToPhase4BridgeAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = EndToEndPhase3ToPhase4BridgeAdapter()
        self.base_pass = {
            "wrapper": "END_TO_END_TO_PHASE3",
            "wrapper_version": "1.0.0",
            "input_ref": "EURUSD_H1_run_940",
            "timestamp": "2026-03-28T19:00:00+07:00",
            "halted": False,
            "halted_at": None,
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_4"],
            "wrapper_status": "PASS",
            "upstream_result": {
                "upstream_result": {
                    "phase_results": {
                        "PHASE_1": {
                            "layer_results": {
                                "L1": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                                "L2": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                                "L3": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                            }
                        },
                        "PHASE_2": {
                            "layer_results": {
                                "L4": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                                "L5": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                            }
                        },
                    },
                    "bridge_result": {
                        "l4_payload": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                        "l5_payload": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                    },
                },
                "phase25_result": {
                    "phase_status": "PASS",
                    "advisory_result": {"status": "success"},
                    "warning_list": [],
                    "error_list": [],
                },
            },
            "bridge_result": {
                "l7_payload": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                "l8_payload": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                "l9_payload": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
            },
            "phase3_result": {
                "chain_status": "PASS",
                "warning_map": {"L7": [], "L8": [], "L9": []},
                "layer_results": {
                    "L7": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                    "L8": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                    "L9": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                },
            },
        }

        self.base_warn = {
            **self.base_pass,
            "wrapper_status": "WARN",
            "upstream_result": {
                "upstream_result": {
                    "phase_results": {
                        "PHASE_1": {
                            "layer_results": {
                                "L1": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                                "L2": {"freshness_state": "STALE_PRESERVED", "warmup_state": "PARTIAL", "fallback_class": "LEGAL_EMERGENCY_PRESERVE"},
                                "L3": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                            }
                        },
                        "PHASE_2": {"layer_results": {}},
                    },
                    "bridge_result": {},
                },
                "phase25_result": {
                    "phase_status": "WARN",
                    "advisory_result": {"status": "partial"},
                    "warning_list": ["ADVISORY_BUILT_FROM_DEGRADED_ENRICHMENT_SET"],
                    "error_list": [],
                },
            },
            "bridge_result": {
                "l7_payload": {"freshness_state": "STALE_PRESERVED", "warmup_state": "PARTIAL", "fallback_class": "LEGAL_EMERGENCY_PRESERVE"},
                "l8_payload": {"freshness_state": "STALE_PRESERVED", "warmup_state": "PARTIAL", "fallback_class": "LEGAL_EMERGENCY_PRESERVE"},
                "l9_payload": {"freshness_state": "STALE_PRESERVED", "warmup_state": "PARTIAL", "fallback_class": "LEGAL_EMERGENCY_PRESERVE"},
            },
            "phase3_result": {
                "chain_status": "WARN",
                "warning_map": {
                    "L7": ["EDGE_STATUS_DEGRADED", "VALIDATION_PARTIAL"],
                    "L8": ["INTEGRITY_STATE_DEGRADED", "TII_PARTIAL"],
                    "L9": ["ENTRY_TIMING_DEGRADED", "LIQUIDITY_PARTIAL"],
                },
                "layer_results": {},
            },
        }

    def test_bridge_pass_result(self) -> None:
        result = self.adapter.build(self.base_pass)
        self.assertTrue(result.bridge_allowed)
        self.assertEqual(result.bridge_status, "PASS")
        self.assertEqual(result.next_legal_targets, ["L11", "L6", "L10"])
        self.assertEqual(result.l11_payload["rr_score"], 0.84)
        self.assertEqual(result.l6_payload["firewall_score"], 0.89)
        self.assertEqual(result.l10_payload["sizing_score"], 0.89)

    def test_bridge_warn_result(self) -> None:
        result = self.adapter.build(self.base_warn)
        self.assertTrue(result.bridge_allowed)
        self.assertEqual(result.bridge_status, "WARN")
        self.assertEqual(result.l11_payload["fallback_class"], "LEGAL_EMERGENCY_PRESERVE")
        self.assertEqual(result.l11_payload["rr_score"], 0.72)
        self.assertEqual(result.l6_payload["firewall_state"], "DEGRADED")
        self.assertEqual(result.l10_payload["compliance_state"], "DEGRADED")

    def test_bridge_rejects_halted_upstream(self) -> None:
        payload = {**self.base_pass, "halted": True, "continuation_allowed": False, "next_legal_targets": [], "wrapper_status": "FAIL"}
        result = self.adapter.build(payload)
        self.assertFalse(result.bridge_allowed)
        self.assertEqual(result.bridge_status, "FAIL")
        self.assertEqual(result.l11_payload, {})
        self.assertEqual(result.l6_payload, {})
        self.assertEqual(result.l10_payload, {})

    def test_bridge_rejects_if_next_target_not_phase4(self) -> None:
        payload = {**self.base_pass, "next_legal_targets": ["PHASE_5"]}
        result = self.adapter.build(payload)
        self.assertFalse(result.bridge_allowed)
        self.assertIn("UPSTREAM_NEXT_TARGET_NOT_PHASE_4", result.audit["bridge_reasons"])

    def test_bridge_uses_worst_case_context(self) -> None:
        payload = {**self.base_pass}
        payload["upstream_result"] = {
            "upstream_result": {
                "phase_results": {
                    "PHASE_1": {
                        "layer_results": {
                            "L1": {"freshness_state": "DEGRADED", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                            "L2": {"freshness_state": "FRESH", "warmup_state": "PARTIAL", "fallback_class": "LEGAL_PRIMARY_SUBSTITUTE"},
                            "L3": {"freshness_state": "FRESH", "warmup_state": "READY", "fallback_class": "NO_FALLBACK"},
                        }
                    },
                    "PHASE_2": {"layer_results": {}},
                },
                "bridge_result": {},
            },
            "phase25_result": {"phase_status": "PASS", "advisory_result": {"status": "success"}, "warning_list": [], "error_list": []},
        }
        result = self.adapter.build(payload)
        self.assertEqual(result.l11_payload["freshness_state"], "DEGRADED")
        self.assertEqual(result.l11_payload["warmup_state"], "PARTIAL")
        self.assertEqual(result.l11_payload["fallback_class"], "LEGAL_PRIMARY_SUBSTITUTE")


if __name__ == "__main__":
    unittest.main()
