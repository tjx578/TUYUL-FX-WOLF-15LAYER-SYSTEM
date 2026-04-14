"""Tests for governance staged validation pipeline."""

from __future__ import annotations

import pytest

from governance.passport import (
    STAGE_ORDER,
    PassportStatus,
    Stage,
    StageMetrics,
    StagePassport,
    build_passport,
)
from governance.stage_gates import (
    GateThresholds,
    evaluate_all_gates,
    evaluate_gate,
)
from governance.stage_orchestrator import StageOrchestrator

# ── Passport tests ────────────────────────────────────────────────────────────


class TestPassport:
    def test_build_passport_creates_valid_id(self) -> None:
        metrics = StageMetrics(sharpe=1.5, win_rate=0.55, profit_factor=1.8, sample_trades=300)
        pp = build_passport(
            strategy_id="test_strat",
            stage=Stage.BACKTEST,
            status=PassportStatus.PASS,
            metrics=metrics,
            issued_by="backtest_gate",
            run_id="run_001",
        )
        assert pp.passport_id.startswith("pp_test_strat_BACKTEST_")
        assert pp.status == PassportStatus.PASS
        assert pp.checksum != ""
        assert len(pp.checksum) == 64  # sha256

    def test_passport_is_frozen(self) -> None:
        pp = build_passport(
            strategy_id="s1",
            stage=Stage.PAPER,
            status=PassportStatus.FAIL,
            metrics=StageMetrics(),
            issued_by="paper_gate",
        )
        with pytest.raises(AttributeError):
            pp.status = PassportStatus.PASS  # type: ignore[misc]

    def test_checksum_deterministic(self) -> None:
        metrics = StageMetrics(sharpe=1.2)
        c1 = StagePassport.compute_checksum("s1", "BACKTEST", "PASS", metrics.to_dict(), "r1")
        c2 = StagePassport.compute_checksum("s1", "BACKTEST", "PASS", metrics.to_dict(), "r1")
        assert c1 == c2

    def test_checksum_changes_on_different_input(self) -> None:
        m1 = StageMetrics(sharpe=1.2)
        m2 = StageMetrics(sharpe=1.3)
        c1 = StagePassport.compute_checksum("s1", "BACKTEST", "PASS", m1.to_dict(), "r1")
        c2 = StagePassport.compute_checksum("s1", "BACKTEST", "PASS", m2.to_dict(), "r1")
        assert c1 != c2

    def test_to_dict(self) -> None:
        pp = build_passport(
            strategy_id="s1",
            stage=Stage.BACKTEST,
            status=PassportStatus.PASS,
            metrics=StageMetrics(sharpe=1.5),
            issued_by="test",
        )
        d = pp.to_dict()
        assert d["stage"] == "BACKTEST"
        assert d["status"] == "PASS"
        assert isinstance(d["metrics"], dict)

    def test_stage_order(self) -> None:
        assert STAGE_ORDER == (Stage.BACKTEST, Stage.OPTIMIZATION, Stage.PAPER, Stage.ROLLOUT)


# ── Gate tests ────────────────────────────────────────────────────────────────


class TestStageGates:
    def test_backtest_pass(self) -> None:
        metrics = StageMetrics(
            sharpe=1.5,
            max_drawdown_pct=5.0,
            profit_factor=2.0,
            win_rate=0.58,
            sample_trades=300,
        )
        status, failures = evaluate_gate(Stage.BACKTEST, metrics)
        assert status == PassportStatus.PASS
        assert failures == []

    def test_backtest_fail_sharpe(self) -> None:
        metrics = StageMetrics(
            sharpe=0.8,  # below 1.2
            max_drawdown_pct=5.0,
            profit_factor=2.0,
            win_rate=0.58,
            sample_trades=300,
        )
        status, failures = evaluate_gate(Stage.BACKTEST, metrics)
        assert status == PassportStatus.FAIL
        assert any("sharpe" in f for f in failures)

    def test_backtest_fail_multiple(self) -> None:
        metrics = StageMetrics(
            sharpe=0.5,
            max_drawdown_pct=15.0,
            profit_factor=1.2,
            win_rate=0.40,
            sample_trades=50,
        )
        status, failures = evaluate_gate(Stage.BACKTEST, metrics)
        assert status == PassportStatus.FAIL
        assert len(failures) >= 4

    def test_optimization_pass(self) -> None:
        metrics = StageMetrics(
            oos_degradation_pct=15.0,
            stability_score=0.85,
        )
        status, failures = evaluate_gate(Stage.OPTIMIZATION, metrics)
        assert status == PassportStatus.PASS

    def test_optimization_fail_degradation(self) -> None:
        metrics = StageMetrics(
            oos_degradation_pct=30.0,  # above 25%
            stability_score=0.85,
        )
        status, failures = evaluate_gate(Stage.OPTIMIZATION, metrics)
        assert status == PassportStatus.FAIL
        assert any("oos_degradation" in f for f in failures)

    def test_custom_thresholds(self) -> None:
        custom = GateThresholds(min_sharpe=2.0)
        metrics = StageMetrics(sharpe=1.5)
        status, failures = evaluate_gate(Stage.BACKTEST, metrics, custom)
        assert status == PassportStatus.FAIL

    def test_evaluate_all_gates_all_pass(self) -> None:
        passports = {
            Stage.BACKTEST: {"status": "PASS"},
            Stage.OPTIMIZATION: {"status": "PASS"},
            Stage.PAPER: {"status": "PASS"},
            Stage.ROLLOUT: {"status": "PASS"},
        }
        all_pass, results = evaluate_all_gates(passports)
        assert all_pass is True

    def test_evaluate_all_gates_missing(self) -> None:
        passports = {
            Stage.BACKTEST: {"status": "PASS"},
        }
        all_pass, results = evaluate_all_gates(passports)
        assert all_pass is False
        assert results[Stage.OPTIMIZATION][0] == PassportStatus.PENDING

    def test_evaluate_all_gates_fail(self) -> None:
        passports = {
            Stage.BACKTEST: {"status": "FAIL", "notes": "bad sharpe"},
            Stage.OPTIMIZATION: {"status": "PASS"},
            Stage.PAPER: {"status": "PASS"},
            Stage.ROLLOUT: {"status": "PASS"},
        }
        all_pass, results = evaluate_all_gates(passports)
        assert all_pass is False
        assert results[Stage.BACKTEST][0] == PassportStatus.FAIL


