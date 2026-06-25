from __future__ import annotations

from analysis.basket_direction_validator import decompose_symbol, validate_basket_direction


def test_basket_validator_accepts_buy_when_base_strong_quote_weak() -> None:
    result = validate_basket_direction(
        "USDCAD",
        "BUY",
        currency_scores={"USD": 0.72, "CAD": -0.38, "AUD": -0.66},
    )

    assert result.valid is True
    assert result.blockers == []
    assert result.pair_alignment == 1.1


def test_basket_validator_blocks_audcad_buy_when_aud_basket_is_weak() -> None:
    result = validate_basket_direction(
        "AUDCAD",
        "BUY",
        currency_scores={"AUD": -0.82, "CAD": 0.15, "USD": 0.40},
    )

    assert result.valid is False
    assert "BASE_AUD_BASKET_WEAK" in result.blockers
    assert "QUOTE_CAD_BASKET_STRONG" in result.blockers
    assert "PAIR_BASKET_NOT_ALIGNED_BUY" in result.blockers


def test_basket_validator_blocks_sell_when_base_is_strong() -> None:
    result = validate_basket_direction(
        "NZDCHF",
        "SELL",
        currency_scores={"NZD": 0.55, "CHF": -0.25},
    )

    assert result.valid is False
    assert "BASE_NZD_BASKET_STRONG" in result.blockers
    assert "QUOTE_CHF_BASKET_WEAK" in result.blockers


def test_decompose_symbol_supports_metals_against_major_quote() -> None:
    assert decompose_symbol("XAUUSD") == ("XAU", "USD")
