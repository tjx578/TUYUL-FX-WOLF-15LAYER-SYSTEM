from risk.prop_firm import PropFirmRules


def test_market_allowlist_respected():
    rules = PropFirmRules()
    assert rules.is_market_allowed("forex") is True
    assert rules.is_market_allowed("crypto") is False


def test_risk_thresholds_loaded():
    rules = PropFirmRules()
    assert rules.max_risk_allowed() == 1.0
    assert rules.min_rr_required() == 2.0
