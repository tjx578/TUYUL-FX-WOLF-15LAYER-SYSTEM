"""Integration tests for effective constitution adapter (Commit 8 / Phase E).

Covers:
  - get_effective_constitution() returns profile-merged constitution
  - get_effective_threshold() dot-path traversal with profile overrides
  - Fallback to raw CONFIG when profile engine is unavailable
  - Profile activation changes effective thresholds
  - Verdict payload carries constitution_profile metadata
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

from config.effective_constitution import (
    get_effective_constitution,
    get_effective_threshold,
)

# ═══════════════════════════════════════════════════════════════════════════
# §1  get_effective_constitution
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEffectiveConstitution:
    """get_effective_constitution() returns profile-merged dict."""

    def test_returns_dict(self) -> None:
        result = get_effective_constitution()
        assert isinstance(result, dict)

    def test_contains_wolf_30_point(self) -> None:
        result = get_effective_constitution()
        assert "wolf_30_point" in result

    def test_contains_sub_thresholds(self) -> None:
        result = get_effective_constitution()
        sub = result.get("wolf_30_point", {}).get("sub_thresholds", {})
        assert "technical_min" in sub
        assert "fta_min" in sub
        assert "execution_min" in sub

    def test_fundamental_min_present(self) -> None:
        """fundamental_min was added in Phase B."""
        result = get_effective_constitution()
        sub = result.get("wolf_30_point", {}).get("sub_thresholds", {})
        assert "fundamental_min" in sub
        assert sub["fundamental_min"] == 5

    def test_returns_copy_not_reference(self) -> None:
        a = get_effective_constitution()
        b = get_effective_constitution()
        a["_mutate_test"] = True
        assert "_mutate_test" not in b

    def test_fallback_on_profile_engine_error(self) -> None:
        """When ConfigProfileEngine raises, falls back to raw CONFIG."""
        with patch(
            "config.profile_engine.ConfigProfileEngine",
            side_effect=RuntimeError("broken"),
        ):
            result = get_effective_constitution()
            assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════
# §2  get_effective_threshold
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEffectiveThreshold:
    """get_effective_threshold() traverses dot-paths in effective constitution."""

    def test_top_level_key(self) -> None:
        result = get_effective_threshold("wolf_30_point")
        assert isinstance(result, dict)

    def test_nested_dot_path(self) -> None:
        result = get_effective_threshold("wolf_30_point.sub_thresholds.technical_min")
        assert result == 9

    def test_fundamental_min_via_dot_path(self) -> None:
        result = get_effective_threshold("wolf_30_point.sub_thresholds.fundamental_min")
        assert result == 5

    def test_missing_key_returns_default(self) -> None:
        result = get_effective_threshold("nonexistent.key.path", default=42)
        assert result == 42

    def test_missing_key_returns_none_by_default(self) -> None:
        result = get_effective_threshold("does.not.exist")
        assert result is None

    def test_partial_path_returns_dict(self) -> None:
        result = get_effective_threshold("wolf_30_point.sub_thresholds")
        assert isinstance(result, dict)
        assert "technical_min" in result


# ═══════════════════════════════════════════════════════════════════════════
# §3  Profile activation changes effective thresholds
# ═══════════════════════════════════════════════════════════════════════════


class TestProfileActivationEffect:
    """When a profile with constitution overrides is active,
    get_effective_constitution() reflects those overrides."""

    def _make_mock_engine(self, constitution_overrides: dict[str, Any]) -> MagicMock:
        mock_engine = MagicMock()
        base_config: dict[str, Any] = {
            "constitution": {
                "wolf_30_point": {
                    "min_score": 22,
                    "sub_thresholds": {
                        "technical_min": 9,
                        "fta_min": 3,
                        "execution_min": 4,
                        "fundamental_min": 5,
                    },
                },
                "tii_min": 0.72,
            }
        }
        merged = deepcopy(base_config)
        # Deep merge constitution overrides
        for k, v in constitution_overrides.items():
            if isinstance(v, dict) and isinstance(merged["constitution"].get(k), dict):
                merged["constitution"][k].update(v)
            else:
                merged["constitution"][k] = v

        mock_engine.return_value.get_effective_config.return_value = merged
        return mock_engine

    def test_strict_profile_raises_tii_min(self) -> None:
        mock = self._make_mock_engine({"tii_min": 0.93})
        with patch("config.profile_engine.ConfigProfileEngine", mock):
            result = get_effective_constitution()
            assert result["tii_min"] == 0.93

    def test_strict_profile_raises_fundamental_min(self) -> None:
        mock = self._make_mock_engine(
            {
                "wolf_30_point": {
                    "min_score": 22,
                    "sub_thresholds": {
                        "technical_min": 9,
                        "fta_min": 3,
                        "execution_min": 4,
                        "fundamental_min": 6,
                    },
                }
            }
        )
        with patch("config.profile_engine.ConfigProfileEngine", mock):
            result = get_effective_constitution()
            sub = result["wolf_30_point"]["sub_thresholds"]
            assert sub["fundamental_min"] == 6

    def test_default_profile_preserves_original(self) -> None:
        mock = self._make_mock_engine({})
        with patch("config.profile_engine.ConfigProfileEngine", mock):
            result = get_effective_constitution()
            assert result["tii_min"] == 0.72


# ═══════════════════════════════════════════════════════════════════════════
# §4  Verdict carries constitution_profile metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestVerdictConstitutionProfile:
    """generate_l12_verdict() return dict contains constitution_profile."""

    @staticmethod
    def _make_synthesis() -> dict[str, Any]:
        return {
            "layers": {
                "L8_tii_sym": 0.85,
                "L8_integrity_index": 0.90,
                "L7_monte_carlo_win": 0.65,
                "conf12": 0.75,
                "enrichment_score": 0.0,
            },
            "scores": {
                "fta_score": 0.70,
                "wolf_30_point": 25,
            },
            "execution": {"rr_ratio": 2.5},
            "propfirm": {"compliant": True},
            "risk": {"current_drawdown": 1.0, "max_drawdown": 5.0},
            "bias": {"technical": "BULLISH"},
            "system": {"latency_ms": 50},
        }

    def test_verdict_contains_constitution_profile_key(self) -> None:
        from constitution.verdict_engine import generate_l12_verdict

        result = generate_l12_verdict(self._make_synthesis())
        assert "constitution_profile" in result

    def test_verdict_constitution_profile_is_string(self) -> None:
        from constitution.verdict_engine import generate_l12_verdict

        result = generate_l12_verdict(self._make_synthesis())
        assert isinstance(result["constitution_profile"], str)

    def test_verdict_constitution_profile_default(self) -> None:
        from constitution.verdict_engine import generate_l12_verdict

        result = generate_l12_verdict(self._make_synthesis())
        # Default profile should be "default" unless env-var overrides it
        assert result["constitution_profile"] in (
            "default",
            "production_pragmatic",
            "wolf_curriculum_strict",
        )

    def test_verdict_profile_reflects_mocked_engine(self) -> None:
        mock_engine = MagicMock()
        mock_engine.return_value.get_active_profile.return_value = "wolf_curriculum_strict"
        with patch(
            "config.profile_engine.ConfigProfileEngine",
            mock_engine,
        ):
            from constitution.verdict_engine import generate_l12_verdict

            result = generate_l12_verdict(self._make_synthesis())
            assert result["constitution_profile"] == "wolf_curriculum_strict"
