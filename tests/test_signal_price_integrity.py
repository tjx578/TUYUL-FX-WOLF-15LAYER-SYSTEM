from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analysis.signal_price_integrity import (
    PRICE_CONTEXT_OUT_OF_RANGE,
    PRICE_CONTEXT_STALE,
    ObservedPrice,
    ObservedPriceRange,
    PriceIntegrityPolicy,
    ReferencePriceLevels,
    SignalPriceContext,
    validate_signal_price_integrity,
)

NOW = datetime(2026, 7, 10, 8, 15, 5, tzinfo=UTC)


def _context(
    *,
    bid: float = 200.661,
    ask: float = 200.663,
    mid: float = 200.662,
    observed_at: datetime | None = None,
    range_low: float = 200.640,
    range_high: float = 200.673,
) -> SignalPriceContext:
    return SignalPriceContext(
        symbol="chfjpy",
        observed=ObservedPrice(
            bid=bid,
            ask=ask,
            mid=mid,
            observed_at=observed_at or NOW,
        ),
        market_range=ObservedPriceRange(low=range_low, high=range_high),
        references=ReferencePriceLevels(
            support=200.640,
            resistance=200.7375,
            entry_zone_low=200.721,
            entry_zone_high=200.735,
        ),
    )


def test_canonical_signal_price_comes_from_observed_mid_not_reference_level():
    result = validate_signal_price_integrity(_context(), evaluated_at=NOW)

    assert result.valid is True
    assert result.reason is None
    assert result.signal_valid_price == 200.662
    assert result.references.resistance == 200.7375

    payload = result.to_dict()
    assert payload["observed"]["mid"] == 200.662
    assert payload["references"]["resistance"] == 200.7375


def test_stale_observed_quote_is_rejected():
    result = validate_signal_price_integrity(
        _context(observed_at=NOW - timedelta(seconds=5.001)),
        evaluated_at=NOW,
        policy=PriceIntegrityPolicy(max_quote_age_seconds=5.0),
    )

    assert result.valid is False
    assert result.reason == PRICE_CONTEXT_STALE
    assert result.signal_valid_price is None
    assert result.quote_age_seconds == pytest.approx(5.001)


def test_quote_too_far_in_the_future_is_rejected_as_stale_context():
    result = validate_signal_price_integrity(
        _context(observed_at=NOW + timedelta(seconds=1.001)),
        evaluated_at=NOW,
        policy=PriceIntegrityPolicy(max_future_skew_seconds=1.0),
    )

    assert result.valid is False
    assert result.reason == PRICE_CONTEXT_STALE


def test_midpoint_outside_candle_range_plus_spread_is_rejected():
    result = validate_signal_price_integrity(
        _context(bid=200.7365, ask=200.7385, mid=200.7375),
        evaluated_at=NOW,
    )

    assert result.valid is False
    assert result.reason == PRICE_CONTEXT_OUT_OF_RANGE
    assert result.signal_valid_price is None
    assert result.allowed_range_high == pytest.approx(200.675)


@pytest.mark.parametrize(
    ("bid", "ask", "mid"),
    [
        (200.663, 200.661, 200.662),
        (200.661, 200.663, 200.665),
        (float("nan"), 200.663, 200.662),
    ],
)
def test_malformed_observed_quote_is_out_of_range(bid: float, ask: float, mid: float):
    result = validate_signal_price_integrity(
        _context(bid=bid, ask=ask, mid=mid),
        evaluated_at=NOW,
    )

    assert result.valid is False
    assert result.reason == PRICE_CONTEXT_OUT_OF_RANGE


def test_spread_is_included_in_allowed_candle_range_by_default():
    result = validate_signal_price_integrity(
        _context(
            bid=200.672,
            ask=200.676,
            mid=200.674,
            range_high=200.673,
        ),
        evaluated_at=NOW,
    )

    assert result.valid is True
    assert result.allowed_range_high == pytest.approx(200.677)


def test_naive_timestamps_are_rejected_instead_of_assuming_timezone():
    naive = NOW.replace(tzinfo=None)

    with pytest.raises(ValueError, match="observed_at must be a timezone-aware datetime"):
        validate_signal_price_integrity(_context(observed_at=naive), evaluated_at=NOW)


def test_negative_policy_tolerance_is_rejected():
    with pytest.raises(ValueError, match="finite and non-negative"):
        validate_signal_price_integrity(
            _context(),
            evaluated_at=NOW,
            policy=PriceIntegrityPolicy(range_buffer=-0.001),
        )
