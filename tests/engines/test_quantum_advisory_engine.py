from engines import QuantumAdvisoryEngine


def test_invalid_inputs_return_insufficient() -> None:
    engine = QuantumAdvisoryEngine()
    summary = engine.summarize(field={"valid": False}, probability={"valid": True})

    assert not summary.valid
    assert summary.signal.value == "INSUFFICIENT"
    assert summary.conflict_flags == ["INVALID_CORE_INPUTS"]


def test_conflict_detection_with_lockout() -> None:
    engine = QuantumAdvisoryEngine()
    summary = engine.summarize(
        field={
            "valid": True,
            "field_energy": 0.15,
            "field_bias": 0.2,
            "stability_index": 0.64,
        },
        probability={"valid": True, "weighted_probability": 0.75, "uncertainty": 0.24},
        coherence={"gate": "LOCKOUT", "coherence_index": 0.68, "psych_confidence": 0.7},
        context={"market_regime": "RISK_ON"},
        momentum={"momentum_direction": 0.7, "phase": "EXPANSION"},
        structure={"mtf_alignment": 1.0, "divergence_present": False},
    )

    assert summary.valid
    assert "HIGH_PROB_BUT_LOCKOUT" in summary.conflict_flags
    assert summary.signal.value in {
        "MODERATE_CONTEXT",
        "WEAK_CONTEXT",
        "INSUFFICIENT",
        "CONFLICTED",
    }


def test_export_serializable_payload() -> None:
    engine = QuantumAdvisoryEngine()
    summary = engine.summarize(
        field={"valid": True, "field_energy": 0.1, "field_bias": 0.1, "stability_index": 0.9},
        probability={"valid": True, "weighted_probability": 0.8, "uncertainty": 0.1},
    )
    payload = engine.export(summary)

    assert payload["valid"] is True
    assert isinstance(payload["signal"], str)
    assert isinstance(payload["details"]["timestamp"], str)
