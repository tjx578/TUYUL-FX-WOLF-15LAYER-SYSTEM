from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
from storage.pressure_outbox import (
    PressureOutboxRuntime,
    PressurePersistenceResult,
    prepare_pressure_event,
)
from storage.pressure_radar_manifest import PressureRadarPersistenceResult


def _persisted_result(payload: dict[str, Any]) -> PressurePersistenceResult:
    prepared = prepare_pressure_event(payload)
    stored_payload = {**prepared.payload, "lifecycle_sequence": 1}
    now = datetime(2026, 7, 20, 4, tzinfo=UTC)
    envelope = PressureOutboxEnvelope(
        outbox_id=prepared.outbox_id,
        event_id=prepared.event_id,
        schema_version=prepared.schema_version,
        symbol=prepared.symbol,
        lifecycle_id=prepared.lifecycle_id,
        lifecycle_sequence=1,
        source_clean_block_id=prepared.source_clean_block_id,
        source_watch_id=prepared.source_watch_id,
        signal_valid_at=prepared.signal_valid_at,
        payload=stored_payload,
        payload_hash=prepared.payload_hash,
        status="PENDING",
        attempt_count=0,
        available_at=now,
        created_at=now,
    )
    return PressurePersistenceResult(status="PERSISTED", envelope=envelope)


@pytest.mark.parametrize(
    ("log_enabled", "rate_allowed"),
    [(False, True), (True, False)],
)
def test_durable_write_precedes_and_is_independent_from_observability_sampling(
    monkeypatch: pytest.MonkeyPatch,
    log_enabled: bool,
    rate_allowed: bool,
) -> None:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    outcomes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pipeline,
        "_record_pressure_state_outcome",
        lambda payload, **kwargs: outcomes.append({"payload": dict(payload), **kwargs}),
    )
    monkeypatch.setattr(pipeline, "_pressure_state_log_allowed", lambda _payload: rate_allowed)
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", str(log_enabled).lower())
    persisted: list[dict[str, Any]] = []

    def _persist(payload: dict[str, Any]) -> PressurePersistenceResult:
        persisted.append(dict(payload))
        return _persisted_result(payload)

    monkeypatch.setattr("storage.pressure_outbox.persist_pressure_payload_sync", _persist)
    payload = {
        "symbol": "AUDUSD",
        "source_watch_id": "AUDUSD:watch:canonical",
        "cluster_id": "AUDUSD_CLUSTER",
        "signal_valid_time_utc": "2026-07-20T04:00:00+00:00",
        "pressure_seen": True,
        "pair_eligible_for_analysis": True,
        "promotion_stage": "PRESSURE_ONLY",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
    }

    emitted = pipeline._emit_signal_pressure_state_payload(payload)

    assert emitted is False
    assert len(persisted) == 1
    assert payload["lifecycle_sequence"] == 1
    assert payload["event_id"]
    assert payload["valid_for_execution"] is False
    assert outcomes[0]["emitted"] is False


def test_master_switch_does_not_enable_writer_without_write_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED", "false")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "false")
    monkeypatch.setattr(
        "storage.pressure_outbox.persist_pressure_payload_sync",
        lambda _payload: pytest.fail("writer must remain disabled"),
    )
    outcomes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pipeline,
        "_record_pressure_state_outcome",
        lambda payload, **kwargs: outcomes.append({"payload": dict(payload), **kwargs}),
    )

    emitted = pipeline._emit_signal_pressure_state_payload({"symbol": "AUDUSD"})

    assert emitted is False
    assert outcomes[0]["suppression_reason"] == "EMITTER_DISABLED"


def test_radar_flag_routes_pipeline_through_atomic_manifest_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_RADAR_WRITE_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "false")
    monkeypatch.setattr(
        "storage.pressure_outbox.persist_pressure_payload_sync",
        lambda _payload: pytest.fail("direct outbox writer must be bypassed in radar mode"),
    )
    captured: list[dict[str, Any]] = []

    def _persist(payload: dict[str, Any]) -> PressureRadarPersistenceResult:
        captured.append(dict(payload))
        return PressureRadarPersistenceResult(
            status="PERSISTED",
            transition="WAITING_CANONICAL_LINEAGE",
        )

    monkeypatch.setattr("storage.pressure_radar_manifest.persist_pressure_radar_payload_sync", _persist)
    monkeypatch.setattr(pipeline, "_pressure_state_log_allowed", lambda _payload: True)
    outcomes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        pipeline,
        "_record_pressure_state_outcome",
        lambda payload, **kwargs: outcomes.append({"payload": dict(payload), **kwargs}),
    )
    payload = {
        "symbol": "AUDUSD",
        "cluster_id": "AUDUSD_RADAR_CLUSTER",
        "signal_valid_time_utc": "2026-07-20T04:00:00+00:00",
        "promotion_stage": "PRESSURE_ONLY",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
    }

    emitted = pipeline._emit_signal_pressure_state_payload(payload)

    assert emitted is False
    assert len(captured) == 1
    assert captured[0]["symbol"] == "AUDUSD"
    assert outcomes[0]["suppression_reason"] == "EMITTER_DISABLED"


class _RuntimeRepository:
    is_available = True

    async def enqueue(self, payload: dict[str, Any]) -> tuple[PressureOutboxEnvelope, bool]:
        result = _persisted_result(payload)
        assert result.envelope is not None
        return result.envelope, False


def test_runtime_writer_requires_master_and_write_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED", "false")

    result = PressureOutboxRuntime().persist_sync({"symbol": "AUDUSD"})

    assert result.status == "DISABLED"


@pytest.mark.asyncio
async def test_sync_pipeline_bridge_writes_on_asyncpg_owner_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED", "true")
    runtime = PressureOutboxRuntime()
    runtime.configure(loop=asyncio.get_running_loop(), repository=_RuntimeRepository())  # type: ignore[arg-type]
    payload = {
        "symbol": "AUDUSD",
        "source_watch_id": "AUDUSD:watch:runtime",
        "cluster_id": "AUDUSD_RUNTIME_CLUSTER",
        "signal_valid_time_utc": "2026-07-20T04:00:00+00:00",
        "promotion_stage": "PRESSURE_ONLY",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
    }

    result = await asyncio.to_thread(runtime.persist_sync, payload)
    owner_loop_result = runtime.persist_sync(payload)

    assert result.status == "PERSISTED"
    assert result.envelope is not None
    assert owner_loop_result.status == "FAILED"
    assert owner_loop_result.error == "PRESSURE_OUTBOX_SYNC_BRIDGE_CALLED_ON_OWNER_LOOP"
