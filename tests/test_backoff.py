"""Tests for infrastructure/backoff.py — exponential backoff with jitter."""

import pytest

from infrastructure.backoff import BackoffConfig, ExponentialBackoff


class TestBackoffConfig:
    def test_defaults(self) -> None:
        cfg = BackoffConfig()
        assert cfg.initial == 1.0
        assert cfg.maximum == 60.0
        assert cfg.factor == 2.0
        assert cfg.jitter == 0.25

    def test_invalid_initial(self) -> None:
        with pytest.raises(ValueError, match="initial must be positive"):
            BackoffConfig(initial=0)

    def test_maximum_less_than_initial(self) -> None:
        with pytest.raises(ValueError, match="maximum.*must be >= initial"):
            BackoffConfig(initial=10.0, maximum=5.0)

    def test_invalid_factor(self) -> None:
        with pytest.raises(ValueError, match="factor must be >= 1.0"):
            BackoffConfig(factor=0.5)

    def test_invalid_jitter(self) -> None:
        with pytest.raises(ValueError, match="jitter must be in"):
            BackoffConfig(jitter=1.5)


class TestExponentialBackoff:
    def test_exponential_growth(self) -> None:
        """Delays should grow exponentially (ignoring jitter)."""
        cfg = BackoffConfig(initial=1.0, maximum=60.0, factor=2.0, jitter=0.0)
        backoff = ExponentialBackoff(cfg)

        d1 = backoff.next_delay()
        d2 = backoff.next_delay()
        d3 = backoff.next_delay()
        d4 = backoff.next_delay()

        assert d1 == pytest.approx(1.0)
        assert d2 == pytest.approx(2.0)
        assert d3 == pytest.approx(4.0)
        assert d4 == pytest.approx(8.0)

    def test_caps_at_maximum(self) -> None:
        cfg = BackoffConfig(initial=1.0, maximum=5.0, factor=2.0, jitter=0.0)
        backoff = ExponentialBackoff(cfg)

        for _ in range(20):
            delay = backoff.next_delay()

        assert delay <= 5.0 # pyright: ignore[reportPossiblyUnboundVariable]

    def test_jitter_adds_variance(self) -> None:
        """With jitter, consecutive same-attempt delays should vary."""
        cfg = BackoffConfig(initial=10.0, maximum=60.0, factor=1.0, jitter=0.25)

        delays = set()
        for _ in range(20):
            backoff = ExponentialBackoff(cfg)
            delays.add(round(backoff.next_delay(), 4))

        # With 25% jitter on base 10.0, we expect values in [7.5, 12.5]
        assert len(delays) > 1, "Jitter should produce varying delays"
        for d in delays:
            assert 7.0 <= d <= 13.0

    def test_reset(self) -> None:
        cfg = BackoffConfig(initial=1.0, maximum=60.0, factor=2.0, jitter=0.0)
        backoff = ExponentialBackoff(cfg)

        backoff.next_delay()  # 1
        backoff.next_delay()  # 2
        backoff.next_delay()  # 4
        assert backoff.attempt == 3

        backoff.reset()
        assert backoff.attempt == 0
        assert backoff.next_delay() == pytest.approx(1.0)

    def test_minimum_delay_with_jitter(self) -> None:
        """Delay should never go below 0.1s even with negative jitter."""
        cfg = BackoffConfig(initial=0.2, maximum=60.0, factor=1.0, jitter=0.99)
        ExponentialBackoff(cfg)

        for _ in range(50):
            backoff_fresh = ExponentialBackoff(cfg)
            delay = backoff_fresh.next_delay()
            assert delay >= 0.1


class TestBackoffSequence:
    """Verify the full sequence matches expected pattern."""

    def test_full_sequence_no_jitter(self) -> None:
        cfg = BackoffConfig(initial=1.0, maximum=30.0, factor=2.0, jitter=0.0)
        backoff = ExponentialBackoff(cfg)

        expected = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
        for exp in expected:
            assert backoff.next_delay() == pytest.approx(exp)

    def test_factor_3(self) -> None:
        cfg = BackoffConfig(initial=0.5, maximum=100.0, factor=3.0, jitter=0.0)
        backoff = ExponentialBackoff(cfg)

        expected = [0.5, 1.5, 4.5, 13.5, 40.5, 100.0]
        for exp in expected:
            assert backoff.next_delay() == pytest.approx(exp)
