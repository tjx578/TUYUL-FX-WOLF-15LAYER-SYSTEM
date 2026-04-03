"""Integration tests for legacy FTA pipeline integration.

Validates:
- LegacyFTAEnricher returns neutral when no data loaded
- LegacyFTAEnricher produces correct advisory hint when data present
- blend_confidence formula correctness
- Synthesis builder includes legacy_fta block
- Legacy FTA does NOT override L12 verdict (advisory-only boundary)
- Confidence blend does not exceed constitutional bounds
"""

from __future__ import annotations

from typing import Any

import pytest

from analysis.legacy_fta.contracts import LegacyCurrencyScore
from engines.legacy_fta_enricher import LegacyFTAEnricher, blend_confidence

# ═══════════════════════════════════════════════════════════════════
# §1  ENRICHER — NEUTRAL DEFAULT
# ═══════════════════════════════════════════════════════════════════


class TestLegacyFTAEnricherNeutral:
    def test_no_data_returns_neutral(self):
        enricher = LegacyFTAEnricher()
        result = enricher.run("EURUSD")
        assert result["legacy_fta_present"] is False
        assert result["confidence_hint"] == 0.0
        assert result["trade_band"] == "NONE"
        assert result["direction"] == "HOLD"

    def test_partial_data_returns_neutral(self):
        enricher = LegacyFTAEnricher()
        enricher.set_currency_score(LegacyCurrencyScore("EUR", 35.0, 7.0, 7.0, 7.0, 7.0, 7.0))
        # Only base, no quote → neutral
        result = enricher.run("EURUSD")
        assert result["legacy_fta_present"] is False

    def test_clear_removes_data(self):
        enricher = LegacyFTAEnricher()
        enricher.set_currency_score(LegacyCurrencyScore("EUR", 35.0, 7.0, 7.0, 7.0, 7.0, 7.0))
        enricher.clear()
        result = enricher.run("EURUSD")
        assert result["legacy_fta_present"] is False


# ═══════════════════════════════════════════════════════════════════
# §2  ENRICHER — WITH DATA
# ═══════════════════════════════════════════════════════════════════


def _seeded_enricher() -> LegacyFTAEnricher:
    enricher = LegacyFTAEnricher()
    enricher.set_currency_scores(
        [
            LegacyCurrencyScore("AUD", 37.0, 7.0, 6.0, 8.0, 7.0, 9.0),
            LegacyCurrencyScore("CAD", 18.0, 4.0, 3.0, 5.0, 3.0, 3.0),
        ]
    )
    return enricher


