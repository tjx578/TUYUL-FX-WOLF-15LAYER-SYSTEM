"""
Governance Pipeline Hook — non-intrusive integration with Wolf-15 pipeline.

Follows the V11 pattern: never raises, annotation-based, optional import.
Runs AFTER L12 verdict (Phase 8 area) to annotate pipeline results with
drift monitoring data and rollout allocation status.

Authority: Advisory only.
  - Does NOT override L12 verdict.
  - Adds governance metadata to synthesis for downstream consumers.
  - DriftMonitor can signal freeze to RolloutController.
"""

from __future__ import annotations

from typing import Any

from loguru import logger


class GovernancePipelineHook:
    """
    Non-intrusive pipeline hook for governance components.

    Integrates DriftMonitor and RolloutController into pipeline output
    without modifying the core pipeline flow.
    """

    def __init__(
        self,
        drift_monitor: Any | None = None,
        rollout_controller: Any | None = None,
    ) -> None:
        self._drift = drift_monitor
        self._rollout = rollout_controller

    def run(self, pipeline_data: dict[str, Any]) -> dict[str, Any]:
        """
        Annotate pipeline output with governance metadata.

        Never raises — catches all exceptions and returns safe defaults.
        """
        governance: dict[str, Any] = {
            "drift": None,
            "rollout": None,
            "governance_active": False,
        }

        # ── Drift monitoring ──────────────────────────────────────────────
        if self._drift is not None:
            try:
                inference = pipeline_data.get("synthesis", {}).get("inference", {})
                if inference:
                    report = self._drift.evaluate(inference)
                    governance["drift"] = report.to_dict()
                    governance["governance_active"] = True

                    if report.should_freeze and self._rollout is not None:
                        # Cascade drift freeze to rollout
                        strategy_id = pipeline_data.get("pair", "default")
                        self._rollout.freeze(
                            strategy_id,
                            f"drift_critical: severity={report.severity}",
                        )
                        governance["drift_triggered_freeze"] = True
            except Exception as exc:
                logger.debug("GovernancePipelineHook: drift error: {}", exc)
                governance["drift"] = {"error": str(exc)}

        # ── Rollout allocation ────────────────────────────────────────────
        if self._rollout is not None:
            try:
                strategy_id = pipeline_data.get("pair", "default")
                state = self._rollout.get_state(strategy_id)
                if state is not None:
                    governance["rollout"] = {
                        "allocation_pct": state.current_allocation_pct,
                        "current_week": state.current_week,
                        "frozen": state.frozen,
                        "freeze_reason": state.freeze_reason,
                    }
                    governance["governance_active"] = True
            except Exception as exc:
                logger.debug("GovernancePipelineHook: rollout error: {}", exc)
                governance["rollout"] = {"error": str(exc)}

        # ── Annotate pipeline data ────────────────────────────────────────
        result = dict(pipeline_data) if isinstance(pipeline_data, dict) else {}
        result["governance"] = governance
        return result
