from risk.prop_firm import PropFirmRules


def test_prop_firm_rr_rule():
    rules = PropFirmRules()
    assert rules.min_rr_required() >= 2.0
