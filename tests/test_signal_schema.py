from schemas.validator import validate_signal_contract


def make_signal_contract(**overrides):
    base = dict(
        contract_version="2026-03-03",
        signal_id="SIG-001",
        symbol="EURUSD",
        verdict="EXECUTE",
        confidence=0.9,
        timestamp=1700000000.0,
        take_profit_1=5.0,
    )
    base.update(overrides)
    return base


def test_take_profit_1_positive():
    # Valid
    valid = make_signal_contract(take_profit_1=5.0)
    ok, errors = validate_signal_contract(valid)
    assert ok
    # Invalid: zero
    invalid_zero = make_signal_contract(take_profit_1=0.0)
    ok, errors = validate_signal_contract(invalid_zero)
    assert not ok
    assert any("take_profit_1" in e for e in errors)
    # Invalid: negative
    invalid_neg = make_signal_contract(take_profit_1=-3.0)
    ok, errors = validate_signal_contract(invalid_neg)
    assert not ok
    assert any("take_profit_1" in e for e in errors)
    # Valid: None (allowed by schema)
    none_val = make_signal_contract(take_profit_1=None)
    ok, errors = validate_signal_contract(none_val)
    assert ok


def test_direction_hold_is_invalid():
    """'HOLD' must NOT be accepted as a direction — schema only allows BUY, SELL, or null."""
    invalid = make_signal_contract(direction="HOLD")
    ok, errors = validate_signal_contract(invalid)
    assert not ok
    assert any("direction" in e for e in errors)


def test_direction_none_is_valid():
    """None (null) is a valid direction for non-EXECUTE verdicts."""
    valid = make_signal_contract(direction=None)
    ok, errors = validate_signal_contract(valid)
    assert ok


def test_direction_buy_sell_valid():
    """BUY and SELL are valid direction values."""
    for direction in ("BUY", "SELL"):
        valid = make_signal_contract(direction=direction)
        ok, errors = validate_signal_contract(valid)
        assert ok, f"direction={direction!r} should be valid but got errors: {errors}"
