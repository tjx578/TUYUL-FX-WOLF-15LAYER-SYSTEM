"""Unit tests for services.shared.type_coerce."""

from __future__ import annotations

import pytest

from services.shared.type_coerce import to_bool, to_float, to_int


class TestToFloat:
    @pytest.mark.parametrize("value, expected", [
        (1, 1.0),
        (0, 0.0),
        (3.14, 3.14),
        ("2.5", 2.5),
        ("-1.0", -1.0),
        ("0", 0.0),
    ])
    def test_valid(self, value: object, expected: float) -> None:
        assert to_float(value) == expected

    @pytest.mark.parametrize("value", [None, "", "abc", [], {}])
    def test_invalid_returns_default(self, value: object) -> None:
        assert to_float(value) == 0.0

    def test_custom_default(self) -> None:
        assert to_float(None, -1.0) == -1.0


class TestToInt:
    @pytest.mark.parametrize("value, expected", [
        (5, 5),
        (3.9, 3),
        ("7", 7),
        ("3.5", 3),
        (True, 1),
        (False, 0),
    ])
    def test_valid(self, value: object, expected: int) -> None:
        assert to_int(value) == expected

    @pytest.mark.parametrize("value", [None, "", "abc", [], {}])
    def test_invalid_returns_default(self, value: object) -> None:
        assert to_int(value) == 0

    def test_custom_default(self) -> None:
        assert to_int(None, -1) == -1


class TestToBool:
    @pytest.mark.parametrize("value", [True, "true", "True", "1", "yes", "on", "ON"])
    def test_truthy(self, value: object) -> None:
        assert to_bool(value) is True

    @pytest.mark.parametrize("value", [False, "false", "0", "no", "off", "random"])
    def test_falsy(self, value: object) -> None:
        assert to_bool(value) is False

    def test_none_returns_default(self) -> None:
        assert to_bool(None) is False
        assert to_bool(None, True) is True
