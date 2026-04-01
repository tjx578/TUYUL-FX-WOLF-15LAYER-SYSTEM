"""Tests for Phase25EnrichmentWrapper and FoundationScoringEnrichmentConstitutionalWrapper."""

from __future__ import annotations

import unittest

from constitution.foundation_scoring_enrichment_constitutional_wrapper import (
    FoundationScoringEnrichmentConstitutionalWrapper,
)
from constitution.phase25_enrichment_wrapper import (
    EnrichmentEngineResult,
    Phase25EnrichmentWrapper,
)


class TestPhase25EnrichmentWrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.base_upstream = {
            "input_ref": "EURUSD_H1_run_200",
            "timestamp": "2026-03-28T10:15:00+07:00",
            "halted": False,
            "continuation_allowed": True,
            "next_legal_targets": ["PHASE_2_5"],
            "wrapper_status": "PASS",
            "phase_status": {"PHASE_1": "PASS", "PHASE_2": "PASS"},
        }

    def test_phase25_pass_on_clean_upstream(self) -> None:
        wrapper = Phase25EnrichmentWrapper()
        result = wrapper.run(self.base_upstream)
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.phase_status, "PASS")
        self.assertEqual(result.next_legal_targets, ["PHASE_3"])
        self.assertEqual(result.advisory_result["engine_id"], "E9_ADVISORY")

    def test_phase25_warn_on_engine_failure_but_continue(self) -> None:
        def bad_runner(engine_id: str, context: dict) -> EnrichmentEngineResult:
            if engine_id == "E3":
                raise RuntimeError("boom")
            return EnrichmentEngineResult(engine_id, "success", {"ok": True}, [], [])

        wrapper = Phase25EnrichmentWrapper(engine_runners={"E3": bad_runner})
        result = wrapper.run(self.base_upstream)
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.phase_status, "WARN")
        self.assertIn("RuntimeError: boom", " ".join(result.error_list))
        self.assertEqual(result.engine_results["E3"]["status"], "failed")

    def test_phase25_skips_if_upstream_not_eligible(self) -> None:
        payload = {
            **self.base_upstream,
            "halted": True,
            "continuation_allowed": False,
            "next_legal_targets": [],
        }
        wrapper = Phase25EnrichmentWrapper()
        result = wrapper.run(payload)
        self.assertFalse(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, [])
        self.assertEqual(result.engine_results, {})

    def test_to_dict_structure(self) -> None:
        wrapper = Phase25EnrichmentWrapper()
        result = wrapper.run(self.base_upstream)
        d = result.to_dict()
        self.assertEqual(d["phase"], "PHASE_2_5_ENRICHMENT")
        self.assertIn("engine_results", d)
        self.assertIn("advisory_result", d)
        self.assertIn("audit", d)


class TestFoundationScoringEnrichmentConstitutionalWrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = FoundationScoringEnrichmentConstitutionalWrapper()
        self.base = {
            "L1": {
                "input_ref": "EURUSD_H1_run_201",
                "timestamp": "2026-03-28T10:15:00+07:00",
                "context_coherence": 0.91,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L2": {
                "input_ref": "EURUSD_H1_run_201",
                "timestamp": "2026-03-28T10:15:00+07:00",
                "alignment_score": 0.88,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L3": {
                "input_ref": "EURUSD_H1_run_201",
                "timestamp": "2026-03-28T10:15:00+07:00",
                "confirmation_score": 0.87,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
        }

    def test_end_to_end_with_phase25(self) -> None:
        result = self.wrapper.run(self.base)
        self.assertFalse(result.halted)
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, ["PHASE_3"])
        self.assertIn(result.wrapper_status, {"PASS", "WARN"})
        self.assertEqual(result.phase25_result["phase"], "PHASE_2_5_ENRICHMENT")

    def test_halt_before_phase25_if_upstream_fails(self) -> None:
        payload = {**self.base}
        payload["L1"] = {**self.base["L1"], "freshness_state": "NO_PRODUCER"}
        result = self.wrapper.run(payload)
        self.assertTrue(result.halted)
        self.assertEqual(result.phase25_result, {})
        self.assertEqual(result.next_legal_targets, [])


if __name__ == "__main__":
    unittest.main()
