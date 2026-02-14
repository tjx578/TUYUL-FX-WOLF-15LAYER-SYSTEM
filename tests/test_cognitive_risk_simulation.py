from engines import CognitiveRiskSimulation


def test_simulate_requires_minimum_returns() -> None:
    simulator = CognitiveRiskSimulation(seed=123)
    result = simulator.simulate({"returns": [0.01, -0.01, 0.02, -0.02]})

    assert result.robustness_estimate == 0.0
    assert result.tail_risk_flag is True
    assert "Insufficient return data" in result.notes


def test_simulate_produces_expected_keys() -> None:
    returns = [0.004, -0.003, 0.002, 0.005, -0.001, 0.003, -0.002, 0.001]
    simulator = CognitiveRiskSimulation(iterations=200, seed=7)

    result = simulator.simulate(
        {
            "returns": returns,
            "stop_loss_pct": 0.02,
            "account_balance": 5000,
        }
    )
    exported = simulator.export(result)

    assert 0.0 <= result.robustness_estimate <= 1.0
    assert isinstance(result.tail_risk_flag, bool)
    assert "iterations" in result.details
    assert set(exported.keys()) == {
        "robustness_estimate",
        "tail_risk_flag",
        "var_95",
        "cvar_95",
        "max_drawdown_estimate",
        "stress_survival_rate",
        "notes",
        "details",
    }
