from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from constitution.end_to_end_constitutional_wrapper_to_phase3 import (
    EndToEndConstitutionalWrapperToPhase3,
)
from constitution.foundation_scoring_enrichment_constitutional_wrapper import (
    FoundationScoringEnrichmentResult,
)
from constitution.foundation_scoring_enrichment_to_phase3_bridge_adapter import (
    FoundationScoringEnrichmentToPhase3BridgeAdapter,
)
from constitution.phase3_chain_adapter import Phase3ChainAdapter


def _make_upstream_pass(input_ref: str, timestamp: str) -> FoundationScoringEnrichmentResult:
    """Build a PASS upstream result for testing."""
    return FoundationScoringEnrichmentResult(
        wrapper="FOUNDATION_SCORING_ENRICHMENT_WRAPPER",
        wrapper_version="1.0.0",
        input_ref=input_ref,
        timestamp=timestamp,
        halted=False,
        halted_at=None,
        continuation_allowed=True,
        next_legal_targets=["PHASE_3"],
        wrapper_status="PASS",
        upstream_result={
            "phase_results": {
                "PHASE_1": {"layer_results": {}},
                "PHASE_2": {"layer_results": {}},
            },
            "bridge_result": {},
        },
        phase25_result={"phase_status": "PASS", "warning_list": [], "error_list": []},
        audit={"steps": ["test"]},
    )


def _make_upstream_warn(input_ref: str, timestamp: str) -> FoundationScoringEnrichmentResult:
    """Build a WARN upstream result for testing."""
    return FoundationScoringEnrichmentResult(
        wrapper="FOUNDATION_SCORING_ENRICHMENT_WRAPPER",
        wrapper_version="1.0.0",
        input_ref=input_ref,
        timestamp=timestamp,
        halted=False,
        halted_at=None,
        continuation_allowed=True,
        next_legal_targets=["PHASE_3"],
        wrapper_status="WARN",
        upstream_result={
            "phase_results": {
                "PHASE_1": {
                    "layer_results": {
                        "L2": {
                            "freshness_state": "STALE_PRESERVED",
                            "warmup_state": "PARTIAL",
                            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
                        }
                    }
                },
                "PHASE_2": {"layer_results": {}},
            },
            "bridge_result": {},
        },
        phase25_result={"phase_status": "WARN", "warning_list": ["e1_partial"], "error_list": []},
        audit={"steps": ["test"]},
    )


def _make_upstream_halt(input_ref: str, timestamp: str) -> FoundationScoringEnrichmentResult:
    """Build a halted upstream result for testing."""
    return FoundationScoringEnrichmentResult(
        wrapper="FOUNDATION_SCORING_ENRICHMENT_WRAPPER",
        wrapper_version="1.0.0",
        input_ref=input_ref,
        timestamp=timestamp,
        halted=True,
        halted_at="PHASE_1",
        continuation_allowed=False,
        next_legal_targets=[],
        wrapper_status="FAIL",
        upstream_result={},
        phase25_result={},
        audit={"steps": ["test"]},
    )


class TestEndToEndConstitutionalWrapperToPhase3(unittest.TestCase):
    def setUp(self) -> None:
        self.input_ref = "EURUSD_H1_run_800"
        self.timestamp = "2026-03-28T16:30:00+07:00"
        self.base = {
            "L1": {
                "input_ref": self.input_ref,
                "timestamp": self.timestamp,
                "context_coherence": 0.91,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L2": {
                "input_ref": self.input_ref,
                "timestamp": self.timestamp,
                "alignment_score": 0.88,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
            "L3": {
                "input_ref": self.input_ref,
                "timestamp": self.timestamp,
                "confirmation_score": 0.87,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
            },
        }

    def _build_wrapper(
        self,
        upstream_result: FoundationScoringEnrichmentResult | None = None,
    ) -> EndToEndConstitutionalWrapperToPhase3:
        """Build an E2E wrapper with a mocked upstream."""
        mock_upstream = MagicMock()
        if upstream_result is None:
            upstream_result = _make_upstream_pass(self.input_ref, self.timestamp)
        mock_upstream.run.return_value = upstream_result
        bridge = FoundationScoringEnrichmentToPhase3BridgeAdapter()
        phase3 = Phase3ChainAdapter()
        return EndToEndConstitutionalWrapperToPhase3(
            upstream_wrapper=mock_upstream,
            bridge_adapter=bridge,
            phase3_adapter=phase3,
        )

    def test_end_to_end_pass_to_phase3(self) -> None:
        wrapper = self._build_wrapper()
        result = wrapper.run(self.base)
        self.assertFalse(result.halted)
        self.assertEqual(result.wrapper_status, "PASS")
        self.assertTrue(result.continuation_allowed)
        self.assertEqual(result.next_legal_targets, ["PHASE_4"])
        self.assertEqual(result.phase3_result["phase"], "PHASE_3_STRUCTURE")
        self.assertEqual(result.phase3_result["chain_status"], "PASS")

    def test_end_to_end_warn_to_phase3(self) -> None:
        upstream = _make_upstream_warn(self.input_ref, self.timestamp)
        wrapper = self._build_wrapper(upstream_result=upstream)
        result = wrapper.run(self.base)
        self.assertFalse(result.halted)
        self.assertEqual(result.wrapper_status, "WARN")
        self.assertEqual(result.phase3_result["chain_status"], "WARN")
        self.assertEqual(result.next_legal_targets, ["PHASE_4"])

    def test_halt_at_upstream(self) -> None:
        upstream = _make_upstream_halt(self.input_ref, self.timestamp)
        wrapper = self._build_wrapper(upstream_result=upstream)
        result = wrapper.run(self.base)
        self.assertTrue(result.halted)
        self.assertEqual(result.halted_at, "UPSTREAM")
        self.assertEqual(result.wrapper_status, "FAIL")
        self.assertEqual(result.bridge_result, {})
        self.assertEqual(result.phase3_result, {})

    def test_bridge_result_embedded(self) -> None:
        wrapper = self._build_wrapper()
        result = wrapper.run(self.base)
        self.assertEqual(result.bridge_result["bridge"], "FOUNDATION_SCORING_ENRICHMENT_TO_PHASE3")
        self.assertTrue(result.bridge_result["bridge_allowed"])

    def test_phase3_result_embedded(self) -> None:
        wrapper = self._build_wrapper()
        result = wrapper.run(self.base)
        self.assertEqual(result.phase3_result["summary_status"], {"L7": "PASS", "L8": "PASS", "L9": "PASS"})


if __name__ == "__main__":
    unittest.main()
