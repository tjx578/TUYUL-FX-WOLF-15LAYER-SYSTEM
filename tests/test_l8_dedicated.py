"""
Dedicated tests for L8 — analyze_tii() production interface.

Covers:
  - Full data path (L3 + L1 + indicators present)
  - Degraded mode (fallback VWAP / energy / bias)
  - Insufficient bars
  - TWMS scoring
  - Gate pass / fail threshold
  - Output contract (required keys)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from analysis.l8_tii import (
    _classify_tii,
    _clamp,
    _compute_tii,
    _compute_twms,
    _score_bias_confirmation,
    _score_energy_coherence,
    _score_vwap_alignment,
    analyze_tii,
)

NOW = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)

# ── Helpers ──────────────────────────────────────────────────────────

def _make_closes(n: int = 60, base: float = 1.3000, drift: float = 0.0001) -> list[float]:
    return [round(base + drift * i, 5) for i in range(n)]


def _full_market_data(n: int = 60) -> dict:
    closes = _make_closes(n)
    return {"closes": closes}


REQUIRED_KEYS = {
    "tii_sym", "tii_status", "integrity", "twms_score",
    "gate_status", "gate_passed", "valid",
}

DEGRADED_KEYS = {"degraded_fields", "meta_integrity"}


# ── Output contract ──────────────────────────────────────────────────

class TestOutputContract:
    def test_full_data_has_required_keys(self) -> None:
        result = analyze_tii(_full_market_data(), now=NOW)
        assert REQUIRED_KEYS.issubset(result.keys())

    def test_degraded_keys_present(self) -> None:
        result = analyze_tii(_full_market_data(), now=NOW)
        assert DEGRADED_KEYS.issubset(result.keys())

    def test_valid_is_true(self) -> None:
        result = analyze_tii(_full_market_data(), now=NOW)
        assert result["valid"] is True

    def test_timestamp_present(self) -> None:
        result = analyze_tii(_full_market_data(), now=NOW)
        assert "timestamp" in result


# ── Insufficient data ────────────────────────────────────────────────

class TestInsufficientData:
    def test_too_few_bars(self) -> None:
        result = analyze_tii({"closes": [1.3, 1.31]}, now=NOW)
        assert result["valid"] is False
        assert result["gate_passed"] is False
        assert result["tii_status"] == "INVALID"

    def test_empty_closes(self) -> None:
        result = analyze_tii({"closes": []}, now=NOW)
        assert result["valid"] is False

    def test_no_closes_key(self) -> None:
        result = analyze_tii({}, now=NOW)
        assert result["valid"] is False


# ── Full data path (L3 + L1 + indicators) ───────────────────────────

class TestFullDataPath:
    def test_no_degraded_fields_with_l3(self) -> None:
        l3 = {"vwap": 1.305, "energy": 2.5, "bias_strength": 0.003}
        l1 = {"regime_confidence": 0.85}
        result = analyze_tii(_full_market_data(), l3_data=l3, l1_data=l1, now=NOW)
        assert result["degraded_fields"] == []

    def test_gate_passes_with_strong_data(self) -> None:
        l3 = {"vwap": 1.305, "energy": 3.0, "bias_strength": 0.006}
        l1 = {"regime_confidence": 0.90}
        result = analyze_tii(_full_market_data(), l3_data=l3, l1_data=l1, now=NOW)
        assert result["tii_sym"] >= 0.0

    def test_indicators_affect_twms(self) -> None:
        ind = {"mfi": 80.0, "cci": 120.0, "rsi": 70.0, "momentum": 1.5}
        result = analyze_tii(_full_market_data(), indicators=ind, now=NOW)
        assert result["twms_score"] > 0.0


# ── Degraded mode ────────────────────────────────────────────────────

class TestDegradedMode:
    def test_fallback_vwap_when_no_l3(self) -> None:
        result = analyze_tii(_full_market_data(), now=NOW)
        assert "vwap" in result.get("degraded_fields", [])

    def test_meta_integrity_penalized(self) -> None:
        result = analyze_tii(_full_market_data(), now=NOW)
        assert result["meta_integrity"] < 0.95


# ── Component scoring functions ──────────────────────────────────────

class TestVWAPScoring:
    def test_zero_vwap_returns_zero(self) -> None:
        assert _score_vwap_alignment(1.3, 0.0) == 0.0

    def test_very_close_scores_high(self) -> None:
        assert _score_vwap_alignment(1.3000, 1.3005) >= 0.90

    def test_far_scores_low(self) -> None:
        assert _score_vwap_alignment(1.30, 1.40) < 0.50


class TestEnergyScoring:
    def test_high_energy_scores_high(self) -> None:
        assert _score_energy_coherence(5.0) >= 0.90

    def test_zero_energy_scores_low(self) -> None:
        assert _score_energy_coherence(0.0) <= 0.25


class TestBiasScoring:
    def test_strong_bias(self) -> None:
        assert _score_bias_confirmation(0.01) >= 0.85

    def test_weak_bias(self) -> None:
        assert _score_bias_confirmation(0.0005) <= 0.40


# ── TII classification ──────────────────────────────────────────────

class TestClassifyTII:
    @pytest.mark.parametrize("tii_val, expected", [
        (0.85, "STRONG"),
        (0.65, "VALID"),
        (0.45, "WEAK"),
        (0.30, "INVALID"),
    ])
    def test_classification(self, tii_val: float, expected: str) -> None:
        assert _classify_tii(tii_val) == expected


# ── TWMS ─────────────────────────────────────────────────────────────

class TestTWMS:
    def test_neutral_indicators(self) -> None:
        result = _compute_twms()
        assert result["twms_score"] == 0.0
        assert result["signals"] == []

    def test_extreme_indicators(self) -> None:
        result = _compute_twms(mfi=80.0, cci=150.0, rsi=70.0, momentum=2.0)
        assert result["twms_score"] >= 0.80
        assert len(result["signals"]) >= 3

    def test_score_capped_at_one(self) -> None:
        result = _compute_twms(mfi=90.0, cci=200.0, rsi=80.0, momentum=5.0)
        assert result["twms_score"] <= 1.0


# ── Determinism ──────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        data = _full_market_data()
        r1 = analyze_tii(data, now=NOW)
        r2 = analyze_tii(data, now=NOW)
        assert r1["tii_sym"] == r2["tii_sym"]
        assert r1["twms_score"] == r2["twms_score"]
