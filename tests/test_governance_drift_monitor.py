"""Tests for governance drift monitor."""

from __future__ import annotations

import math

import pytest

from governance.drift_monitor import (
    DriftMonitor,
    DriftThresholds,
    FeatureBaseline,
    _safe_kl_divergence,
    _wasserstein_1d,
    extract_features,
)


class TestMathHelpers:
    def test_kl_identical_distributions(self) -> None:
        """KL(P||P) = 0 for identical Gaussians."""
        kl = _safe_kl_divergence(1.0, 1.0, 1.0, 1.0)
        assert abs(kl) < 1e-10

    def test_kl_different_means(self) -> None:
        """KL should be positive for different means."""
        kl = _safe_kl_divergence(0.0, 1.0, 2.0, 1.0)
        assert kl > 0

    def test_kl_zero_variance(self) -> None:
        """Degenerate case: zero variance returns 0."""
        kl = _safe_kl_divergence(0.0, 0.0, 1.0, 1.0)
        assert kl == 0.0

    def test_wasserstein_identical(self) -> None:
        w = _wasserstein_1d(1.0, 1.0, 1.0, 1.0)
        assert abs(w) < 1e-10

    def test_wasserstein_different_means(self) -> None:
        w = _wasserstein_1d(0.0, 1.0, 3.0, 1.0)
        assert w == pytest.approx(3.0, abs=0.01)

    def test_wasserstein_different_stds(self) -> None:
        w = _wasserstein_1d(0.0, 1.0, 0.0, 2.0)
        expected = abs(1.0 - 2.0) * math.sqrt(2.0 / math.pi)
        assert w == pytest.approx(expected, abs=0.01)


class TestFeatureBaseline:
    def test_welford_mean(self) -> None:
        fb = FeatureBaseline()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            fb.update(v)
        assert fb.mean == pytest.approx(3.0)
        assert fb.count == 5

    def test_welford_std(self) -> None:
        fb = FeatureBaseline()
        for v in [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]:
            fb.update(v)
        assert fb.std == pytest.approx(2.138, abs=0.01)

    def test_roundtrip_dict(self) -> None:
        fb = FeatureBaseline()
        fb.update(1.0)
        fb.update(2.0)
        d = fb.to_dict()
        fb2 = FeatureBaseline.from_dict(d)
        assert fb2.count == fb.count
        assert fb2.mean == pytest.approx(fb.mean)


class TestExtractFeatures:
    def test_basic_extraction(self) -> None:
        snap = {
            "regime_state": {"regime": 1, "vix": 22.5},
            "volatility_regime": "HIGH",
            "session_state": {"multiplier": 1.2},
            "news_pressure_vector": {"impact": 0.5},
            "signal_stack": [{"a": 1}, {"b": 2}],
        }
        features = extract_features(snap)
        assert features["regime_state_macro"] == 1.0
        assert features["regime_state_vix"] == 22.5
        assert features["volatility_regime_ordinal"] == 2.0
        assert features["session_multiplier"] == 1.2
        assert features["news_pressure_impact"] == 0.5
        assert features["signal_stack_depth"] == 2.0

    def test_empty_snapshot(self) -> None:
        features = extract_features({})
        # volatility_regime defaults to NORMAL (ordinal 1.0), session_multiplier defaults to 1.0
        assert features["regime_state_macro"] == 0.0
        assert features["regime_state_vix"] == 0.0
        assert features["news_pressure_impact"] == 0.0
        assert features["signal_stack_depth"] == 0.0


class TestDriftMonitor:
    def test_no_baseline_returns_stable(self) -> None:
        mon = DriftMonitor(redis_client=None)
        report = mon.evaluate({})
        assert report.severity == "STABLE"
        assert report.should_freeze is False

    def test_capture_and_evaluate_stable(self, tmp_path, monkeypatch) -> None:
        import governance.drift_monitor as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        mon = DriftMonitor(redis_client=None, window_size=200)

        # Capture 20 baseline snapshots (all similar)
        for _ in range(20):
            mon.capture_baseline(
                {
                    "regime_state": {"regime": 1, "vix": 20.0},
                    "volatility_regime": "NORMAL",
                    "session_state": {"multiplier": 1.0},
                    "news_pressure_vector": {"impact": 0.1},
                    "signal_stack": [],
                }
            )

        # Observe 10 live snapshots (also similar)
        for _ in range(10):
            mon.observe(
                {
                    "regime_state": {"regime": 1, "vix": 20.5},
                    "volatility_regime": "NORMAL",
                    "session_state": {"multiplier": 1.0},
                    "news_pressure_vector": {"impact": 0.12},
                    "signal_stack": [],
                }
            )

        report = mon.evaluate()
        assert report.severity == "STABLE"
        assert report.should_freeze is False

    def test_detect_drift(self, tmp_path, monkeypatch) -> None:
        import governance.drift_monitor as mod

        monkeypatch.setattr(mod, "_ARTIFACT_DIR", tmp_path)

        mon = DriftMonitor(
            redis_client=None,
            thresholds=DriftThresholds(kl_warning=0.05, kl_critical=0.10),
            window_size=200,
        )

        # Baseline: regime 1 (trending)
        for _ in range(30):
            mon.capture_baseline(
                {
                    "regime_state": {"regime": 1, "vix": 15.0},
                    "volatility_regime": "LOW",
                    "session_state": {"multiplier": 1.0},
                    "news_pressure_vector": {"impact": 0.0},
                    "signal_stack": [],
                }
            )

        # Live: regime shift to 2 (range), high VIX
        for _ in range(15):
            mon.observe(
                {
                    "regime_state": {"regime": 2, "vix": 35.0},
                    "volatility_regime": "EXTREME",
                    "session_state": {"multiplier": 0.5},
                    "news_pressure_vector": {"impact": 0.8},
                    "signal_stack": [{"x": 1}] * 10,
                }
            )

        report = mon.evaluate()
        assert report.drifted_features > 0
        assert report.severity in ("WARNING", "CRITICAL")

    def test_has_baseline(self) -> None:
        mon = DriftMonitor(redis_client=None)
        assert mon.has_baseline() is False

        for _ in range(15):
            mon.capture_baseline({"regime_state": {"regime": 1, "vix": 20}})
        assert mon.has_baseline() is True
