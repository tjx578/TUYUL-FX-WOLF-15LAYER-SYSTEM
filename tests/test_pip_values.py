"""Tests for config/pip_values.py -- pip value single source of truth."""

import pytest

from config.pip_values import (
    _JPY_MULTIPLIER,
    _STANDARD_MULTIPLIER,
    DEFAULT_PIP_VALUE,
    PIP_MULTIPLIERS,
    PIP_VALUES_PER_STANDARD_LOT,
    PipLookupError,
    get_pip_info,
    get_pip_multiplier,
    get_pip_value,
    is_pair_supported,
    list_supported_pairs,
)

# ── Table Integrity ──────────────────────────────────────────────────

class TestTableIntegrity:
    """Validate the static tables are self-consistent."""

    def test_all_pip_values_positive(self):
        for pair, val in PIP_VALUES_PER_STANDARD_LOT.items():
            assert val > 0, f"{pair} has non-positive pip value: {val}"

    def test_all_multipliers_positive(self):
        for pair, mult in PIP_MULTIPLIERS.items():
            assert mult > 0, f"{pair} has non-positive multiplier: {mult}"

    def test_every_pip_value_pair_has_multiplier(self):
        for pair in PIP_VALUES_PER_STANDARD_LOT:
            assert pair in PIP_MULTIPLIERS, (
                f"{pair} in PIP_VALUES but missing from PIP_MULTIPLIERS"
            )

    def test_no_duplicate_keys(self):
        """Ensure no duplicate pair entries (case-normalized)."""
        keys = list(PIP_VALUES_PER_STANDARD_LOT.keys())
        upper_keys = [k.upper() for k in keys]
        assert len(upper_keys) == len(set(upper_keys))

    def test_default_pip_value_positive(self):
        assert DEFAULT_PIP_VALUE > 0


# ── P0 Bug Fix: XAUUSD ──────────────────────────────────────────────

class TestP0XauusdFix:
    """The original bug: XAUUSD was 0.10 in dashboard vs 10.0 in config."""

    def test_xauusd_pip_value_is_10(self):
        assert PIP_VALUES_PER_STANDARD_LOT["XAUUSD"] == 10.0
        assert get_pip_value("XAUUSD") == 10.0

    def test_xauusd_multiplier_is_10(self):
        """XAUUSD: 1 pip = $0.10 -> multiplier = 10."""
        assert get_pip_multiplier("XAUUSD") == 10.0

    def test_xagusd_pip_value_is_50(self):
        assert PIP_VALUES_PER_STANDARD_LOT["XAGUSD"] == 50.0
        assert get_pip_value("XAGUSD") == 50.0

    def test_xagusd_multiplier_is_100(self):
        """XAGUSD: 1 pip = $0.01 -> multiplier = 100."""
        assert get_pip_multiplier("XAGUSD") == 100.0


# ── get_pip_value ────────────────────────────────────────────────────

class TestGetPipValue:
    def test_known_pair(self):
        assert get_pip_value("GBPUSD") == 10.0

    def test_case_insensitive(self):
        assert get_pip_value("gbpusd") == 10.0
        assert get_pip_value("GbpUsd") == 10.0

    def test_slash_stripped(self):
        assert get_pip_value("GBP/USD") == 10.0

    def test_whitespace_stripped(self):
        assert get_pip_value("  GBPUSD  ") == 10.0

    def test_unknown_pair_raises(self):
        with pytest.raises(PipLookupError) as exc_info:
            get_pip_value("ZZZZZZZ")
        assert "ZZZZZZZ" in str(exc_info.value)
        assert exc_info.value.pair == "ZZZZZZZ"
        assert exc_info.value.table_name == "PIP_VALUES_PER_STANDARD_LOT"

    def test_jpy_pairs_have_lower_values(self):
        """JPY-denominated pairs typically have lower pip values."""
        for pair in ("USDJPY", "GBPJPY", "EURJPY"):
            val = get_pip_value(pair)
            assert val < 10.0, f"{pair} pip value {val} seems wrong for JPY pair"

    def test_all_supported_pairs_return_value(self):
        for pair in list_supported_pairs():
            val = get_pip_value(pair)
            assert isinstance(val, float)
            assert val > 0


# ── get_pip_multiplier ───────────────────────────────────────────────

