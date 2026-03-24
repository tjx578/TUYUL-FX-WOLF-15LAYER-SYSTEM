"""Tests for schemas.direction.normalize_direction."""

import pytest

from schemas.direction import normalize_direction


class TestNormalizeDirection:
    """normalize_direction must only return BUY, SELL, or None."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("BUY", "BUY"),
            ("SELL", "SELL"),
            ("buy", "BUY"),
            ("sell", "SELL"),
            (" Buy ", "BUY"),
        ],
    )
    def test_valid_directions_pass_through(self, raw: str, expected: str) -> None:
        assert normalize_direction(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["HOLD", "NO_TRADE", "NEUTRAL", "ABORT", "", "MIXED", None],
    )
    def test_non_executable_returns_none(self, raw: str | None) -> None:
        assert normalize_direction(raw) is None

    def test_verdict_fallback_execute_buy(self) -> None:
        assert normalize_direction(None, "EXECUTE_BUY") == "BUY"
        assert normalize_direction("", "EXECUTE_BUY") == "BUY"
        assert normalize_direction("HOLD", "EXECUTE_BUY") == "BUY"

    def test_verdict_fallback_execute_sell(self) -> None:
        assert normalize_direction(None, "EXECUTE_SELL") == "SELL"
        assert normalize_direction("NEUTRAL", "EXECUTE_SELL") == "SELL"

    def test_verdict_fallback_reduced_risk(self) -> None:
        assert normalize_direction(None, "EXECUTE_REDUCED_RISK_BUY") == "BUY"
        assert normalize_direction(None, "EXECUTE_REDUCED_RISK_SELL") == "SELL"

    def test_hold_verdict_returns_none(self) -> None:
        assert normalize_direction(None, "HOLD") is None
        assert normalize_direction("HOLD", "HOLD") is None

    def test_no_trade_verdict_returns_none(self) -> None:
        assert normalize_direction(None, "NO_TRADE") is None

    def test_raw_direction_takes_precedence(self) -> None:
        # Valid direction should win over verdict inference
        assert normalize_direction("BUY", "EXECUTE_SELL") == "BUY"
        assert normalize_direction("SELL", "EXECUTE_BUY") == "SELL"
