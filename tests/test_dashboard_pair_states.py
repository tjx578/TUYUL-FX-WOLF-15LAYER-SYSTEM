"""Viewer-safe projection of cached engine evidence, without bus reconstruction."""

from typing import Any

import pytest

from api import dashboard_routes, l12_routes, verdict_normalization


@pytest.fixture
def bind(monkeypatch):
    monkeypatch.setattr(verdict_normalization.time, "time", lambda: 1_800_000_000.0)

    def configure(pairs, verdicts, healthy=True, failure_counts=None):
        monkeypatch.setattr(l12_routes, "AVAILABLE_PAIRS", pairs)

        def batch(symbols):
            if isinstance(verdicts, Exception):
                raise verdicts
            return {symbol: verdicts.get(symbol) for symbol in symbols}

        monkeypatch.setattr(dashboard_routes, "get_verdicts", batch)
        monkeypatch.setattr(dashboard_routes, "verdict_read_source_ok", lambda: healthy)
        counts = list(failure_counts or [0, 0])
        monkeypatch.setattr(dashboard_routes, "verdict_read_failure_count", lambda: counts.pop(0))

    return configure


def record(**changes: Any) -> dict[str, Any]:
    return {"verdict": "HOLD", "_cached_at": 1_800_000_000.0, **changes}


def row():
    return dashboard_routes.dashboard_pair_states()["items"][0]


def test_inventory_retains_missing_and_disabled_pairs(bind):
    bind(
        [{"symbol": "USDJPY", "enabled": False}, {"symbol": "GBPUSD"}, {"symbol": "EURUSD"}],
        {"EURUSD": record(governance={"action": "ALLOW"}, warmup_ready=True)},
    )
    response = dashboard_routes.dashboard_pair_states()
    assert response["source_ok"] is True
    assert response["count"] == 3
    assert [r["symbol"] for r in response["items"]] == ["EURUSD", "GBPUSD", "USDJPY"]
    first, missing, disabled = response["items"]
    assert first["warmup_ready"] is True
    assert first["admission"] == "ALLOW"
    assert first["quality"] == "LIVE"
    assert missing["snapshot_present"] is False
    assert all(missing[k] is None for k in ("verdict", "admission", "age_seconds", "quality", "warmup_ready"))
    assert disabled["active"] is False


@pytest.mark.parametrize("action", ["ALLOW", "ALLOW_REDUCED", "BLOCK", "HOLD"])
def test_explicit_governance_is_published(bind, action):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(governance={"action": action})})
    assert row()["admission"] == action


@pytest.mark.parametrize(
    "reason,action",
    [
        ("GOVERNANCE_BLOCK:private", "BLOCK"),
        ("GOVERNANCE_HOLD:private", "HOLD"),
        ("WARMUP_INSUFFICIENT:private", "HOLD"),
    ],
)
def test_recognized_reason_carries_only_declared_code(bind, reason, action):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(errors=[reason])})
    result = row()
    assert result["admission"] == action
    assert result["reason_code"] == reason.split(":")[0]
    assert "private" not in str(result)


@pytest.mark.parametrize("errors", [[], ["PIPELINE_TIMEOUT:analysis"], ["PIPELINE_ERROR:failure"]])
def test_degraded_or_missing_governance_stays_unmeasured(bind, errors):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(errors=errors)})
    assert row()["admission"] is None
    assert verdict_normalization.extract_governance_action(record(errors=errors)) == "ALLOW"


def test_undeclared_values_and_private_fields_are_not_published(bind):
    bind(
        [{"symbol": "EURUSD"}],
        {
            "EURUSD": record(
                verdict="WAIT",
                governance={"action": "CANARY"},
                last_hold_block_reason="CANARY:private",
                confidence=0.9,
                scores={"x": 1},
                gates={"x": True},
                execution={"lot_size": 10},
                diagnostics="CANARY",
                errors=["CANARY"],
            )
        },
    )
    response = dashboard_routes.dashboard_pair_states()
    assert set(response) == {"observed_at", "source_ok", "count", "items"}
    result = response["items"][0]
    assert set(result) == {
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
    assert all(result[k] is None for k in ("verdict", "admission", "reason_code", "warmup_ready"))
    assert "CANARY" not in str(response)
    assert "lot_size" not in str(response)


@pytest.mark.parametrize("verdict", sorted(verdict_normalization.VERDICT_STATES))
def test_declared_verdict_states_are_preserved(bind, verdict):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(verdict=verdict)})
    assert row()["verdict"] == verdict


@pytest.mark.parametrize(
    "ready,expected", [(True, True), (False, False), (None, None), (1, None), (0, None), ("true", None), ({}, None)]
)
def test_warmup_only_uses_typed_engine_evidence(bind, ready, expected):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(warmup_ready=ready)})
    assert row()["warmup_ready"] is expected


def test_no_context_redis_reconstruction(bind, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Dashboard must not reconstruct engine warmup")

    monkeypatch.setattr("api.redis_context_reader.RedisContextReader", forbidden)
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(warmup_ready=True)})
    response = dashboard_routes.dashboard_pair_states()
    assert response["source_ok"] is True
    assert response["items"][0]["warmup_ready"] is True


@pytest.mark.parametrize("healthy,counts", [(False, [0, 0]), (True, [0, 1])])
def test_suppressed_or_recovered_read_failure_is_latched(bind, healthy, counts):
    bind([{"symbol": "EURUSD"}], {}, healthy=healthy, failure_counts=counts)
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is False


def test_prior_failures_do_not_poison_current_read(bind):
    bind([{"symbol": "EURUSD"}], {}, failure_counts=[7, 7])
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is True


def test_raised_read_failure_retains_unknown_inventory(bind):
    bind([{"symbol": "EURUSD"}], RuntimeError("Redis unavailable"))
    response = dashboard_routes.dashboard_pair_states()
    assert response["source_ok"] is False
    assert response["count"] == 1
    assert response["items"][0]["warmup_ready"] is None


def test_failure_during_health_sampling_is_not_absorbed(bind, monkeypatch):
    bind([{"symbol": "EURUSD"}], {})
    generation = [0]

    def health():
        generation[0] = 1
        return True

    monkeypatch.setattr(dashboard_routes, "verdict_read_source_ok", health)
    monkeypatch.setattr(dashboard_routes, "verdict_read_failure_count", lambda: generation[0])
    assert dashboard_routes.dashboard_pair_states()["source_ok"] is False


def test_one_batch_for_inventory(bind, monkeypatch):
    symbols = [f"PAIR{i}" for i in range(30)]
    bind([{"symbol": s} for s in symbols], {})
    calls = []

    def batch(requested):
        calls.append(requested)
        return {}

    monkeypatch.setattr(dashboard_routes, "get_verdicts", batch)
    response = dashboard_routes.dashboard_pair_states()
    assert calls == [symbols]
    assert response["count"] == 30
    assert response["source_ok"] is True


@pytest.mark.parametrize(
    "age,quality", [(0.0, "LIVE"), (300.0, "LIVE"), (300.0001, "STALE"), (300.5, "STALE"), (900.0, "STALE")]
)
def test_snapshot_age_boundary(bind, age, quality):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(_cached_at=1_800_000_000.0 - age)})
    assert row()["quality"] == quality


@pytest.mark.parametrize("stamp", [1_800_000_600.0, float("nan"), float("inf"), float("-inf"), "bad"])
def test_unverifiable_freshness_is_not_live(bind, stamp):
    bind([{"symbol": "EURUSD"}], {"EURUSD": record(_cached_at=stamp)})
    result = row()
    assert result["age_seconds"] is None
    assert result["quality"] is None