class TestGetPipMultiplier:
    def test_standard_fx(self):
        assert get_pip_multiplier("EURUSD") == _STANDARD_MULTIPLIER
        assert get_pip_multiplier("GBPUSD") == _STANDARD_MULTIPLIER

    def test_jpy_pairs(self):
        assert get_pip_multiplier("USDJPY") == _JPY_MULTIPLIER
        assert get_pip_multiplier("GBPJPY") == _JPY_MULTIPLIER
        assert get_pip_multiplier("EURJPY") == _JPY_MULTIPLIER

    def test_gold(self):
        assert get_pip_multiplier("XAUUSD") == 10.0

    def test_silver(self):
        assert get_pip_multiplier("XAGUSD") == 100.0

    def test_indices(self):
        assert get_pip_multiplier("US30") == 1.0
        assert get_pip_multiplier("US500") == 1.0
        assert get_pip_multiplier("NAS100") == 1.0

    def test_case_insensitive(self):
        assert get_pip_multiplier("xauusd") == 10.0
        assert get_pip_multiplier("usdjpy") == _JPY_MULTIPLIER

    def test_unknown_pair_raises(self):
        with pytest.raises(PipLookupError) as exc_info:
            get_pip_multiplier("ZZZZZZZ")
        assert exc_info.value.pair == "ZZZZZZZ"
        assert "PIP_MULTIPLIERS" in exc_info.value.table_name

    def test_gold_not_10000(self):
        """Critical regression: XAUUSD must NOT use the standard 10000 multiplier."""
        assert get_pip_multiplier("XAUUSD") != _STANDARD_MULTIPLIER

    def test_silver_not_10000(self):
        assert get_pip_multiplier("XAGUSD") != _STANDARD_MULTIPLIER


# ── Pip math consistency ─────────────────────────────────────────────

class TestPipMathConsistency:
    """Verify pip multiplier and pip values produce correct risk amounts."""

    def test_eurusd_50pip_sl_1lot(self):
        """EURUSD: 50 pip SL, 1 lot -> $500 risk."""
        entry = 1.10000
        sl = 1.09500
        mult = get_pip_multiplier("EURUSD")
        pv = get_pip_value("EURUSD")
        sl_pips = abs(entry - sl) * mult
        risk = sl_pips * pv * 1.0   # 1 standard lot

        assert sl_pips == pytest.approx(50.0, abs=0.1)
        assert risk == pytest.approx(500.0, abs=1.0)

    def test_usdjpy_50pip_sl_1lot(self):
        """USDJPY: 50 pip SL, 1 lot -> ~$333.50 risk."""
        entry = 155.000
        sl = 154.500
        mult = get_pip_multiplier("USDJPY")
        pv = get_pip_value("USDJPY")
        sl_pips = abs(entry - sl) * mult
        risk = sl_pips * pv * 1.0

        assert sl_pips == pytest.approx(50.0, abs=0.1)
        assert risk == pytest.approx(333.5, abs=5.0)

    def test_xauusd_50pip_sl_1lot(self):
        """XAUUSD: $5.00 SL distance = 50 pips, 1 lot -> $500 risk."""
        entry = 2000.00
        sl = 1995.00
        mult = get_pip_multiplier("XAUUSD")
        pv = get_pip_value("XAUUSD")
        sl_pips = abs(entry - sl) * mult
        risk = sl_pips * pv * 1.0

        assert sl_pips == pytest.approx(50.0, abs=0.1)
        assert risk == pytest.approx(500.0, abs=1.0)

    def test_xagusd_50pip_sl_1lot(self):
        """XAGUSD: $0.50 SL distance = 50 pips, 1 lot -> $2500 risk."""
        entry = 25.00
        sl = 24.50
        mult = get_pip_multiplier("XAGUSD")
        pv = get_pip_value("XAGUSD")
        sl_pips = abs(entry - sl) * mult
        risk = sl_pips * pv * 1.0

        assert sl_pips == pytest.approx(50.0, abs=0.1)
        assert risk == pytest.approx(2500.0, abs=1.0)

    def test_index_us30_10point_sl(self):
        """US30: 10 point SL = 10 pips, 1 lot -> $100 risk."""
        entry = 40000.0
        sl = 39990.0
        mult = get_pip_multiplier("US30")
        pv = get_pip_value("US30")
        sl_pips = abs(entry - sl) * mult
        risk = sl_pips * pv * 1.0

        assert sl_pips == pytest.approx(10.0, abs=0.1)
        assert risk == pytest.approx(100.0, abs=1.0)


