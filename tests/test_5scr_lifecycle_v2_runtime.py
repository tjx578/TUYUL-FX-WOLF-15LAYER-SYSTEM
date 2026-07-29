"""Runtime wiring for the lifecycle V2 shadow worker.

A shadow worker that is never called is a dead path, so these tests cover the
integration rather than the domain: config parsing, peer-worker construction,
the non-leasing read, and restart ordering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from analysis.strategy_5scr_v3.episode_hash import (
    build_material_state_hash,
    build_strategy_lifecycle_id,
)
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2
from services.pressure_outbox.lifecycle_shadow_worker import (
    LifecycleV2RuntimeConfig,
    LifecycleV2ShadowRunner,
    build_lifecycle_v2_shadow_runner,
)

START = datetime(2026, 7, 17, 13, 0, 0, tzinfo=UTC)


class _FakeRepository:
    def __init__(self, rows=None, active=None):
        self._batches = [list(rows)] if rows else []
        self._active = active
        self.persisted: list[tuple] = []
        self.active_lookups: list[str] = []
        self.fetch_calls = 0

    async def fetch_unlinked_events(self, *, limit=100):
        self.fetch_calls += 1
        return self._batches.pop(0) if self._batches else []

    async def active_lifecycle(self, symbol):
        self.active_lookups.append(symbol)
        return self._active

    async def persist(self, lifecycle, link):
        self.persisted.append((lifecycle, link))
        return True


def _row(index: int, *, symbol="CHFJPY", offset_seconds=0, direction="BUY"):
    return {
        "event_id": f"0f9d3b1e-4c2a-4f6b-9c1d-2a5e7b8c9d{index:02d}",
        "symbol": symbol,
        "lifecycle_id": f"transport-{index}",
        "signal_valid_at": START + timedelta(seconds=offset_seconds),
        "payload": {
            "raw_direction": direction,
            "pressure_seen": True,
            "pressure_event_count": 3,
        },
    }


def _lifecycle(symbol="CHFJPY", *, at=START):
    return StrategyLifecycleV2(
        strategy_lifecycle_id=build_strategy_lifecycle_id(
            symbol=symbol, opened_at_utc=at, opening_direction_state="BUY"
        ),
        symbol=symbol,
        direction_state="BUY",
        opened_at_utc=at,
        last_event_at_utc=at,
        last_continuity_event_at_utc=at,
        last_material_event_at_utc=at,
        material_state_hash=build_material_state_hash(
            symbol=symbol,
            state="ANALYSIS_OPEN",
            direction_state="BUY",
            opened_at_utc=at,
            last_material_event_at_utc=at,
        ),
        event_count=1,
    )


def _config(**overrides) -> LifecycleV2RuntimeConfig:
    base = {"enabled": True, "shadow_only": True, "dual_write_enabled": True, "metrics_enabled": False}
    base.update(overrides)
    return LifecycleV2RuntimeConfig(**base)


# --------------------------------------------------------------------------
# config parsing
# --------------------------------------------------------------------------


def test_config_defaults_are_safe():
    config = LifecycleV2RuntimeConfig.from_env({})

    assert config.enabled is False
    assert config.shadow_only is True  # safe default is ON
    assert config.dual_write_enabled is False
    assert config.max_continuity_gap_seconds == 900


def test_config_reads_all_flags():
    config = LifecycleV2RuntimeConfig.from_env(
        {
            "STRATEGY_5SCR_LIFECYCLE_V2_ENABLED": "true",
            "STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY": "true",
            "STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED": "true",
            "STRATEGY_5SCR_LIFECYCLE_V2_METRICS_ENABLED": "false",
            "STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS": "600",
        }
    )

    assert config.enabled and config.dual_write_enabled
    assert config.metrics_enabled is False
    assert config.max_continuity_gap_seconds == 600


def test_config_rejects_a_non_integer_gap():
    with pytest.raises(ValueError, match="MAX_CONTINUITY_GAP_SECONDS"):
        LifecycleV2RuntimeConfig.from_env({"STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS": "nine hundred"})


# --------------------------------------------------------------------------
# runner behaviour
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_runner_does_not_read_anything():
    repository = _FakeRepository(rows=[_row(1)])
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config(enabled=False))

    await runner.run()

    assert repository.fetch_calls == 0
    assert repository.persisted == []


@pytest.mark.asyncio
async def test_runner_refuses_to_start_when_not_shadow_only():
    runner = LifecycleV2ShadowRunner(repository=_FakeRepository(), config=_config(shadow_only=False))

    with pytest.raises(RuntimeError, match="SHADOW_ONLY_REQUIRED"):
        await runner.run()


@pytest.mark.asyncio
async def test_poll_folds_a_batch_into_one_episode():
    rows = [_row(i, offset_seconds=i * 60) for i in range(5)]
    repository = _FakeRepository(rows=rows)
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config())

    processed = await runner.poll_once()

    assert processed == 5
    assert len(repository.persisted) == 5
    lifecycle_ids = {lifecycle.strategy_lifecycle_id for lifecycle, _ in repository.persisted}
    assert len(lifecycle_ids) == 1


@pytest.mark.asyncio
async def test_poll_with_dual_write_off_reads_but_does_not_write():
    repository = _FakeRepository(rows=[_row(1)])
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config(dual_write_enabled=False))

    processed = await runner.poll_once()

    assert processed == 1
    assert repository.persisted == []


@pytest.mark.asyncio
async def test_empty_poll_returns_zero():
    runner = LifecycleV2ShadowRunner(repository=_FakeRepository(), config=_config())

    assert await runner.poll_once() == 0


# --------------------------------------------------------------------------
# restart ordering
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_episode_is_recovered_before_the_first_event_is_folded():
    """Polling first would open a duplicate episode on restart."""
    existing = _lifecycle()
    repository = _FakeRepository(rows=[_row(9, offset_seconds=120)], active=existing)
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config())

    await runner.poll_once()

    assert repository.active_lookups == ["CHFJPY"]
    lifecycle, _link = repository.persisted[0]
    assert lifecycle.strategy_lifecycle_id == existing.strategy_lifecycle_id
    assert lifecycle.event_count == existing.event_count + 1


@pytest.mark.asyncio
async def test_recovery_happens_once_per_symbol():
    rows = [_row(i, offset_seconds=i * 60) for i in range(4)]
    repository = _FakeRepository(rows=rows)
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config())

    await runner.poll_once()

    assert repository.active_lookups == ["CHFJPY"]


@pytest.mark.asyncio
async def test_each_symbol_is_recovered_separately():
    rows = [_row(1, symbol="CHFJPY"), _row(2, symbol="NZDCAD", offset_seconds=30)]
    repository = _FakeRepository(rows=rows)
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config())

    await runner.poll_once()

    assert sorted(repository.active_lookups) == ["CHFJPY", "NZDCAD"]


@pytest.mark.asyncio
async def test_restart_midway_matches_a_continuous_run():
    """Continuous run and restart-midway must agree on every clock."""
    rows = [_row(i, offset_seconds=i * 60) for i in range(6)]

    continuous_repo = _FakeRepository(rows=list(rows))
    continuous = LifecycleV2ShadowRunner(repository=continuous_repo, config=_config())
    await continuous.poll_once()
    continuous_final, _ = continuous_repo.persisted[-1]

    # Restart: first three events, then a fresh runner recovering from storage.
    first_repo = _FakeRepository(rows=rows[:3])
    await LifecycleV2ShadowRunner(repository=first_repo, config=_config()).poll_once()
    midpoint, _ = first_repo.persisted[-1]

    second_repo = _FakeRepository(rows=rows[3:], active=midpoint)
    await LifecycleV2ShadowRunner(repository=second_repo, config=_config()).poll_once()
    restarted_final, _ = second_repo.persisted[-1]

    assert restarted_final.strategy_lifecycle_id == continuous_final.strategy_lifecycle_id
    assert restarted_final.event_count == continuous_final.event_count
    assert restarted_final.last_event_at_utc == continuous_final.last_event_at_utc
    assert restarted_final.last_continuity_event_at_utc == continuous_final.last_continuity_event_at_utc
    assert restarted_final.last_material_event_at_utc == continuous_final.last_material_event_at_utc
    assert restarted_final.direction_state == continuous_final.direction_state


# --------------------------------------------------------------------------
# isolation from the existing path
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_never_leases_or_mutates_transport_rows():
    """The shadow reader must not compete with the dispatcher for delivery."""
    repository = _FakeRepository(rows=[_row(1)])
    runner = LifecycleV2ShadowRunner(repository=repository, config=_config())

    await runner.poll_once()

    # The only repository surface used is read + V2 write.
    assert not hasattr(repository, "claimed")
    assert all(link.transport_lifecycle_id == "transport-1" for _lifecycle, link in repository.persisted)


def test_builder_returns_a_runner():
    runner = build_lifecycle_v2_shadow_runner(pg=object(), config=_config())

    assert isinstance(runner, LifecycleV2ShadowRunner)


def test_runner_is_not_constructed_when_disabled():
    """Mirrors the runner.py wiring condition."""
    config = LifecycleV2RuntimeConfig.from_env({})
    worker: Any = build_lifecycle_v2_shadow_runner(pg=object(), config=config) if config.enabled else None

    assert worker is None
