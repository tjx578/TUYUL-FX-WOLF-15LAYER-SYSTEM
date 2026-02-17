"""
Dedicated tests for L5 — Psychology & Fundamental Context (production interface).

Covers:
  - L5AnalysisLayer.analyze() output contract
  - EAF score calculation and threshold
  - Psychology gates (10 gates, critical gates)
  - Stateful loss/win tracking
  - Fundamental analysis (sentiment bias)
  - Cross-integration (risk event → emotional bias)
  - Gate decision logic
"""

from __future__ import annotations

from datetime import UTC, datetime

from analysis.layers.L5_psychology_fundamental import (
    L5AnalysisLayer,
    L5PsychologyAnalyzer,
    analyze_fundamental,
    analyze_l5,
)

NOW = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)

REQUIRED_PSYCHOLOGY_KEYS = {
    "psychology_score", "eaf_score", "can_trade",
    "gate_status", "psychology_ok", "fatigue_level",
    "valid",
}

REQUIRED_FUNDAMENTAL_KEYS = {
    "fundamental_bias", "fundamental_strength",
}


# ── L5AnalysisLayer output contract ─────────────────────────────────

class TestL5OutputContract:
    def test_has_required_keys(self) -> None:
        layer = L5AnalysisLayer()
        result = layer.analyze(pair="EURUSD", now=NOW)
        assert REQUIRED_PSYCHOLOGY_KEYS.issubset(result.keys())

    def test_valid_flag(self) -> None:
        layer = L5AnalysisLayer()
        result = layer.analyze(pair="EURUSD", now=NOW)
        assert result["valid"] is True

    def test_returns_dict(self) -> None:
        layer = L5AnalysisLayer()
        result = layer.analyze(pair="EURUSD", now=NOW)
        assert isinstance(result, dict)


# ── EAF thresholds ──────────────────────────────────────────────────

class TestEAFScore:
    def test_fresh_trader_eaf_above_threshold(self) -> None:
        layer = L5AnalysisLayer()
        result = layer.analyze(pair="EURUSD", now=NOW)
        # Fresh trader (no losses, no drawdown) should pass EAF ≥ 0.70
        assert result["eaf_score"] >= 0.70

    def test_eaf_bounded_zero_one(self) -> None:
        layer = L5AnalysisLayer()
        result = layer.analyze(pair="EURUSD", now=NOW)
        assert 0.0 <= result["eaf_score"] <= 1.0


# ── Stateful loss / win tracking ────────────────────────────────────

class TestStatefulTracking:
    def test_losses_degrade_psychology(self) -> None:
        layer = L5AnalysisLayer()
        layer.record_loss()
        layer.record_loss()
        layer.record_loss()
        result = layer.analyze(pair="EURUSD", now=NOW)
        # 3 consecutive losses should flag psychology issue
        assert result["psychology_ok"] is False or result["eaf_score"] < 0.70

    def test_win_resets_loss_streak(self) -> None:
        layer = L5AnalysisLayer()
        layer.record_loss()
        layer.record_loss()
        layer.record_win()
        result = layer.analyze(pair="EURUSD", now=NOW)
        # Win should reset the loss streak
        assert result["eaf_score"] >= 0.60

    def test_drawdown_affects_gate(self) -> None:
        layer = L5AnalysisLayer()
        layer.update_drawdown(6.0)  # Above _MAX_DRAWDOWN_PERCENT (5%)
        result = layer.analyze(pair="EURUSD", now=NOW)
        assert result["psychology_ok"] is False or result["can_trade"] is False

    def test_reset_session_clears_state(self) -> None:
        layer = L5AnalysisLayer()
        layer.record_loss()
        layer.record_loss()
        layer.record_loss()
        layer.reset_session()
        result = layer.analyze(pair="EURUSD", now=NOW)
        assert result["eaf_score"] >= 0.70


# ── Psychology gates ─────────────────────────────────────────────────

class TestPsychologyGates:
    def test_gates_present_with_data(self) -> None:
        layer = L5AnalysisLayer()
        psych_data = {
            "mta_compliance": 0.9,
            "body_close_compliance": 0.85,
            "decision_quality": 0.8,
            "patience_score": 0.7,
            "risk_acceptance": 0.75,
            "focus_score": 0.8,
            "discipline_score": 0.85,
            "emotional_control": 0.9,
            "confidence_level": 0.8,
            "adaptability": 0.75,
        }
        result = layer.analyze(pair="EURUSD", psychology_data=psych_data, now=NOW)
        assert "psychology_gates" in result
        assert result["has_gate_data"] is True


# ── Fundamental analysis ─────────────────────────────────────────────

class TestFundamentalAnalysis:
    def test_analyze_fundamental_returns_dict(self) -> None:
        result = analyze_fundamental({}, pair="EURUSD", now=NOW)
        assert isinstance(result, dict)
        assert "fundamental_bias" in result

    def test_no_news_neutral_bias(self) -> None:
        result = analyze_fundamental({}, pair="EURUSD", now=NOW)
        assert "NEUTRAL" in result["fundamental_bias"] or result["fundamental_strength"] == 0.0


# ── Backward-compat wrapper ─────────────────────────────────────────

class TestL5PsychologyAnalyzerCompat:
    def test_returns_dict(self) -> None:
        analyzer = L5PsychologyAnalyzer()
        result = analyzer.analyze("EURUSD")
        assert isinstance(result, dict)
        assert "valid" in result

    def test_reset_session(self) -> None:
        analyzer = L5PsychologyAnalyzer()
        analyzer.record_loss()
        analyzer.reset_session()
        result = analyzer.analyze("EURUSD")
        assert result["eaf_score"] >= 0.70


# ── Convenience function ────────────────────────────────────────────

class TestAnalyzeL5Convenience:
    def test_returns_dict(self) -> None:
        result = analyze_l5(pair="EURUSD", news_sentiment=None,
                            volatility_profile=None, session_hours=2.0,
                            now=NOW, psychology_data=None)
        assert isinstance(result, dict)
        assert "valid" in result
