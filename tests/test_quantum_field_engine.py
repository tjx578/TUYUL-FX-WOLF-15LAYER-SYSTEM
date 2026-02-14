from engines import QuantumFieldEngine


def test_quantum_field_engine_rejects_short_input() -> None:
    engine = QuantumFieldEngine()

    result = engine.evaluate([1.0, 2.0, 3.0, 4.0])

    assert result["valid"] is False
    assert result["reason"] == "insufficient_price_data"


def test_quantum_field_engine_emits_metrics() -> None:
    engine = QuantumFieldEngine(energy_window=5, bias_window=10, drift_window=4)
    prices = [100.0, 101.0, 102.0, 103.0, 102.5, 103.2, 104.0, 104.8, 105.5, 106.0]
    volumes = [1000, 1200, 900, 1500, 1300, 1250, 1400, 1600, 1700, 1800]

    result = engine.evaluate(prices, volumes)

    assert result["valid"] is True
    assert result["data_points"] == len(prices)
    assert "field_energy" in result
    assert "vwap_strength" in result
    assert 0.0 <= result["stability_index"] <= 1.0
