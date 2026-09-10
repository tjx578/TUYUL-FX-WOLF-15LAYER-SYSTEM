from constitution.gatekeeper import Gatekeeper


def test_l12_reject_invalid_candidate():
    gate = Gatekeeper()
    candidate = {"symbol": "EURUSD"}
    result = gate.evaluate(candidate)
    assert result["passed"] is False
