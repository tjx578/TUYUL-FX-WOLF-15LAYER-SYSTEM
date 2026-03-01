"""Unit tests for engines/v11/config.py.

Tests cover:
- Dot-path access
- Default values
- is_v11_enabled() function
- get_all_v11_config()
"""

import pytest  # pyright: ignore[reportMissingImports]

from engines.v11.config import get_v11, is_v11_enabled, get_all_v11_config


class TestV11Config:
    """Tests for v11 configuration accessor."""

    def test_get_v11_top_level(self) -> None:
        """Test getting top-level config value."""
        enabled = get_v11("enabled")
        assert isinstance(enabled, bool)

    def test_get_v11_nested(self) -> None:
        """Test getting nested config value with dot-path."""
        score_min = get_v11("selectivity.score_min")
        assert isinstance(score_min, (int, float))
        assert 0.0 <= score_min <= 1.0

    def test_get_v11_with_default(self) -> None:
        """Test default value when path not found."""
        value = get_v11("nonexistent.path", 42)
        assert value == 42

    def test_get_v11_missing_no_default(self) -> None:
        """Test missing path without default returns None."""
        value = get_v11("nonexistent.path")
        assert value is None

    def test_is_v11_enabled(self) -> None:
        """Test is_v11_enabled() function."""
        enabled = is_v11_enabled()
        assert isinstance(enabled, bool)

    def test_get_all_v11_config(self) -> None:
        """Test getting full config."""
        config = get_all_v11_config()
        assert isinstance(config, dict)
        assert "enabled" in config
        assert "selectivity" in config
        assert "veto" in config

    def test_veto_thresholds_exist(self) -> None:
        """Test all veto thresholds are accessible."""
        assert get_v11("veto.regime_confidence_floor") is not None
        assert get_v11("veto.discipline_min") is not None
        assert get_v11("veto.eaf_min") is not None
        assert get_v11("veto.cluster_exposure_max") is not None

    def test_selectivity_thresholds_exist(self) -> None:
        """Test all selectivity thresholds are accessible."""
        assert get_v11("selectivity.score_min") is not None
        assert get_v11("selectivity.monte_carlo_win_min") is not None
        assert get_v11("selectivity.posterior_min") is not None
        assert get_v11("selectivity.mc_pf_min") is not None

    def test_scoring_weights_exist(self) -> None:
        """Test scoring weights are accessible."""
        weights = get_v11("scoring")
        assert isinstance(weights, dict)
        assert "regime_confidence" in weights
        assert "liquidity_sweep" in weights
        assert "exhaustion_confidence" in weights
