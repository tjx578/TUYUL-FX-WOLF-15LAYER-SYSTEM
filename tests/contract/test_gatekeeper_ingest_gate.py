from __future__ import annotations

import copy

from constitution.gatekeeper import Gatekeeper
from state.ingest_state_consumer import IngestGateDecision


class _StubConsumer:
    def __init__(self, decision: IngestGateDecision) -> None:
        self._decision = decision

    def is_blocking(self):
        return self._decision


def _base_candidate() -> dict:
    return {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "L1": {"ctx": True},
        "L2": {"multi_timeframe_alignment": True},
        "L3": {"tech": True},
        "L4": {"score": 90},
        "L7": {"win_probability": 60.0},
        "L8": {
            "integrity": 0.99,
            "tii_sym": 0.95,
        },
        "L9": {"smc": True},
        "L10": {"position_ok": True},
        "L11": {"rr": 2.5},
    }


def test_gatekeeper_rejects_candidate_when_ingest_is_blocking() -> None:
    gate = Gatekeeper(
        ingest_state_consumer=_StubConsumer(
            IngestGateDecision(True, "ingest_no_producer", "NO_PRODUCER", None, None, "audit-1")
        )
    )

    result = gate.evaluate(_base_candidate())

    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_ingest_health"
    assert result["reason"] == "ingest_blocked:ingest_no_producer"


def test_gatekeeper_allows_healthy_ingest_and_continues_to_other_gates() -> None:
    gate = Gatekeeper(
        ingest_state_consumer=_StubConsumer(IngestGateDecision(False, "ingest_ok", "HEALTHY", 1.0, 1.0, "audit-2"))
    )
    candidate = copy.deepcopy(_base_candidate())
    candidate["L7"]["win_probability"] = 40.0

    result = gate.evaluate(candidate)

    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_probability"


def test_gatekeeper_keeps_ingest_gate_disabled_by_default() -> None:
    candidate = copy.deepcopy(_base_candidate())
    candidate["L7"]["win_probability"] = 40.0

    result = Gatekeeper(enable_ingest_gate=False).evaluate(candidate)

    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_probability"