# ── Orchestrator tests ────────────────────────────────────────────────────────


class TestStageOrchestrator:
    def setup_method(self) -> None:
        self.orch = StageOrchestrator(redis_client=None)

    def test_register_strategy(self, tmp_path, monkeypatch) -> None:
        import governance.stage_orchestrator as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)
        state = self.orch.register_strategy("test_s1")
        assert state.strategy_id == "test_s1"
        assert state.current_stage == Stage.BACKTEST
        assert not state.frozen

    def test_submit_and_promote(self, tmp_path, monkeypatch) -> None:
        import governance.stage_orchestrator as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.orch.register_strategy("s1")

        metrics = StageMetrics(
            sharpe=1.5,
            max_drawdown_pct=5.0,
            profit_factor=2.0,
            win_rate=0.58,
            sample_trades=300,
        )
        pp = self.orch.submit_stage_result("s1", Stage.BACKTEST, metrics, run_id="run1")
        assert pp.status == PassportStatus.PASS

        ok, msg = self.orch.promote("s1")
        assert ok is True
        assert "OPTIMIZATION" in msg

        state = self.orch.get_state("s1")
        assert state is not None
        assert state.current_stage == Stage.OPTIMIZATION

    def test_cannot_promote_without_pass(self, tmp_path, monkeypatch) -> None:
        import governance.stage_orchestrator as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.orch.register_strategy("s2")
        metrics = StageMetrics(sharpe=0.5)  # will fail backtest gate
        self.orch.submit_stage_result("s2", Stage.BACKTEST, metrics)

        ok, msg = self.orch.promote("s2")
        assert ok is False
        assert "FAIL" in msg

    def test_stage_mismatch_rejected(self, tmp_path, monkeypatch) -> None:
        import governance.stage_orchestrator as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.orch.register_strategy("s3")
        metrics = StageMetrics()
        pp = self.orch.submit_stage_result("s3", Stage.PAPER, metrics)
        assert pp.status == PassportStatus.FAIL
        assert "stage mismatch" in pp.notes

    def test_freeze_blocks_promotion(self, tmp_path, monkeypatch) -> None:
        import governance.stage_orchestrator as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.orch.register_strategy("s4")
        self.orch.freeze("s4", "test freeze")

        metrics = StageMetrics(sharpe=2.0, profit_factor=3.0, win_rate=0.70, sample_trades=500)
        pp = self.orch.submit_stage_result("s4", Stage.BACKTEST, metrics)
        assert pp.status == PassportStatus.FAIL
        assert "frozen" in pp.notes

    def test_is_live_ready_full_cycle(self, tmp_path, monkeypatch) -> None:
        import governance.stage_orchestrator as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.orch.register_strategy("s5")

        good = StageMetrics(
            sharpe=1.5,
            max_drawdown_pct=5.0,
            profit_factor=2.0,
            win_rate=0.58,
            sample_trades=300,
            stability_score=0.85,
        )

        # Backtest
        self.orch.submit_stage_result("s5", Stage.BACKTEST, good)
        self.orch.promote("s5")

        # Optimization
        self.orch.submit_stage_result("s5", Stage.OPTIMIZATION, good)
        self.orch.promote("s5")

        # Paper
        paper = StageMetrics(win_rate=0.55, sample_trades=50)
        self.orch.submit_stage_result("s5", Stage.PAPER, paper)
        self.orch.promote("s5")

        # Rollout
        rollout = StageMetrics(win_rate=0.55, max_drawdown_pct=6.0)
        self.orch.submit_stage_result("s5", Stage.ROLLOUT, rollout)

        ready, msg = self.orch.is_live_ready("s5")
        assert ready is True
