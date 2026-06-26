from __future__ import annotations

from analysis.direction_conflict_resolver import resolve_direction_conflict


def test_conflict_resolver_blocks_counter_when_basket_supports_raw_direction():
    result = resolve_direction_conflict(
        symbol="USDCAD",
        raw_direction="BUY",
        candidate_direction="SELL",
        currency_scores={"USD": 0.72, "CAD": -0.38},
    )

    assert result.direction_conflict is True
    assert result.counter_direction_allowed is False
    assert result.raw_direction_status == "SUPPORTS_RAW_DIRECTION"
    assert result.candidate_direction_status == "REJECTS_COUNTER_DIRECTION"
    assert result.counter_direction_block_reason == "BASKET_SUPPORTS_RAW_DIRECTION"
    assert result.action == "WAIT_RAW_CONTINUATION_RETEST"


def test_conflict_resolver_allows_counter_when_reversal_is_confirmed():
    result = resolve_direction_conflict(
        symbol="USDCAD",
        raw_direction="BUY",
        candidate_direction="SELL",
        currency_scores={"USD": 0.72, "CAD": -0.38},
        market_context={"m15_rejection_from_resistance": True},
    )

    assert result.direction_conflict is True
    assert result.counter_direction_allowed is True
    assert result.action == "ALLOW_COUNTER_WATCH_CONFIRMED_REVERSAL"


def test_conflict_resolver_marks_low_differential_without_blocking():
    result = resolve_direction_conflict(
        symbol="AUDNZD",
        raw_direction="BUY",
        candidate_direction="SELL",
        currency_scores={"AUD": 0.05, "NZD": 0.01},
    )

    assert result.direction_conflict is True
    assert result.counter_direction_allowed is True
    assert result.raw_direction_status == "NEUTRAL_LOW_DIFFERENTIAL"
    assert result.action == "ALLOW_COUNTER_WATCH_LOW_PRIORITY"
