"""The shadow worker must observe and nothing else.

Phase one is defined by what it refuses to do: with the flag off it does not
run, with shadow_only false it refuses, with dual-write off it does not
persist, and in every case it produces no execution effect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analysis.strategy_5scr_v3.episode_grouping import EpisodeEvent
from analysis.strategy_5scr_v3.episode_policy import (
    EpisodePreflightError,
    assert_episode_rollout_is_safe,
    episode_lifecycle_v2_enabled,
    episode_shadow_only,
    resolve_episode_policy,
)
from services.pressure_outbox.lifecycle_shadow_worker import (
    LifecycleShadowWorker,
    episode_event_from_outbox_row,
)

START = datetime(2026, 7, 17, 13, 0, 0, tzinfo=UTC)


class _FakeRepository:
    """In-memory stand-in exposing the repository surface the worker uses."""

    def __init__(self, active=None):
        self._active = active
        self.persisted: list[tuple] = []

    async def active_lifecycle(self, symbol):
        return self._active

    async def persist(self, lifecycle, link):
        self.persisted.append((lifecycle, link))
        return True


def _event(index=1, *, offset_seconds=0, direction="BUY", symbol="CHFJPY"):
    return EpisodeEvent(
        pressure_event_id=f"evt-{index}",
        symbol=symbol,
        event_time_utc=START + timedelta(seconds=offset_seconds),
        transport_lifecycle_id=f"transport-{index}",
        raw_direction=direction,
        pressure_seen=True,
        pressure_event_count=3,
    )


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED", "true")
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY", "true")
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_METRICS_ENABLED", "false")


# --------------------------------------------------------------------------
# flags default to off
# --------------------------------------------------------------------------


def test_flags_default_off(monkeypatch):
    for name in (
        "STRATEGY_5SCR_LIFECYCLE_V2_ENABLED",
        "STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY",
        "STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    assert episode_lifecycle_v2_enabled() is False
    # Shadow-only is the safe default and therefore defaults ON.
    assert episode_shadow_only() is True


@pytest.mark.asyncio
async def test_disabled_worker_does_nothing(monkeypatch):
    monkeypatch.delenv("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED", raising=False)
    repository = _FakeRepository()
    worker = LifecycleShadowWorker(repository=repository)

    assert await worker.process_event(_event()) is None
    assert repository.persisted == []


@pytest.mark.asyncio
async def test_worker_refuses_when_shadow_only_is_false(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED", "true")
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY", "false")
    repository = _FakeRepository()

    assert await LifecycleShadowWorker(repository=repository).process_event(_event()) is None
    assert repository.persisted == []


def test_preflight_rejects_non_shadow_with_execution(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED", "true")
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY", "false")

    with pytest.raises(EpisodePreflightError):
        assert_episode_rollout_is_safe(execution_enabled=True)


def test_preflight_allows_shadow_with_execution(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED", "true")
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY", "true")

    assert_episode_rollout_is_safe(execution_enabled=True)


# --------------------------------------------------------------------------
# dual-write gating
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_write_off_does_not_persist(enabled, monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED", "false")
    repository = _FakeRepository()

    lifecycle = await LifecycleShadowWorker(repository=repository).process_event(_event())

    assert lifecycle is not None
    assert repository.persisted == []


@pytest.mark.asyncio
async def test_dual_write_on_persists_episode_and_link(enabled, monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED", "true")
    repository = _FakeRepository()

    await LifecycleShadowWorker(repository=repository).process_event(_event())

    assert len(repository.persisted) == 1
    lifecycle, link = repository.persisted[0]
    assert link.strategy_lifecycle_id == lifecycle.strategy_lifecycle_id
    assert link.transport_lifecycle_id == "transport-1"


# --------------------------------------------------------------------------
# restart safety
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_continues_a_recovered_episode(enabled, monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED", "false")

    first = await LifecycleShadowWorker(repository=_FakeRepository()).process_event(_event(1))

    # A fresh worker recovers the episode from the repository, as after restart.
    resumed = await LifecycleShadowWorker(repository=_FakeRepository(active=first)).process_event(
        _event(2, offset_seconds=120)
    )

    assert resumed is not None
    assert resumed.strategy_lifecycle_id == first.strategy_lifecycle_id
    assert resumed.event_count == first.event_count + 1


@pytest.mark.asyncio
async def test_restart_after_gap_opens_a_new_episode(enabled, monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED", "false")

    first = await LifecycleShadowWorker(repository=_FakeRepository()).process_event(_event(1))
    resumed = await LifecycleShadowWorker(repository=_FakeRepository(active=first)).process_event(
        _event(2, offset_seconds=1200)
    )

    assert resumed is not None
    assert resumed.strategy_lifecycle_id != first.strategy_lifecycle_id


# --------------------------------------------------------------------------
# batch metrics
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_reports_compression_without_execution_impact(enabled, monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED", "false")
    events = [_event(i, offset_seconds=i * 60) for i in range(10)]

    summary = await LifecycleShadowWorker(repository=_FakeRepository()).process_batch(events)

    assert summary["pressure_events_total"] == 10
    assert summary["strategy_lifecycles_v2_total"] == 1
    assert summary["lifecycle_v2_compression_ratio"] == pytest.approx(10.0)
    assert summary["execution_impact"] is False
    assert summary["rule_version"] == "5scr.market-episode.v1"


@pytest.mark.asyncio
async def test_batch_disabled_returns_disabled_summary(monkeypatch):
    monkeypatch.delenv("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED", raising=False)

    summary = await LifecycleShadowWorker(repository=_FakeRepository()).process_batch([_event()])

    assert summary == {"enabled": False}


# --------------------------------------------------------------------------
# outbox adapter
# --------------------------------------------------------------------------


def test_outbox_row_preserves_transport_identity():
    row = {
        "event_id": "0f9d3b1e-4c2a-4f6b-9c1d-2a5e7b8c9d01",
        "symbol": "CHFJPY",
        "lifecycle_id": "CHFJPY_20260717T130000Z_20260717T130500Z",
        "signal_valid_at": START,
        "payload": {
            "raw_direction": "BUY",
            "source_clean_block_id": "CHFJPY_20260717T130000Z_20260717T130500Z",
            "pressure_seen": True,
            "pressure_event_count": 4,
        },
    }

    event = episode_event_from_outbox_row(row)

    assert event.transport_lifecycle_id == "CHFJPY_20260717T130000Z_20260717T130500Z"
    assert event.source_clean_block_id == "CHFJPY_20260717T130000Z_20260717T130500Z"
    assert event.direction == "BUY"
    # Without this the event would read as a heartbeat and sustain nothing.
    assert event.is_continuity_evidence is True


def test_outbox_row_accepts_postgres_json_payload_as_text():
    row = {
        "event_id": "0f9d3b1e-4c2a-4f6b-9c1d-2a5e7b8c9d03",
        "symbol": "CHFJPY",
        "lifecycle_id": "transport-json-text",
        "signal_valid_at": START,
        "payload": (
            '{"raw_direction":"BUY","source_clean_block_id":"clean-json-text",'
            '"pressure_seen":true,"pressure_event_count":4}'
        ),
    }

    event = episode_event_from_outbox_row(row)

    assert event.transport_lifecycle_id == "transport-json-text"
    assert event.source_clean_block_id == "clean-json-text"
    assert event.direction == "BUY"
    assert event.is_continuity_evidence is True


@pytest.mark.parametrize("payload", ["not-json", "[]", "42"])
def test_outbox_row_rejects_payload_that_is_not_a_json_object(payload):
    row = {
        "event_id": "0f9d3b1e-4c2a-4f6b-9c1d-2a5e7b8c9d04",
        "symbol": "CHFJPY",
        "lifecycle_id": "transport-invalid-json",
        "signal_valid_at": START,
        "payload": payload,
    }

    with pytest.raises(ValueError, match="payload"):
        episode_event_from_outbox_row(row)


def test_outbox_row_without_pressure_evidence_is_not_continuity():
    row = {
        "event_id": "0f9d3b1e-4c2a-4f6b-9c1d-2a5e7b8c9d02",
        "symbol": "CHFJPY",
        "lifecycle_id": "transport-1",
        "signal_valid_at": START,
        "payload": {"raw_direction": "BUY"},
    }

    assert episode_event_from_outbox_row(row).is_continuity_evidence is False


def test_outbox_row_without_timestamp_is_rejected():
    with pytest.raises(ValueError, match="signal_valid_at"):
        episode_event_from_outbox_row(
            {"event_id": "x", "symbol": "CHFJPY", "lifecycle_id": "t", "signal_valid_at": None}
        )


def test_policy_gap_comes_from_environment(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS", "600")
    assert resolve_episode_policy().max_continuity_gap_seconds == 600

    monkeypatch.delenv("STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS", raising=False)
    assert resolve_episode_policy().max_continuity_gap_seconds == 900


def test_invalid_gap_is_rejected(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS", "not-a-number")
    with pytest.raises(EpisodePreflightError):
        resolve_episode_policy()
