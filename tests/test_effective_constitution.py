"""Tests for config.effective_constitution adapter.

Covers:
  - get_effective_constitution() returns dict with profile overrides
  - get_effective_constitution() fallback when profile engine unavailable
  - get_effective_threshold() dot-path traversal
  - get_effective_threshold() default on missing key
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from config.effective_constitution import (
    get_effective_constitution,
    get_effective_threshold,
)

# ═══════════════════════════════════════════════════════════════════════════
# §1  get_effective_constitution
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEffectiveConstitution:
    """Profile-aware constitution accessor."""

    def test_returns_dict(self) -> None:
        result = get_effective_constitution()
        assert isinstance(result, dict)

    def test_contains_known_keys(self) -> None:
        result = get_effective_constitution()
        # constitution.yaml has wolf_30_point section
        assert "wolf_30_point" in result or result == {}

    @patch("config.effective_constitution.ConfigProfileEngine", side_effect=ImportError)
    def test_fallback_on_import_error(self, _mock: MagicMock) -> None:
        """Falls back to raw CONFIG when profile engine fails."""
        result = get_effective_constitution()
        assert isinstance(result, dict)

    @patch("config.effective_constitution.ConfigProfileEngine")
    def test_uses_profile_engine(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.get_effective_config.return_value = {
            "constitution": {"tii_min": 0.99, "custom_key": True},
        }
        mock_cls.return_value = mock_instance

        result = get_effective_constitution()
        assert result["tii_min"] == 0.99
        assert result["custom_key"] is True

    @patch("config.effective_constitution.ConfigProfileEngine")
    def test_returns_empty_when_no_constitution_key(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.get_effective_config.return_value = {}
        mock_cls.return_value = mock_instance

        result = get_effective_constitution()
        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════
# §2  get_effective_threshold
# ═══════════════════════════════════════════════════════════════════════════


class TestGetEffectiveThreshold:
    """Dot-path traversal into effective constitution."""

    @patch(
        "config.effective_constitution.get_effective_constitution",
        return_value={
            "tii_min": 0.82,
            "wolf_30_point": {
                "sub_thresholds": {"fundamental_min": 5, "technical_min": 9},
                "min_score": 22,
            },
        },
    )
    def test_top_level_key(self, _mock: MagicMock) -> None:
        assert get_effective_threshold("tii_min") == 0.82

    @patch(
        "config.effective_constitution.get_effective_constitution",
        return_value={
            "wolf_30_point": {
                "sub_thresholds": {"fundamental_min": 5},
            },
        },
    )
    def test_nested_dot_path(self, _mock: MagicMock) -> None:
        assert get_effective_threshold("wolf_30_point.sub_thresholds.fundamental_min") == 5

    @patch(
        "config.effective_constitution.get_effective_constitution",
        return_value={"wolf_30_point": {"min_score": 22}},
    )
    def test_missing_key_returns_default(self, _mock: MagicMock) -> None:
        assert get_effective_threshold("nonexistent.path", default=42) == 42

    @patch(
        "config.effective_constitution.get_effective_constitution",
        return_value={"wolf_30_point": {"min_score": 22}},
    )
    def test_missing_key_returns_none_by_default(self, _mock: MagicMock) -> None:
        assert get_effective_threshold("wolf_30_point.sub_thresholds") is None

    @patch(
        "config.effective_constitution.get_effective_constitution",
        return_value={},
    )
    def test_empty_constitution(self, _mock: MagicMock) -> None:
        assert get_effective_threshold("anything", default="fallback") == "fallback"
