from engines import create_engine_suite


def test_create_engine_suite_has_all_engines():
    suite = create_engine_suite()
    assert {
        "coherence",
        "context",
        "risk",
        "momentum",
        "precision",
        "structure",
        "field",
        "probability",
        "advisory",
    }.issubset(suite.keys())


def test_advisory_flags_lockout_conflict():
    suite = create_engine_suite()
    advisory = suite["advisory"]
    summary = advisory.summarize(  # type: ignore[attr-defined]
        field={"valid": True, "field_energy": 0.1, "field_bias": 0.3, "stability_index": 0.6},
        probability={"valid": True, "weighted_probability": 0.75, "uncertainty": 0.2},
        coherence={"gate": "LOCKOUT", "coherence_index": 0.5, "psych_confidence": 0.4},
    )
    assert "HIGH_PROB_BUT_LOCKOUT" in summary.conflict_flags
    assert summary.valid is True
