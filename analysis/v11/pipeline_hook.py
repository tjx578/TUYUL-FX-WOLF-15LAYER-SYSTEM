"""
V11 Pipeline Hook — integrates the V11 Extreme Selectivity Gate into the
analysis pipeline via the data adapter.

Analysis zone only.  No execution side-effects.
"""
from __future__ import annotations

import logging
from typing import Any

from analysis.v11.data_adapter import V11DataAdapter
from analysis.v11.extreme_selectivity_gate import ExtremeSelectivityGateV11, V11Thresholds
from analysis.v11.models import GateVerdict, V11GateResult

logger = logging.getLogger(__name__)


class V11PipelineHook:
    """
    Drop-in hook for the analysis pipeline.

    Usage in pipeline:
        hook = V11PipelineHook()
        result = hook.run(pipeline_synthesis_output)
        if not result.passed:
            # candidate rejected at V11
    """

    def __init__(self, thresholds: V11Thresholds | None = None) -> None:
        self._adapter = V11DataAdapter()
        self._gate = ExtremeSelectivityGateV11(thresholds=thresholds)

    def run(self, pipeline_data: dict[str, Any]) -> V11GateResult:
        """
        Full pipeline integration:
        1. Adapter collects & validates data from pipeline synthesis dict.
        2. Gate evaluates the validated input.
        3. Returns structured V11GateResult.

        Never raises.  Returns FAIL/SKIP on invalid input.
        """
        try:
            gate_input = self._adapter.collect(pipeline_data)
            result = self._gate.evaluate(gate_input)
        except Exception as exc:
            logger.error("V11PipelineHook.run unexpected error: %s", exc, exc_info=True)
            result = V11GateResult(
                verdict=GateVerdict.FAIL,
                overall_score=0.0,
                passed_checks=0,
                total_checks=0,
                failed_criteria=("internal_error",),
                details={"error": str(exc)},
            )
        return result

    def run_and_annotate(self, pipeline_data: dict[str, Any]) -> dict[str, Any]:
        """
        Run the gate and return pipeline_data annotated with v11 results.
        Useful for pipelines that pass dicts through a chain.
        """
        result = self.run(pipeline_data)
        annotated = dict(pipeline_data) if isinstance(pipeline_data, dict) else {}
        annotated["v11_gate"] = {
            "verdict": result.verdict.value,
            "overall_score": result.overall_score,
            "passed_checks": result.passed_checks,
            "total_checks": result.total_checks,
            "failed_criteria": list(result.failed_criteria),
            "passed": result.passed,
        }
        return annotated
