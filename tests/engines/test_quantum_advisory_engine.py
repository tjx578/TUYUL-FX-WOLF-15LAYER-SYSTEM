from types import SimpleNamespace

from engines import QuantumAdvisoryEngine


def test_no_inputs_return_insufficient() -> None:
    """Empty engine_outputs -> invalid advisory with error metadata."""
    engine = QuantumAdvisoryEngine()
    result = engine.analyze({})

    assert not result.is_valid
    assert result.confidence == 0.0
    assert result.metadata.get("error") == "no_inputs"


def test_coherence_abort_triggers_abort_action() -> None:
    """When coherence engine reports ABORT, advisory action should be ABORT."""
    engine = QuantumAdvisoryEngine()
    outputs = {
        "field": SimpleNamespace(energy_score=0.5, field_polarity="BULLISH"),
        "probability": SimpleNamespace(confidence=0.7),
        "coherence": SimpleNamespace(
            coherence_score=0.3,
            coherence_verdict="ABORT",
        ),
    }
    result = engine.analyze(outputs, symbol="EURUSD")

    assert result.advisory_action == "ABORT"
    assert any("ABORT" in r for r in result.reasons)


def test_no_direction_consensus_returns_no_trade() -> None:
    """When engines have no directional consensus, action is NO_TRADE."""
    engine = QuantumAdvisoryEngine()
    outputs = {
        "field": SimpleNamespace(energy_score=0.5, field_polarity="NEUTRAL"),
        "momentum": SimpleNamespace(momentum_score=0.5, momentum_bias="NEUTRAL"),
        "structure": SimpleNamespace(structure_score=0.5, structure_bias="NEUTRAL"),
    }
    result = engine.analyze(outputs)

    assert result.direction == "NONE"
    assert result.advisory_action == "NO_TRADE"


def test_advisory_produces_execute_with_strong_scores() -> None:
    """Strong component scores -> EXECUTE advisory action."""
    engine = QuantumAdvisoryEngine()
    outputs = {
        "structure": SimpleNamespace(
            structure_score=0.9, structure_bias="BULLISH", direction="BUY"
        ),
        "momentum": SimpleNamespace(
            momentum_score=0.8, momentum_bias="BULLISH", direction="BUY"
        ),
        "precision": SimpleNamespace(
            precision_score=0.7,
            entry_optimal=1.10,
            stop_loss=1.09,
            tp1=1.12,
            risk_reward_1=2.0,
            direction="BUY",
        ),
        "field": SimpleNamespace(energy_score=0.8, field_polarity="BULLISH"),
        "coherence": SimpleNamespace(
            coherence_score=0.9, coherence_verdict="PASS"
        ),
        "context": SimpleNamespace(
            context_score=0.7, context_verdict="NEUTRAL"
        ),
        "risk_simulation": SimpleNamespace(
            risk_score=0.8, win_probability=0.6
        ),
    }
    result = engine.analyze(outputs, symbol="EURUSD")

    assert result.is_valid
    assert result.wolf_score > 0
    assert result.tii_score > 0
    assert result.frpc_score > 0
    assert result.direction == "BUY"
    assert result.advisory_action == "EXECUTE"
    assert result.suggested_entry == 1.10
    assert result.suggested_sl == 1.09
    assert result.suggested_tp1 == 1.12
    assert result.metadata.get("symbol") == "EURUSD"


def test_advisory_result_has_component_weights() -> None:
    """Advisory result populates per-component weight fields."""
    engine = QuantumAdvisoryEngine()
    outputs = {
        "structure": SimpleNamespace(structure_score=0.6, structure_bias="BULLISH", direction="BUY"),
        "momentum": SimpleNamespace(momentum_score=0.5, momentum_bias="BULLISH"),
        "field": SimpleNamespace(energy_score=0.4, field_polarity="BULLISH"),
    }
    result = engine.analyze(outputs)

    assert result.structure_weight == 0.6
    assert result.momentum_weight == 0.5
    assert result.field_weight == 0.4
    # Missing engines should get 0.0
    assert result.coherence_weight == 0.0
    assert result.context_weight == 0.0
    assert result.risk_sim_weight == 0.0
    assert len(result.warnings) > 0  # warnings about missing engines
