"""Tests for governance pipeline hook."""

from __future__ import annotations

from unittest.mock import MagicMock

from governance.pipeline_hook import GovernancePipelineHook


class TestGovernancePipelineHook:
    def test_no_components_returns_inactive(self) -> None:
        hook = GovernancePipelineHook()
        result = hook.run({"pair": "EURUSD", "synthesis": {}})
        assert result["governance"]["governance_active"] is False

    def test_drift_annotation(self) -> None:
        mock_drift = MagicMock()
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"severity": "STABLE", "should_freeze": False}
        mock_report.should_freeze = False
        mock_drift.evaluate.return_value = mock_report

        hook = GovernancePipelineHook(drift_monitor=mock_drift)
        result = hook.run(
            {
                "pair": "EURUSD",
                "synthesis": {"inference": {"regime_state": {"regime": 1}}},
            }
        )
        assert result["governance"]["governance_active"] is True
        assert result["governance"]["drift"]["severity"] == "STABLE"

    def test_drift_critical_triggers_rollout_freeze(self) -> None:
        mock_drift = MagicMock()
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"severity": "CRITICAL", "should_freeze": True}
        mock_report.should_freeze = True
        mock_report.severity = "CRITICAL"
        mock_drift.evaluate.return_value = mock_report

        mock_rollout = MagicMock()

        hook = GovernancePipelineHook(
            drift_monitor=mock_drift,
            rollout_controller=mock_rollout,
        )
        result = hook.run(
            {
                "pair": "EURUSD",
                "synthesis": {"inference": {"regime_state": {"regime": 2}}},
            }
        )
        assert result["governance"]["drift_triggered_freeze"] is True
        mock_rollout.freeze.assert_called_once()

    def test_rollout_annotation(self) -> None:
        mock_rollout = MagicMock()
        mock_state = MagicMock()
        mock_state.current_allocation_pct = 0.25
        mock_state.current_week = 1
        mock_state.frozen = False
        mock_state.freeze_reason = ""
        mock_rollout.get_state.return_value = mock_state

        hook = GovernancePipelineHook(rollout_controller=mock_rollout)
        result = hook.run({"pair": "EURUSD", "synthesis": {}})
        assert result["governance"]["rollout"]["allocation_pct"] == 0.25

    def test_exception_handling(self) -> None:
        """Hook must never raise — catches all exceptions."""
        mock_drift = MagicMock()
        mock_drift.evaluate.side_effect = RuntimeError("boom")

        hook = GovernancePipelineHook(drift_monitor=mock_drift)
        result = hook.run(
            {
                "pair": "EURUSD",
                "synthesis": {"inference": {"regime_state": {"regime": 1}}},
            }
        )
        assert "error" in str(result["governance"]["drift"])

    def test_preserves_original_pipeline_data(self) -> None:
        hook = GovernancePipelineHook()
        original = {"pair": "GBPUSD", "synthesis": {}, "l12_verdict": {"verdict": "EXECUTE"}}
        result = hook.run(original)
        assert result["pair"] == "GBPUSD"
        assert result["l12_verdict"]["verdict"] == "EXECUTE"
        assert "governance" in result
