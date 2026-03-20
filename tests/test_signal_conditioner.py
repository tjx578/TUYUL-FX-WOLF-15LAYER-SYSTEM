from __future__ import annotations

from analysis.signal_conditioner import SignalConditioner


def test_condition_returns_reduces_outlier_noise() -> None:
    conditioner = SignalConditioner.from_config(
        {
            "enabled": True,
            "ema_span": 4,
            "outlier_mad_scale": 4.0,
            "adaptive_sampling": False,
        }
    )
    returns = [0.0012, 0.0011, -0.0009, 0.0010, 0.0250, -0.0011, 0.0013, -0.0010]

    result = conditioner.condition_returns(returns)

    assert len(result.conditioned_returns) == len(returns)
    assert result.realized_volatility < result.raw_volatility
    assert result.noise_ratio > 0.0
    assert 0.0 <= result.microstructure_quality_score <= 1.0


def test_condition_returns_adaptive_sampling_triggers_on_high_noise() -> None:
    conditioner = SignalConditioner.from_config(
        {
            "enabled": True,
            "ema_span": 3,
            "outlier_mad_scale": 2.5,
            "adaptive_sampling": True,
            "high_noise_ratio": 0.2,
            "high_noise_stride": 2,
        }
    )
    returns = [0.0008, 0.0009, -0.0010, 0.0120, -0.0105, 0.0007, -0.0006, 0.0095, -0.0088]

    result = conditioner.condition_returns(returns)

    assert result.sampling_stride == 2
    assert len(result.conditioned_returns) < len(result.raw_returns)


def test_condition_prices_uses_log_returns() -> None:
    conditioner = SignalConditioner()
    prices = [1.1000, 1.1003, 1.1001, 1.1005, 1.1004]

    result = conditioner.condition_prices(prices)

    assert len(result.raw_returns) == len(prices) - 1
    assert len(result.conditioned_returns) > 0
