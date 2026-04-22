from __future__ import annotations

from typing import Any

import pytest

from constitution.verdict_engine import generate_l12_verdict
from state.ingest_state_consumer import IngestGateDecision


class _StubConsumer:
    def __init__(self, decision: IngestGateDecision) -> None:
        self._decision = decision

    def is_blocking(self):
        return self._decision


def _make_synthesis() -> dict[str, Any]:
    return {
        "pair": "EURUSD",
        "scores": {
            "wolf_30_point": 25,
            "fta_score": 0.8,
        },
        "layers": {
            "L8_tii_sym": 0.95,
            "L8_integrity_index": 0.98,
            "L7_monte_carlo_win": 0.75,
            "conf12": 0.85,
            "enrichment_score": 0.0,
        },
        "execution": {
            "rr_ratio": 2.0,
        },
        "propfirm": {
            "compliant": True,
        },
        "risk": {
            "current_drawdown": 2.0,
            "max_drawdown": 5.0,
        },
        "bias": {
            "technical": "BULLISH",
        },
        "macro_vix": {
            "regime_state": 1,
        },
        "system": {
            "latency_ms": 100,
        },
    }


def test_generate_l12_verdict_returns_no_trade_when_ingest_blocking() -> None:
    verdict = generate_l12_verdict(
        _make_synthesis(),
        ingest_state_consumer=_StubConsumer(
            IngestGateDecision(True, "ingest_degraded_too_long:age=61.0s", "DEGRADED", 1.0, 61.0, "audit-3")
        ),
    )

    assert verdict["verdict"] == "NO_TRADE"
    assert verdict["proceed_to_L13"] is False
    assert verdict["gates"]["ingest_gate"] == "FAIL"
    assert verdict["verdict_reason"] == "ingest_unhealthy:ingest_degraded_too_long:age=61.0s"
    assert verdict["audit"]["ingest_state"] == "DEGRADED"


def test_generate_l12_verdict_keeps_existing_path_when_ingest_is_healthy() -> None:
    verdict = generate_l12_verdict(
        _make_synthesis(),
        ingest_state_consumer=_StubConsumer(IngestGateDecision(False, "ingest_ok", "HEALTHY", 1.0, 1.0, "audit-4")),
    )

    assert verdict["verdict"] in {"EXECUTE_BUY", "EXECUTE_REDUCED_RISK_BUY", "HOLD", "NO_TRADE"}
    assert verdict["gates"].get("ingest_gate") != "FAIL"


def test_generate_l12_verdict_keeps_existing_path_when_ingest_gate_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WOLF15_ENABLE_INGEST_GATE", raising=False)

    verdict = generate_l12_verdict(_make_synthesis())

    assert verdict["verdict"] in {"EXECUTE_BUY", "EXECUTE_REDUCED_RISK_BUY", "HOLD", "NO_TRADE"}
    assert verdict["gates"].get("ingest_gate") != "FAIL"


def test_generate_l12_verdict_uses_default_ingest_gate_when_env_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WOLF15_ENABLE_INGEST_GATE", "1")
    monkeypatch.setattr(
        "state.ingest_state_consumer.get_ingest_state_consumer",
        lambda: _StubConsumer(IngestGateDecision(True, "ingest_no_producer", "NO_PRODUCER", None, None, "audit-5")),
    )

    verdict = generate_l12_verdict(_make_synthesis())

    assert verdict["verdict"] == "NO_TRADE"
    assert verdict["gates"]["ingest_gate"] == "FAIL"
