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
    read_source_ok = True
    # Successive values returned by read_failure_count, to model a failure that
    # happens during a scan; empty means a steady count.
    failure_counts: list[int] | None = None

    @property
    def read_failure_count(self) -> int:
        if self.failure_counts:
            return self.failure_counts.pop(0)
        return 0

    def check_warmup(self, symbol: str, min_bars: dict[str, int] | None = None) -> dict[str, Any]:
        if self.raises:
            raise RuntimeError("redis unavailable")
        return {"ready": self.ready, "bars": {"H1": 40}, "missing": {}}


@pytest.fixture
def bind(monkeypatch):
    """Bind the endpoint to an explicit pair universe and verdict store."""

    def _bind(
        pairs: list[dict[str, Any]],
        verdicts: dict[str, Any],
        reader: _Reader | None = None,
        verdict_source_ok: bool = True,
        verdict_failure_counts: list[int] | None = None,
    ):
        monkeypatch.setattr(l12_routes, "AVAILABLE_PAIRS", pairs)

        def _get_verdict(symbol: str) -> dict[str, Any] | None:
            value = verdicts.get(symbol)
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(dashboard_routes, "get_verdict", _get_verdict)
        bound = reader or _Reader()
        monkeypatch.setattr(redis_context_reader, "RedisContextReader", lambda *a, **k: bound)
        monkeypatch.setattr(dashboard_routes, "verdict_read_source_ok", lambda: verdict_source_ok)

        counts = list(verdict_failure_counts) if verdict_failure_counts else None

        def _failure_count() -> int:
            return counts.pop(0) if counts else 0

        monkeypatch.setattr(dashboard_routes, "verdict_read_failure_count", _failure_count)
        return bound

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


def test_publishes_an_explicit_governance_action(bind) -> None:
    """An action the record actually carries is published as-is.

    This is the reason the endpoint exists: the browser cannot reach the
    governance record, so the service resolves admission on its behalf.
    """
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {"EURUSD": _verdict(governance={"action": "ALLOW"})},
    )
    assert _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]["admission"] == "ALLOW"


def test_never_reports_a_degraded_hold_as_allowed(bind) -> None:
    """A degraded verdict carries no governance evidence, so admission is null.

    _build_degraded_verdict() persists HOLD after a pipeline timeout or error
    with neither a governance action nor a recognized governance reason.
    Publishing ALLOW there would claim governance ran when it did not.
    """
    bind(
        [{"symbol": "EURUSD", "enabled": True}, {"symbol": "GBPUSD", "enabled": True}],
        {
            "EURUSD": _verdict(errors=["PIPELINE_TIMEOUT:analysis"]),
            "GBPUSD": _verdict(),
        },
    )
    rows = _by_symbol(dashboard_routes.dashboard_pair_states())

    assert rows["EURUSD"]["admission"] is None
    # A record with no governance block at all is equally unmeasured.
    assert rows["GBPUSD"]["admission"] is None


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


def test_flags_a_suppressed_verdict_read_failure(bind) -> None:
    """A fail-soft Redis failure returns None, not an exception.

    Without the reader's own health signal this is indistinguishable from a pair
    that simply has no verdict yet, which is exactly the confusion source_ok
    exists to prevent.
    """
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": None}, verdict_source_ok=False)
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is False


def test_flags_a_suppressed_context_read_failure(bind) -> None:
    reader = _Reader()
    reader.read_source_ok = False
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": _verdict()}, reader=reader)
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is False


def test_latches_a_verdict_failure_that_healed_before_the_scan_ended(bind) -> None:
    """Read health is a cooldown window, not a latch.

    A failure on the first pair can lapse before the last pair is read, so
    asking only at the end would report a healthy source for a response whose
    rows came from reads that had already failed.  The failure count is what
    makes that detectable.
    """
    bind(
        [{"symbol": "EURUSD", "enabled": True}, {"symbol": "GBPUSD", "enabled": True}],
        {"EURUSD": None, "GBPUSD": _verdict()},
        verdict_source_ok=True,
        verdict_failure_counts=[0, 1],
    )
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is False


def test_latches_a_context_failure_that_healed_before_the_scan_ended(bind) -> None:
    reader = _Reader()
    reader.failure_counts = [0, 1]
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": _verdict()}, reader=reader)
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is False


def test_a_steady_failure_count_leaves_the_source_healthy(bind) -> None:
    """Failures before this scan are not this response's problem."""
    reader = _Reader()
    reader.failure_counts = [7, 7]
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {"EURUSD": _verdict()},
        reader=reader,
        verdict_failure_counts=[3, 3],
    )
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is True


def test_a_missing_snapshot_on_a_healthy_source_is_not_a_failure(bind) -> None:
    """Warmup is not an outage: no verdict yet, but both readers are healthy."""
    reader = _Reader()
    reader.ready = False
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": None}, reader=reader)
    response = dashboard_routes.dashboard_pair_states()

    assert response["source_ok"] is True
    assert response["items"][0]["snapshot_present"] is False
    assert response["items"][0]["warmup_ready"] is False


def test_reports_a_disabled_pair_as_inactive(bind) -> None:
    bind([{"symbol": "EURUSD", "enabled": False}], {"EURUSD": _verdict()})
    assert _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]["active"] is False


def test_publishes_a_row_for_every_configured_pair(bind) -> None:
    """items is the configured inventory, so count is not a snapshot count."""
    bind(
        [
            {"symbol": "EURUSD", "enabled": True},
            {"symbol": "GBPUSD", "enabled": True},
            {"symbol": "USDJPY", "enabled": False},
        ],
        {"EURUSD": _verdict()},
    )
    response = dashboard_routes.dashboard_pair_states()

    assert response["count"] == 3
    assert [item["symbol"] for item in response["items"]] == ["EURUSD", "GBPUSD", "USDJPY"]
    rows = _by_symbol(response)
    assert rows["GBPUSD"]["snapshot_present"] is False
    assert rows["USDJPY"]["active"] is False


@pytest.mark.parametrize(
    ("age_offset", "expected"),
    [
        (0.0, "LIVE"),
        (300.0, "LIVE"),
        (300.5, "STALE"),
        (900.0, "STALE"),
    ],
)
def test_quality_follows_the_stale_boundary(bind, age_offset: float, expected: str) -> None:
    bind(
        [{"symbol": "EURUSD", "enabled": True}],
        {"EURUSD": _verdict(_cached_at=time.time() - age_offset)},
    )
    assert _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]["quality"] == expected


@pytest.mark.parametrize(
    "stamped",
    [
        pytest.param(None, id="future"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="+inf"),
        pytest.param(float("-inf"), id="-inf"),
        pytest.param("not-a-number", id="unparseable"),
    ],
)
def test_an_unverifiable_timestamp_is_never_live(bind, stamped: Any) -> None:
    """A future or non-finite stamp means the clocks disagree, not that it is fresh."""
    value = time.time() + 600 if stamped is None else stamped
    bind([{"symbol": "EURUSD", "enabled": True}], {"EURUSD": _verdict(_cached_at=value)})
    row = _by_symbol(dashboard_routes.dashboard_pair_states())["EURUSD"]

    assert row["age_seconds"] is None
    assert row["quality"] is None
