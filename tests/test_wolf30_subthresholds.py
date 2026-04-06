"""Tests for Wolf 30-Point sub-threshold enforcement and additive payload.

Covers:
  - fundamental_min enforcement in L4 constitutional governor
  - fta_conflict_veto enforcement (ADVISORY + HARD modes)
  - curriculum_grade and fta_conflict fields in L4 scoring payload
  - _classify_curriculum_grade() function
  - _detect_fta_conflict() function
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from analysis.layers.L4_constitutional import (
    BlockerCode,
    _enforce_wolf_sub_thresholds,
)
from analysis.layers.L4_session_scoring import (
    _classify_curriculum_grade,
    _classify_grade,
    _detect_fta_conflict,
)

# ═══════════════════════════════════════════════════════════════════════════
# §1  _classify_curriculum_grade
# ═══════════════════════════════════════════════════════════════════════════


class TestClassifyCurriculumGrade:
    """Curriculum grade uses stricter thresholds than production."""

    @pytest.mark.parametrize(
        ("total", "expected"),
        [
            (30, "PERFECT"),
            (27, "PERFECT"),
            (26, "EXCELLENT"),
            (24, "EXCELLENT"),
            (23, "GOOD"),  # production would give EXCELLENT
            (20, "GOOD"),
            (19, "MARGINAL"),  # production would give GOOD
            (15, "MARGINAL"),
            (14, "FAIL"),
            (0, "FAIL"),
        ],
    )
    def test_curriculum_grade_thresholds(self, total: float, expected: str) -> None:
        assert _classify_curriculum_grade(total) == expected

    def test_curriculum_stricter_than_production(self) -> None:
        """Score 23 is EXCELLENT in production but GOOD in curriculum."""
        assert _classify_grade(23) == "EXCELLENT"
        assert _classify_curriculum_grade(23) == "GOOD"


# ═══════════════════════════════════════════════════════════════════════════
# §2  _detect_fta_conflict
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectFtaConflict:
    """L1↔L2 direction mismatch detection."""

    def test_conflict_bullish_vs_bearish(self) -> None:
        detail = {"l1_direction": "BULLISH", "l2_direction": "BEARISH"}
        assert _detect_fta_conflict(detail) is True

    def test_conflict_bearish_vs_bullish(self) -> None:
        detail = {"l1_direction": "BEARISH", "l2_direction": "BULLISH"}
        assert _detect_fta_conflict(detail) is True

    def test_no_conflict_aligned(self) -> None:
        detail = {"l1_direction": "BULLISH", "l2_direction": "BULLISH"}
        assert _detect_fta_conflict(detail) is False

    def test_no_conflict_neutral_l1(self) -> None:
        detail = {"l1_direction": "NEUTRAL", "l2_direction": "BEARISH"}
        assert _detect_fta_conflict(detail) is False

    def test_no_conflict_neutral_l2(self) -> None:
        detail = {"l1_direction": "BULLISH", "l2_direction": "NEUTRAL"}
        assert _detect_fta_conflict(detail) is False

    def test_no_conflict_both_neutral(self) -> None:
        detail = {"l1_direction": "NEUTRAL", "l2_direction": "NEUTRAL"}
        assert _detect_fta_conflict(detail) is False

    def test_missing_keys_default_neutral(self) -> None:
        assert _detect_fta_conflict({}) is False


# ═══════════════════════════════════════════════════════════════════════════
# §3  _enforce_wolf_sub_thresholds
# ═══════════════════════════════════════════════════════════════════════════


def _mock_wolf_constitution(
    fundamental_min: int | None = 5,
    veto_enabled: bool = False,
    veto_mode: str = "ADVISORY",
    hard_fail: bool = False,
) -> dict:
    """Build a mock wolf_30_point constitution section."""
    cfg: dict = {
        "max_score": 30,
        "min_score": 22,
        "sub_thresholds": {
            "technical_min": 9,
            "fta_min": 3,
            "execution_min": 4,
        },
        "fta_conflict_veto": {
            "enabled": veto_enabled,
            "mode": veto_mode,
            "hard_fail_on_conflict": hard_fail,
        },
    }
    if fundamental_min is not None:
        cfg["sub_thresholds"]["fundamental_min"] = fundamental_min
    return cfg


class TestEnforceFundamentalMin:
    """fundamental_min enforcement in L4 constitutional."""

    def test_f_score_above_min_no_blocker(self) -> None:
        wolf = {"f_score": 6.0, "fta_conflict": False}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(fundamental_min=5),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert not blockers
        assert not any("FUNDAMENTAL" in w for w in warnings)

    def test_f_score_below_min_triggers_blocker(self) -> None:
        wolf = {"f_score": 3.0, "fta_conflict": False}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(fundamental_min=5),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert BlockerCode.SESSION_STATE_INVALID in blockers
        assert any("FUNDAMENTAL_BELOW_MIN" in w for w in warnings)

    def test_f_score_equal_to_min_no_blocker(self) -> None:
        wolf = {"f_score": 5.0, "fta_conflict": False}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(fundamental_min=5),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert not blockers

    def test_no_fundamental_min_in_config_skips(self) -> None:
        wolf = {"f_score": 1.0, "fta_conflict": False}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(fundamental_min=None),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert not blockers


class TestEnforceFtaConflictVeto:
    """fta_conflict_veto enforcement in L4 constitutional."""

    def test_veto_disabled_no_enforcement(self) -> None:
        wolf = {"f_score": 6.0, "fta_conflict": True}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(veto_enabled=False),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert not any("FTA_CONFLICT_VETO" in w for w in warnings)

    def test_veto_advisory_mode_warning_only(self) -> None:
        wolf = {"f_score": 6.0, "fta_conflict": True}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(
                veto_enabled=True, veto_mode="ADVISORY", hard_fail=False,
            ),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert not blockers
        assert any("FTA_CONFLICT_VETO_ADVISORY" in w for w in warnings)

    def test_veto_hard_mode_triggers_blocker(self) -> None:
        wolf = {"f_score": 6.0, "fta_conflict": True}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(
                veto_enabled=True, veto_mode="HARD", hard_fail=True,
            ),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert BlockerCode.SESSION_STATE_INVALID in blockers
        assert any("FTA_CONFLICT_VETO_HARD" in w for w in warnings)

    def test_veto_enabled_no_conflict_no_action(self) -> None:
        wolf = {"f_score": 6.0, "fta_conflict": False}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(
                veto_enabled=True, veto_mode="HARD", hard_fail=True,
            ),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert not blockers
        assert not any("FTA_CONFLICT_VETO" in w for w in warnings)

    def test_hard_fail_flag_overrides_advisory_mode(self) -> None:
        """hard_fail_on_conflict=true should block even if mode=ADVISORY."""
        wolf = {"f_score": 6.0, "fta_conflict": True}
        blockers: list[BlockerCode] = []
        warnings: list[str] = []
        rules: list[str] = []

        with patch(
            "analysis.layers.L4_constitutional._load_wolf_constitution",
            return_value=_mock_wolf_constitution(
                veto_enabled=True, veto_mode="ADVISORY", hard_fail=True,
            ),
        ):
            _enforce_wolf_sub_thresholds(wolf, {}, blockers, warnings, rules)

        assert BlockerCode.SESSION_STATE_INVALID in blockers
