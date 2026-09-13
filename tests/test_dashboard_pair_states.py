"""Contract tests for GET /api/v1/dashboard/pair-states.

The endpoint exists so that governance normalization stays on the service side
of the viewer boundary.  These tests pin both halves of that: the normalization
is actually applied, and nothing outside the declared projection is published.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from api import dashboard_routes, l12_routes, redis_context_reader


class _Reader:
    """Stand-in for RedisContextReader with a fixed warmup answer."""

    ready = True
    raises = False

    def check_warmup(self, symbol: str, min_bars: dict[str, int] | None = None) -> dict[str, Any]:
        if self.raises:
            raise RuntimeError("redis unavailable")
        return {"ready": self.ready, "bars": {"H1": 40}, "missing": {}}


@pytest.fixture
def bind(monkeypatch):
    """Bind the endpoint to an explicit pair universe and verdict store."""

    def _bind(pairs: list[dict[str, Any]], verdicts: dict[str, Any], reader: _Reader | None = None):
        monkeypatch.setattr(l12_routes, "AVAILABLE_PAIRS", pairs)

        def _get_verdict(symbol: str) -> dict[str, Any] | None:
            value = verdicts.get(symbol)
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(dashboard_routes, "get_verdict", _get_verdict)
        monkeypatch.setattr(redis_context_reader, "RedisContextReader", lambda *a, **k: reader or _Reader())

    return _bind


def _verdict(**changes: Any) -> dict[str, Any]:
    base = {"verdict": "HOLD", "_cached_at": time.time()}
    base.update(changes)
    return base


def _by_symbol(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["symbol"]: item for item in response["items"]}


def test_projects_one_row_per_available_verdict(bind) -> None:
    bind(
        [{"symbol": "GBPUSD", "enabled": True}, {"symbol": "EURUSD", "enabled": True}],
        {
            "EURUSD": _verdict(verdict="EXECUTE_REDUCED_RISK_BUY", governance={"action": "ALLOW_REDUCED"}),
            "GBPUSD": _verdict(verdict="NO_TRADE"),
        },
    )
    response = dashboard_routes.dashboard_pair_states()

    assert response["count"] == 2
    assert response["source_ok"] is True
    # Deterministic order regardless of the configured pair order.
    assert [item["symbol"] for item in response["items"]] == ["EURUSD", "GBPUSD"]

    rows = _by_symbol(response)
    assert rows["EURUSD"]["verdict"] == "EXECUTE_REDUCED_RISK_BUY"
    assert rows["EURUSD"]["admission"] == "ALLOW_REDUCED"
    assert rows["EURUSD"]["quality"] == "LIVE"
    assert rows["EURUSD"]["snapshot_present"] is True
    assert rows["EURUSD"]["warmup_ready"] is True
    assert rows["EURUSD"]["active"] is True


def test_applies_backend_governance_normalization(bind) -> None:
    """A record with no explicit action still normalizes to ALLOW here.

    This is the reason the endpoint exists: a browser reading the raw verdict
    would see an absent action and could only report it as unmeasured.
    """
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": _verdict(governance={})})
    assert _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]["admission"] == "ALLOW"


def test_derives_admission_and_reason_from_a_hold(bind) -> None:
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {"EURUSD": _verdict(last_hold_block_reason="GOVERNANCE_HOLD:stale_preserved,vix_spike")},
    )
    row = _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]

    assert row["admission"] == "HOLD"
    # Only the leading token survives; the detail after ":" is free-form.
    assert row["reason_code"] == "GOVERNANCE_HOLD"


def test_reports_undeclared_values_as_unmeasured(bind) -> None:
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {
            "EURUSD": _verdict(
                verdict="WAIT",
                governance={"action": "CANARY"},
                last_hold_block_reason="CANARY:detail",
            )
        },
    )
    row = _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]

    assert row["verdict"] is None
    assert row["admission"] is None
    assert row["reason_code"] is None


def test_omits_every_field_outside_the_projection(bind) -> None:
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {
            "EURUSD": _verdict(
                confidence=0.91,
                direction="BUY",
                scores={"tii": 0.8},
                gates={"passed": 9},
                execution={"lot_size": 0.42, "risk_amount": 120.0},
                execution_map={"halt_reason": "CANARY"},
                mta_diagnostics={"detail": "CANARY"},
                errors=["CANARY"],
            )
        },
    )
    response = dashboard_routes.dashboard_pair_states()

    assert set(response) == {"observed_at", "source_ok", "count", "items"}
    assert set(response["items"][0]) == {
        "symbol",
        "verdict",
        "admission",
        "reason_code",
        "age_seconds",
        "quality",
        "warmup_ready",
        "active",
        "snapshot_present",
    }
    assert "CANARY" not in str(response)
    assert "lot_size" not in str(response)


def test_marks_a_pair_without_a_snapshot(bind) -> None:
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": None})
    row = _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]

    assert row["snapshot_present"] is False
    assert row["verdict"] is None
    assert row["admission"] is None
    assert row["age_seconds"] is None
    assert row["quality"] is None


def test_reports_a_stale_snapshot(bind) -> None:
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {"EURUSD": _verdict(_cached_at=time.time() - 900)},
    )
    assert _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]["quality"] == "STALE"


def test_flags_an_unreadable_source_without_failing_the_read(bind) -> None:
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": RuntimeError("redis down")})
    response = dashboard_routes.dashboard_pair_states()

    assert response["source_ok"] is False
    assert response["items"][0]["snapshot_present"] is False


def test_reports_a_disabled_pair_as_inactive(bind) -> None:
    bind([{"symbol": "EURUSD", "enabled": False}], {"EURUSD": _verdict()})
    assert _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]["active"] is False
