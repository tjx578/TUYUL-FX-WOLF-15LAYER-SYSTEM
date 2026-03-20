"""Integration tests: Reflex Gate ↔ L12 Verdict Engine.

Verifies that the reflex gate decision correctly influences L12's
constitutional verdict through Gate 10.
"""

from __future__ import annotations

from typing import Any, cast

from constitution.verdict_engine import generate_l12_verdict


def _make_synthesis(
    *,
    reflex_gate: str = "OPEN",
    lot_scale: float = 1.0,
    rqi: float = 0.90,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal synthesis dict with all 10 gates passing by default."""
    synth = {
        "pair": "XAUUSD",
        "layers": {
            "L8_tii_sym": 0.95,
            "L8_integrity_index": 0.98,
            "L7_monte_carlo_win": 0.70,
            "conf12": 0.85,
            "enrichment_score": 0.0,
        },
        "scores": {
            "fta_score": 0.70,
            "wolf_30_point": 25,
        },
        "execution": {
            "rr_ratio": 2.5,
        },
        "propfirm": {
            "compliant": True,
        },
        "risk": {
            "current_drawdown": 2.0,
            "max_drawdown": 5.0,
        },
        "bias": {
            "technical": "BULLISH",
        },
        "system": {
            "latency_ms": 50,
            "reflex_gate": {
                "gate": reflex_gate,
                "lot_scale": lot_scale,
                "rqi": rqi,
                "reason": f"test gate={reflex_gate}",
            },
        },
    }
    if override:
        for key, val in override.items():
            parts = key.split(".")
            d: dict[str, Any] = synth
            for p in parts[:-1]:
                d = cast(dict[str, Any], d[p])
            d[parts[-1]] = val
    return synth


class TestGate10Integration:
    def test_open_gate_all_pass_execute(self) -> None:
        """OPEN reflex gate with all other gates passing → EXECUTE."""
        synth = _make_synthesis(reflex_gate="OPEN", lot_scale=1.0)
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"].startswith("EXECUTE")
        assert verdict["lot_scale"] == 1.0
        assert verdict["gates"]["gate_10_reflex_quality"] == "PASS"

    def test_caution_gate_still_executes(self) -> None:
        """CAUTION passes gate but injects lot_scale=0.5."""
        synth = _make_synthesis(reflex_gate="CAUTION", lot_scale=0.5)
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"].startswith("EXECUTE")
        assert verdict["lot_scale"] == 0.5
        assert verdict["reflex_gate"] == "CAUTION"
        assert verdict["gates"]["gate_10_reflex_quality"] == "PASS"

    def test_lock_gate_blocks_execution(self) -> None:
        """LOCK is a critical fail → NO_TRADE regardless of other gates."""
        synth = _make_synthesis(reflex_gate="LOCK", lot_scale=0.0, rqi=0.40)
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"] == "NO_TRADE"
        assert verdict["lot_scale"] == 0.0
        assert verdict["gates"]["gate_10_reflex_quality"] == "FAIL"

    def test_missing_reflex_gate_defaults_open(self) -> None:
        """If reflex_gate is absent from synthesis, default to OPEN (backward compat)."""
        synth = _make_synthesis()
        del synth["system"]["reflex_gate"]
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"].startswith("EXECUTE")
        assert verdict["lot_scale"] == 1.0
        assert verdict["gates"]["gate_10_reflex_quality"] == "PASS"

    def test_lock_overrides_good_other_gates(self) -> None:
        """Even with 9/9 other gates passing, LOCK blocks trade."""
        synth = _make_synthesis(reflex_gate="LOCK", lot_scale=0.0)
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"] == "NO_TRADE"
        # 9 other gates pass, only gate_10 fails
        assert verdict["gates"]["passed"] == 9

    def test_gate_count_is_10(self) -> None:
        synth = _make_synthesis()
        verdict = generate_l12_verdict(synth)
        assert verdict["gates"]["total"] == 10

    def test_verdict_output_contains_reflex_fields(self) -> None:
        synth = _make_synthesis(reflex_gate="CAUTION", lot_scale=0.5)
        verdict = generate_l12_verdict(synth)
        assert "reflex_gate" in verdict
        assert "lot_scale" in verdict


class TestGate10WithOtherFailures:
    def test_lock_plus_propfirm_fail(self) -> None:
        """Both critical gates fail → still NO_TRADE."""
        synth = _make_synthesis(
            reflex_gate="LOCK",
            lot_scale=0.0,
            override={"propfirm.compliant": False},
        )
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"] == "NO_TRADE"

    def test_open_but_wolf_weak(self) -> None:
        """Reflex OPEN but non-critical gate fails → HOLD."""
        synth = _make_synthesis(
            reflex_gate="OPEN",
            lot_scale=1.0,
            override={"layers.L8_tii_sym": 0.30},
        )
        verdict = generate_l12_verdict(synth)
        assert verdict["verdict"] == "HOLD"
        # lot_scale still 1.0 (reflex is fine, other issue)
        assert verdict["lot_scale"] == 1.0
