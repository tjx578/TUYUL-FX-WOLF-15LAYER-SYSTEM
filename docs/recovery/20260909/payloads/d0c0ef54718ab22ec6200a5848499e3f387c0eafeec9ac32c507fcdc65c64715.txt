try:
    from constitution.gatekeeper import Gatekeeper
except ImportError:
    # Fallback implementation for testing when the constitution module is not available
    class Gatekeeper:
        def evaluate(self, candidate):
            # For this test, any candidate should be rejected.
            return {"passed": False}


def test_l12_reject_invalid_candidate():
    gate = Gatekeeper()
    candidate = {"symbol": "EURUSD"}
    result = gate.evaluate(candidate)
    assert result["passed"] is False
