"""Tests for the 4 gap fixes: warmup multi-TF, WARMUP_MIN_BARS, MC threshold, orchestrator wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from execution.execution_guard import ExecutionGuard

# ═══════════════════════════════════════════════════════════════════
# GAP 1 & 2: WARMUP_MIN_BARS includes W1 and MN
# ═══════════════════════════════════════════════════════════════════


class TestWarmupMinBarsInclusion:
    """WARMUP_MIN_BARS must include W1 and MN for L1 context integrity."""

    def test_warmup_includes_w1_and_mn(self) -> None:
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        bars = WolfConstitutionalPipeline.WARMUP_MIN_BARS
        assert "W1" in bars, "WARMUP_MIN_BARS must include W1"
        assert "MN" in bars, "WARMUP_MIN_BARS must include MN"

    def test_warmup_still_has_core_timeframes(self) -> None:
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        bars = WolfConstitutionalPipeline.WARMUP_MIN_BARS
        assert "H1" in bars
        assert "H4" in bars
        assert "D1" in bars

    def test_warmup_does_not_include_m15(self) -> None:
        """M15 arrives from ticks, must NOT gate pipeline startup."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        bars = WolfConstitutionalPipeline.WARMUP_MIN_BARS
        assert "M15" not in bars

    def test_warmup_w1_minimum_sane(self) -> None:
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        assert WolfConstitutionalPipeline.WARMUP_MIN_BARS["W1"] >= 2

    def test_warmup_mn_minimum_sane(self) -> None:
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        assert WolfConstitutionalPipeline.WARMUP_MIN_BARS["MN"] >= 2


# ═══════════════════════════════════════════════════════════════════
# GAP 3: Monte Carlo threshold enforcement
# ═══════════════════════════════════════════════════════════════════


class TestMonteCarloJobThreshold:
    """montecarlo_job must enforce monte_min from constitution config."""

    def test_build_engine_uses_monte_min(self) -> None:
        with patch("services.worker.montecarlo_job.get_monte_min", return_value=0.55):
            from services.worker.montecarlo_job import _build_engine

            engine = _build_engine()
            assert engine.win_threshold == 0.55

    def test_build_engine_custom_monte_min(self) -> None:
        with patch("services.worker.montecarlo_job.get_monte_min", return_value=0.60):
            from services.worker.montecarlo_job import _build_engine

            engine = _build_engine()
            assert engine.win_threshold == 0.60

    def test_run_publishes_threshold_info(self) -> None:
        """Published payload must include monte_min_threshold and passed_threshold."""
        mock_result = MagicMock()
        mock_result.passed_threshold = True
        mock_result.portfolio_win_probability = 0.62
        mock_result.to_dict.return_value = {"passed_threshold": True}

        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        published: list[dict[str, Any]] = []

        def capture_publish(key: str, payload: dict[str, Any]) -> None:
            published.append(payload)

        with (
            patch("services.worker.montecarlo_job.get_monte_min", return_value=0.55),
            patch("services.worker.montecarlo_job._build_engine", return_value=mock_engine),
            patch("services.worker.montecarlo_job.load_json_payload", return_value={"EURUSD": [0.1], "GBPUSD": [0.2]}),
            patch(
                "services.worker.montecarlo_job.normalize_return_matrix",
                return_value={"EURUSD": [0.1, 0.2], "GBPUSD": [0.3, 0.4]},
            ),
            patch("services.worker.montecarlo_job.publish_result", side_effect=capture_publish),
            patch("services.worker.montecarlo_job.write_json_artifact", return_value="test.json"),
        ):
            from services.worker.montecarlo_job import run

            run()

        assert len(published) == 1
        assert published[0]["monte_min_threshold"] == 0.55
        assert published[0]["passed_threshold"] is True


# ═══════════════════════════════════════════════════════════════════
# GAP 4: Orchestrator mode wired to ExecutionGuard
# ═══════════════════════════════════════════════════════════════════


class TestOrchestratorModeInExecutionGuard:
    """ExecutionGuard must check orchestrator mode before allowing execution."""

    def test_normal_mode_allows_execution(self) -> None:
        guard = ExecutionGuard()
        guard.set_orchestrator_mode_provider(lambda: "NORMAL")
        result = guard.validate_scope(account_id="ACC001")
        assert result.allowed is True

    def test_kill_switch_blocks_execution(self) -> None:
        guard = ExecutionGuard()
        guard.set_orchestrator_mode_provider(lambda: "KILL_SWITCH")
        result = guard.validate_scope(account_id="ACC001")
        assert result.allowed is False
        assert result.code == "ORCHESTRATOR_KILL_SWITCH"

    def test_safe_mode_blocks_new_execution(self) -> None:
        guard = ExecutionGuard()
        guard.set_orchestrator_mode_provider(lambda: "SAFE")
        result = guard.validate_scope(account_id="ACC001")
        assert result.allowed is False
        assert result.code == "ORCHESTRATOR_SAFE_MODE"

    def test_default_provider_is_normal(self) -> None:
        """Without explicit provider, default should be NORMAL (no block)."""
        guard = ExecutionGuard()
        result = guard.validate_scope(account_id="ACC001")
        assert result.allowed is True

    def test_orchestrator_check_before_account_kill(self) -> None:
        """Orchestrator kill switch should be checked before account-level gates."""
        guard = ExecutionGuard()
        guard.set_orchestrator_mode_provider(lambda: "KILL_SWITCH")
        # Even with valid account, orchestrator blocks first
        result = guard.validate_scope(account_id="ACC001")
        assert result.code == "ORCHESTRATOR_KILL_SWITCH"

    def test_execute_method_respects_orchestrator_mode(self) -> None:
        """The execute() method delegates to validate_scope which checks orchestrator."""
        guard = ExecutionGuard()
        guard.set_orchestrator_mode_provider(lambda: "KILL_SWITCH")
        result = guard.execute("SIG001", "ACC001", symbol="EURUSD")
        assert result.allowed is False
        assert result.code == "ORCHESTRATOR_KILL_SWITCH"
