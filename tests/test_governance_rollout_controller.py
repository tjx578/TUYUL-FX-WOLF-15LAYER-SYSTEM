"""Tests for governance rollout controller."""

from __future__ import annotations

import pytest

from governance.rollout_controller import (
    RolloutController,
    RolloutGuardRails,
)


class TestRolloutController:
    def setup_method(self) -> None:
        self.ctrl = RolloutController(redis_client=None)

    def test_start_rollout(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        state = self.ctrl.start_rollout("strat_1", backtest_dd_pct=6.0)
        assert state.strategy_id == "strat_1"
        assert state.current_allocation_pct == 0.10
        assert state.current_week == 0
        assert not state.frozen

    def test_get_allocation_pct_not_found(self) -> None:
        assert self.ctrl.get_allocation_pct("nonexistent") == 0.0

    def test_ramp_schedule(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s1", backtest_dd_pct=8.0)

        # Week 1: healthy metrics → ramp to 25%
        pct, msg = self.ctrl.evaluate_and_ramp(
            "s1",
            rolling_win_rate=0.55,
            realized_dd_pct=2.0,
            trades_this_week=10,
        )
        assert pct == 0.25
        assert "25%" in msg

        # Week 2: still healthy → ramp to 40%
        pct, msg = self.ctrl.evaluate_and_ramp(
            "s1",
            rolling_win_rate=0.52,
            realized_dd_pct=3.0,
            trades_this_week=8,
        )
        assert pct == 0.40

    def test_freeze_on_dd_breach(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s2", backtest_dd_pct=8.0)

        # DD exceeds 60% of backtest DD (8% * 0.6 = 4.8%)
        pct, msg = self.ctrl.evaluate_and_ramp(
            "s2",
            rolling_win_rate=0.50,
            realized_dd_pct=6.0,  # 6/8 = 75% > 60%
            trades_this_week=10,
        )
        assert "FROZEN" in msg

        state = self.ctrl.get_state("s2")
        assert state is not None
        assert state.frozen is True

    def test_freeze_on_win_rate_collapse(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s3", backtest_dd_pct=8.0)

        pct, msg = self.ctrl.evaluate_and_ramp(
            "s3",
            rolling_win_rate=0.35,  # below 0.45
            realized_dd_pct=2.0,
            trades_this_week=10,
        )
        assert "FROZEN" in msg

    def test_freeze_on_drift_critical(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s4", backtest_dd_pct=8.0)

        pct, msg = self.ctrl.evaluate_and_ramp(
            "s4",
            rolling_win_rate=0.55,
            realized_dd_pct=2.0,
            trades_this_week=10,
            drift_severity="CRITICAL",
        )
        assert "FROZEN" in msg

    def test_hold_on_insufficient_trades(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s5", backtest_dd_pct=8.0)

        pct, msg = self.ctrl.evaluate_and_ramp(
            "s5",
            rolling_win_rate=0.55,
            realized_dd_pct=2.0,
            trades_this_week=2,  # below 5
        )
        assert pct == 0.10  # stays at initial
        assert "insufficient" in msg

    def test_manual_freeze_unfreeze(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s6", backtest_dd_pct=8.0)

        assert self.ctrl.freeze("s6", "manual test") is True
        assert self.ctrl.get_allocation_pct("s6") == 0.0

        assert self.ctrl.unfreeze("s6") is True
        assert self.ctrl.get_allocation_pct("s6") == 0.10

    def test_full_ramp_to_100(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s7", backtest_dd_pct=8.0)

        expected_pcts = [0.25, 0.40, 0.55, 0.70, 0.85, 1.00]
        for i, expected in enumerate(expected_pcts):
            pct, _ = self.ctrl.evaluate_and_ramp(
                "s7",
                rolling_win_rate=0.55,
                realized_dd_pct=2.0,
                trades_this_week=10,
            )
            assert pct == pytest.approx(expected), f"Week {i + 1}: expected {expected}, got {pct}"

    def test_weekly_log_recorded(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        self.ctrl.start_rollout("s8", backtest_dd_pct=8.0)
        self.ctrl.evaluate_and_ramp(
            "s8",
            rolling_win_rate=0.55,
            realized_dd_pct=2.0,
            trades_this_week=10,
        )

        state = self.ctrl.get_state("s8")
        assert state is not None
        assert len(state.weekly_log) == 1
        assert state.weekly_log[0]["action"] == "RAMP"

    def test_custom_guard_rails(self, tmp_path, monkeypatch) -> None:
        import governance.rollout_controller as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        strict = RolloutGuardRails(min_rolling_win_rate=0.60)
        ctrl = RolloutController(redis_client=None, guard_rails=strict)
        ctrl.start_rollout("s9", backtest_dd_pct=8.0)

        pct, msg = ctrl.evaluate_and_ramp(
            "s9",
            rolling_win_rate=0.55,  # below strict 0.60
            realized_dd_pct=2.0,
            trades_this_week=10,
        )
        assert "FROZEN" in msg
