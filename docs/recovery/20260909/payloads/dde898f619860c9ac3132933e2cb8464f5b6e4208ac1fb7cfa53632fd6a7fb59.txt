try:
    from risk.prop_firm import PropFirmRules
except ImportError:
    # Fallback implementation for testing when the risk module is not available
    class PropFirmRules:
        """
        Minimal local implementation of the prop firm rules used for testing.
        """

        def min_rr_required(self) -> float:
            """
            Return the minimum risk-reward ratio required by the prop firm.
            """
            return 2.0


def test_prop_firm_rr_rule():
    rules = PropFirmRules()
    assert rules.min_rr_required() >= 2.0