class TestLegacyFTAEnricherWithData:
    def test_audcad_present(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUDCAD", fta_score_100=91.4, technical_score_100=86.0)
        assert result["legacy_fta_present"] is True

    def test_audcad_direction(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUDCAD", fta_score_100=91.4)
        assert result["direction"] == "BUY"

    def test_audcad_confidence_hint(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUDCAD", fta_score_100=91.4)
        expected = 0.70 * 0.914 + 0.30 * (19.0 / 30.0)
        assert result["confidence_hint"] == pytest.approx(expected, abs=1e-3)

    def test_pair_format_slash(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUD/CAD", fta_score_100=91.4)
        assert result["legacy_fta_present"] is True

    def test_pair_format_underscore(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUD_CAD", fta_score_100=91.4)
        assert result["legacy_fta_present"] is True

    def test_unknown_pair_neutral(self):
        enricher = _seeded_enricher()
        result = enricher.run("EURUSD")
        assert result["legacy_fta_present"] is False


# ═══════════════════════════════════════════════════════════════════
# §3  CONFIDENCE BLENDING
# ═══════════════════════════════════════════════════════════════════


class TestBlendConfidence:
    def test_default_weights(self):
        result = blend_confidence(0.78, 0.8298)
        expected = 0.85 * 0.78 + 0.15 * 0.8298
        assert result == pytest.approx(expected, abs=1e-4)

    def test_borderline_upgrade(self):
        """Borderline repo confidence (0.74) boosted past 0.75 threshold."""
        result = blend_confidence(0.74, 0.8298)
        assert result == pytest.approx(0.85 * 0.74 + 0.15 * 0.8298, abs=1e-4)
        assert result > 0.75  # bumped into HIGH band

    def test_strong_repo_minimal_change(self):
        """Strong repo confidence barely affected."""
        repo = 0.90
        result = blend_confidence(repo, 0.50)
        assert result == pytest.approx(0.85 * 0.90 + 0.15 * 0.50, abs=1e-4)
        assert abs(result - repo) < 0.07  # max 15% weight shift

    def test_zero_legacy_no_effect(self):
        result = blend_confidence(0.78, 0.0)
        assert result == pytest.approx(0.85 * 0.78, abs=1e-4)

    def test_clamped_upper(self):
        result = blend_confidence(1.0, 1.0)
        assert result <= 1.0

    def test_clamped_lower(self):
        result = blend_confidence(0.0, 0.0)
        assert result >= 0.0

    def test_custom_weights(self):
        result = blend_confidence(0.70, 0.90, weight_repo=0.90, weight_legacy=0.10)
        expected = 0.90 * 0.70 + 0.10 * 0.90
        assert result == pytest.approx(expected, abs=1e-4)


# ═══════════════════════════════════════════════════════════════════
# §4  SYNTHESIS BUILDER — LEGACY FTA BLOCK
# ═══════════════════════════════════════════════════════════════════


class TestSynthesisLegacyFTABlock:
    """Validate legacy_fta is correctly injected into synthesis."""

    @staticmethod
    def _minimal_layer_results(legacy_fta: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build minimal layer_results for build_l12_synthesis."""
        lr: dict[str, Any] = {
            "L1": {"valid": True, "regime": "TREND", "regime_confidence": 0.8, "volatility_level": "NORMAL"},
            "L2": {"valid": True, "reflex_coherence": 0.7, "conf12": 0.65, "frpc_state": "SYNC"},
            "L3": {"valid": True, "trend": "BULLISH", "atr": 0.001, "atr_mean_20": 0.001},
            "L4": {
                "technical_score": 75,
                "wolf_30_point": {"total": 22, "f_score": 6, "t_score": 7, "fta_score": 5.0, "exec_score": 4},
            },
            "L5": {"psychology_score": 70, "eaf_score": 0.8},
            "L6": {"risk_ok": True, "propfirm_compliant": True},
            "L7": {"win_probability": 55.0, "bayesian_posterior": 0.6},
            "L8": {"tii_sym": 0.8, "integrity": 0.75, "twms_score": 0.7},
            "L9": {"confidence": 0.8},
            "L10": {
                "fta_score": 78.0,
                "fta_multiplier": 1.0,
                "position_ok": True,
                "lot_size": 0.01,
                "adjusted_risk_pct": 1.0,
                "risk_amount": 100.0,
            },
            "L11": {
                "valid": True,
                "entry_price": 1.085,
                "stop_loss": 1.080,
                "take_profit_1": 1.095,
                "rr": 2.0,
                "battle_strategy": "SHADOW_STRIKE",
            },
            "macro_vix_state": {"regime_state": 1, "risk_multiplier": 1.0},
        }
        if legacy_fta is not None:
            lr["legacy_fta"] = legacy_fta
        return lr

    def test_synthesis_has_legacy_fta_block_when_present(self):
        from pipeline.phases.synthesis import build_l12_synthesis

        legacy = {
            "base_score_50": 37.0,
            "quote_score_50": 18.0,
            "pair_gap_points": 19.0,
            "pair_gap_norm": 0.6333,
            "technical_score_100": 86.0,
            "fta_score_100": 91.4,
            "fta_norm": 0.914,
            "confidence_hint": 0.8298,
            "trade_band": "HIGH",
            "direction": "BUY",
            "fundamental_score_claimed_100": 95.0,
            "fundamental_score_calibrated_100": 63.33,
            "legacy_fta_present": True,
        }
        synthesis = build_l12_synthesis(self._minimal_layer_results(legacy), "AUDCAD")
        assert "legacy_fta" in synthesis
        assert synthesis["legacy_fta"]["legacy_fta_present"] is True
        assert synthesis["legacy_fta"]["confidence_hint"] == pytest.approx(0.8298, abs=1e-3)
        assert synthesis["legacy_fta"]["trade_band"] == "HIGH"

    def test_synthesis_has_neutral_legacy_fta_when_absent(self):
        from pipeline.phases.synthesis import build_l12_synthesis

        synthesis = build_l12_synthesis(self._minimal_layer_results(), "EURUSD")
        assert "legacy_fta" in synthesis
        assert synthesis["legacy_fta"]["legacy_fta_present"] is False
        assert synthesis["legacy_fta"]["confidence_hint"] == 0.0

    def test_legacy_fta_does_not_affect_fta_score(self):
        """Synthesis fta_score must come from L10, not legacy block."""
        from pipeline.phases.synthesis import build_l12_synthesis

        legacy = {
            "fta_score_100": 91.4,
            "fta_norm": 0.914,
            "confidence_hint": 0.8298,
            "legacy_fta_present": True,
        }
        synthesis = build_l12_synthesis(self._minimal_layer_results(legacy), "AUDCAD")
        # scores.fta_score must be from L10 (78.0), not legacy's 91.4
        assert synthesis["scores"]["fta_score"] == pytest.approx(78.0)


# ═══════════════════════════════════════════════════════════════════
# §5  AUTHORITY BOUNDARY — L12 NOT OVERRIDDEN
# ═══════════════════════════════════════════════════════════════════


class TestLegacyFTAAuthorityBoundary:
    """Legacy FTA must never act as an execution authority."""

    def test_enricher_has_no_verdict_field(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUDCAD", fta_score_100=91.4)
        assert "verdict" not in result
        assert "trade_allowed" not in result
        assert "execute" not in result

    def test_enricher_has_no_lot_size(self):
        enricher = _seeded_enricher()
        result = enricher.run("AUDCAD", fta_score_100=91.4)
        assert "lot_size" not in result
        assert "risk_amount" not in result

    def test_blend_cannot_exceed_one(self):
        """Even with maximum inputs, blend stays ≤ 1.0."""
        result = blend_confidence(1.5, 2.0)  # deliberately oversized inputs
        assert result <= 1.0

    def test_blend_cannot_go_negative(self):
        result = blend_confidence(-0.5, -0.5)
        assert result >= 0.0
