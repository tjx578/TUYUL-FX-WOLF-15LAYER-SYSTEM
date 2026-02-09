import copy

from constitution.gatekeeper import Gatekeeper


def _base_candidate():
    return {
        "symbol": "EURUSD",
        "L1": {"ctx": True},
        "L2": {"multi_timeframe_alignment": True},
        "L3": {"tech": True},
        "L4": {"score": 90},
        "L7": {"win_probability": 60.0},
        "L8": {
            "integrity": 0.99,
            "technical_integrity_index_symbol": 0.95,
            "tii_sym": 0.95,
        },
        "L9": {"smc": True},
        "L10": {"position_ok": True},
        "L11": {"rr": 2.5},
    }


def test_gatekeeper_all_gates_pass():
    gate = Gatekeeper()
    result = gate.evaluate(_base_candidate())
    assert result["passed"] is True
    assert result["reason"] == "ALL_GATES_PASSED"


def test_gatekeeper_blocks_low_probability():
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["L7"]["win_probability"] = 40.0

    result = gate.evaluate(candidate)

    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_probability"
    assert result["reason"].startswith("prob<")