# ── get_pip_info ─────────────────────────────────────────────────────

class TestGetPipInfo:
    def test_returns_both(self):
        pv, mult = get_pip_info("GBPUSD")
        assert pv == 10.0
        assert mult == _STANDARD_MULTIPLIER

    def test_gold_returns_both(self):
        pv, mult = get_pip_info("XAUUSD")
        assert pv == 10.0
        assert mult == 10.0

    def test_unknown_raises(self):
        with pytest.raises(PipLookupError):
            get_pip_info("ZZZZZZZ")


# ── is_pair_supported ────────────────────────────────────────────────

class TestIsPairSupported:
    def test_known(self):
        assert is_pair_supported("GBPUSD") is True

    def test_known_lowercase(self):
        assert is_pair_supported("gbpusd") is True

    def test_unknown(self):
        assert is_pair_supported("ZZZZZZZ") is False

    def test_slash_format(self):
        assert is_pair_supported("GBP/USD") is True


# ── list_supported_pairs ─────────────────────────────────────────────

class TestListSupportedPairs:
    def test_returns_list(self):
        pairs = list_supported_pairs()
        assert isinstance(pairs, list)
        assert len(pairs) > 0

    def test_sorted(self):
        pairs = list_supported_pairs()
        assert pairs == sorted(pairs)

    def test_contains_majors(self):
        pairs = list_supported_pairs()
        for major in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
            assert major in pairs

    def test_all_pairs_uppercase(self):
        for pair in list_supported_pairs():
            assert pair == pair.upper()


# ── PipLookupError ───────────────────────────────────────────────────

class TestPipLookupError:
    def test_is_lookup_error(self):
        err = PipLookupError("ZZZZZZZ", "TEST_TABLE")
        assert isinstance(err, LookupError)

    def test_attributes(self):
        err = PipLookupError("ZZZZZZZ", "TEST_TABLE")
        assert err.pair == "ZZZZZZZ"
        assert err.table_name == "TEST_TABLE"

    def test_message(self):
        err = PipLookupError("ZZZZZZZ", "TEST_TABLE")
        assert "ZZZZZZZ" in str(err)
        assert "TEST_TABLE" in str(err)
        assert "is_pair_supported" in str(err)


# ── Constitutional: No Business Logic ────────────────────────────────

class TestConstitutionalNoBusinessLogic:
    """Config module must NOT contain position sizing or risk logic."""

    def test_no_lot_size_function(self):
        import config.pip_values as mod  # noqa: PLC0415
        assert not hasattr(mod, "calculate_lot_size"), (
            "Lot sizing belongs in risk/position_sizer.py, not config/"
        )

    def test_no_risk_amount_function(self):
        import config.pip_values as mod  # noqa: PLC0415
        assert not hasattr(mod, "calculate_risk_amount"), (
            "Risk calculation belongs in risk/position_sizer.py, not config/"
        )

    def test_get_pip_value_has_no_lot_parameter(self):
        """get_pip_value returns per-standard-lot value only.
        Scaling by lot_size is the caller's responsibility."""
        import inspect  # noqa: PLC0415
        sig = inspect.signature(get_pip_value)
        param_names = list(sig.parameters.keys())
        assert "lot_size" not in param_names, (
            "get_pip_value must not accept lot_size -- "
            "scaling is the caller's (risk/) responsibility"
        )

    def test_no_clamping_logic(self):
        """Config must not contain min/max lot enforcement."""
        import config.pip_values as mod  # noqa: PLC0415
        source = inspect.getsource(mod)
        assert "max(0.01" not in source, "Lot clamping belongs in risk/"
        assert "min(10.0" not in source, "Lot clamping belongs in risk/"

    def test_no_account_references(self):
        """Config must not reference account state."""
        import inspect  # noqa: PLC0415

        import config.pip_values as mod  # noqa: PLC0415
        source = inspect.getsource(mod)
        for forbidden in ("balance", "equity", "account_state"):
            assert forbidden not in source.lower(), (
                f"Config must not reference '{forbidden}'"
            )


# Need inspect for constitutional tests
import inspect  # noqa: E402
