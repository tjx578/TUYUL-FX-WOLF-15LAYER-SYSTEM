from news.pair_mapper import (
    affected_pairs_for_currencies,
    affected_pairs_for_currency,
    symbol_is_affected,
)


def test_affected_pairs_for_currency_usd_contains_major() -> None:
    pairs = affected_pairs_for_currency("USD")
    assert "EURUSD" in pairs
    assert "USDJPY" in pairs


def test_affected_pairs_for_currencies_merges_unique() -> None:
    pairs = affected_pairs_for_currencies(["USD", "EUR"])
    assert "EURUSD" in pairs
    assert "USDJPY" in pairs
    assert len(pairs) == len(set(pairs))


def test_symbol_is_affected_true_and_false() -> None:
    assert symbol_is_affected("EURUSD", ["USD"]) is True
    assert symbol_is_affected("XAUUSD", ["JPY"]) is False
