from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from storage.pressure_radar_manifest import (
    PressureRadarManifestRepository,
    PressureRadarPersistenceContractError,
    PressureRadarPersistenceIntegrityError,
    PressureRadarRuntime,
)

START = datetime(2026, 7, 20, 6, 51, 23, tzinfo=UTC)


def _qualifying_payload(**updates: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": "signal_pressure_state_json",
        "schema_version": "2.0-pressure-state",
        "deployment_id": "deployment-target",
        "commit_sha": "da0d1332",
        "replica_id": "replica-a",
        "cluster_id": "AUDUSD:qualifying",
        "symbol": "AUDUSD",
        "raw_direction": "BUY",
        "signal_family": "SIGNAL_THROTTLE_PRESSURE",
        "source_stage": "PRESSURE_BLOCK",
        "promotion_stage": "PRESSURE_ONLY",
        "signal_valid_time_utc": START.isoformat(),
        "generated_at_utc": (START + timedelta(seconds=1)).isoformat(),
        "raw_direction_expires_at_utc": (START + timedelta(hours=4)).isoformat(),
        "raw_direction_eligible_for_context_resolution": True,
        "current_block_effective_ticks": 3,
        "source_clean_block_id": None,
        "context_version": "pressure-context-v2:qualifying",
        "liquidity_resolution": "BUY_SIDE_APPROACHING",
        "direction_next_required_stage": "LIQUIDITY_ACCEPTANCE_OR_REJECTION",
        "next_required_stage": "MICROBOOST_OR_MARKET_CONTEXT",
        "htf_structure_context": {
            "daily_bias": "BULLISH",
            "h4_structure": "BEARISH_PULLBACK",
            "price_location": "H4_SUPPLY",
            "liquidity_resolution": "BUY_SIDE_APPROACHING",
            "daily_bias_freshness_status": "FRESH",
            "allowed_playbook": "WAIT_FOR_BUY_LOCATION",
        },
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
    }
    payload.update(updates)
    return payload


def _lineage_payload(qualifying: dict[str, Any]) -> dict[str, Any]:
    start = START.replace(microsecond=0)
    end = start + timedelta(minutes=5)
    payload = copy.deepcopy(qualifying)
    payload.update(
        {
            "cluster_id": "AUDUSD:lineage",
            "signal_valid_time_utc": (START + timedelta(minutes=6)).isoformat(),
            "generated_at_utc": (START + timedelta(minutes=6, seconds=1)).isoformat(),
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "current_block_effective_ticks": 1,
            "source_clean_block_id": (f"AUDUSD_{start.strftime('%Y%m%dT%H%M%SZ')}_{end.strftime('%Y%m%dT%H%M%SZ')}"),
            "context_version": "pressure-context-v2:lineage",
        }
    )
    return payload


class _FakeConnection:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.queries: list[str] = []
        self.fail_outbox_insert = False
        self.fail_ready_manifest = False

    async def execute(self, query: str, *args: Any) -> str:
        self.queries.append(query)
        normalized = " ".join(query.split())
        if "pg_advisory_xact_lock" in normalized:
            self.state["locks"].append(args[0])
            return "SELECT 1"
        if "INSERT INTO pressure_lifecycle_sequences" in normalized:
            self.state["sequences"].setdefault(args[0], 0)
            return "INSERT 0 1"
        if "UPDATE pressure_lifecycle_sequences" in normalized:
            self.state["sequences"][args[0]] = int(args[1])
            return "UPDATE 1"
        if "INSERT INTO pressure_radar_manifests" in normalized:
            if self.fail_ready_manifest and args[8] == "ANALYSIS_READY":
                raise ConnectionError("crash after outbox before manifest update")
            previous = self.state["manifests"].get(args[0])
            outbox_event_id = args[11] or (previous or {}).get("outbox_event_id")
            outbox_id = args[12] or (previous or {}).get("outbox_id")
            self.state["manifests"][args[0]] = {
                "manifest": json.loads(args[9]),
                "qualifying_payload": json.loads(args[10]),
                "outbox_event_id": outbox_event_id,
                "outbox_id": outbox_id,
            }
            return "INSERT 0 1"
        if "INSERT INTO pressure_radar_events" in normalized:
            self.state["radar_events"][(args[0], args[1])] = {
                "payload_hash": args[4],
                "transition": args[6],
                "manifest_id": args[7],
                "outbox_event_id": args[8],
            }
            return "INSERT 0 1"
        raise AssertionError(f"Unexpected execute query: {normalized}")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        normalized = " ".join(query.split())
        if "FROM pressure_radar_manifests" not in normalized:
            raise AssertionError(f"Unexpected fetch query: {normalized}")
        deployment_id, symbol, statuses = args
        rows: list[dict[str, Any]] = []
        for row in self.state["manifests"].values():
            manifest = row["manifest"]
            if (
                manifest["deployment_id"] == deployment_id
                and manifest["symbol"] == symbol
                and manifest["status"] in statuses
            ):
                rows.append(copy.deepcopy(row))
        return rows

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.queries.append(query)
        normalized = " ".join(query.split())
        if "FROM pressure_radar_events" in normalized:
            return copy.deepcopy(self.state["radar_events"].get((args[0], args[1])))
        if "FROM pressure_radar_manifests" in normalized:
            return copy.deepcopy(self.state["manifests"].get(args[0]))
        if "SELECT last_sequence" in normalized:
            return {"last_sequence": self.state["sequences"].get(args[0], 0)}
        if "FROM pressure_outbox WHERE event_id" in normalized:
            return copy.deepcopy(self.state["outbox_events"].get(args[0]))
        if "INSERT INTO pressure_outbox" in normalized:
            if self.fail_outbox_insert:
                raise ConnectionError("crash during outbox insert")
            now = datetime(2026, 7, 20, 7, tzinfo=UTC)
            row = {
                "id": args[0],
                "event_id": args[1],
                "event_type": "signal_pressure_state_json",
                "schema_version": args[2],
                "symbol": args[3],
                "lifecycle_id": args[4],
                "lifecycle_sequence": args[5],
                "source_clean_block_id": args[6],
                "source_watch_id": args[7],
                "signal_valid_at": args[8],
                "payload": json.loads(args[9]),
                "payload_hash": args[10],
                "status": "PENDING",
                "attempt_count": 0,
                "available_at": now,
                "locked_at": None,
                "lease_expires_at": None,
                "published_at": None,
                "created_at": now,
            }
            self.state["outbox_events"][args[1]] = row
            return copy.deepcopy(row)
        raise AssertionError(f"Unexpected fetchrow query: {normalized}")


class _FakePostgres:
    def __init__(self) -> None:
        self.is_available = True
        self.state: dict[str, Any] = {
            "manifests": {},
            "radar_events": {},
            "sequences": {},
            "outbox_events": {},
            "locks": [],
        }
        self.conn = _FakeConnection(self.state)
        self.raise_after_commit_once = False
        self.transaction_lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_FakeConnection]:
        async with self.transaction_lock:
            snapshot = copy.deepcopy(self.state)
            try:
                yield self.conn
            except Exception:
                self.state.clear()
                self.state.update(snapshot)
                raise
            if self.raise_after_commit_once:
                self.raise_after_commit_once = False
                raise ConnectionError("connection lost after commit before acknowledgement")

    async def fetch(self, query: str, *_: Any) -> list[dict[str, str]]:
        if "pg_catalog.pg_tables" in query:
            return [
                {"tablename": "pressure_radar_manifests"},
                {"tablename": "pressure_radar_events"},
            ]
        return [
            {"indexname": "ix_pressure_radar_manifest_active"},
            {"indexname": "ix_pressure_radar_manifest_expiry"},
            {"indexname": "ix_pressure_radar_event_manifest"},
        ]


def _repository(pg: _FakePostgres) -> PressureRadarManifestRepository:
    return PressureRadarManifestRepository(pg=cast(Any, pg))


@pytest.mark.asyncio
async def test_waiting_manifest_then_lineage_atomically_enqueues_non_executable_event() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    qualifying = _qualifying_payload()

    waiting = await repository.ingest(qualifying)
    ready = await repository.ingest(_lineage_payload(qualifying))

    assert waiting.transition == "WAITING_CANONICAL_LINEAGE"
    assert waiting.envelope is None
    assert waiting.manifest is not None
    assert waiting.manifest.status == "WAITING_CANONICAL_LINEAGE"
    assert ready.transition == "ANALYSIS_READY"
    assert ready.manifest is not None
    assert ready.manifest.status == "ANALYSIS_READY"
    assert ready.envelope is not None
    assert ready.envelope.payload["radar_manifest_id"] == ready.manifest.manifest_id
    assert ready.envelope.payload["pressure_selection_confirmed"] is True
    assert ready.envelope.payload["lifecycle_anchor_at_utc"] == START.isoformat()
    assert ready.envelope.signal_valid_at == START + timedelta(minutes=6, seconds=1)
    assert ready.envelope.payload["final_direction"] == "WAIT"
    assert ready.envelope.payload["valid_for_execution"] is False
    assert ready.envelope.payload["is_final_signal"] is False
    assert ready.envelope.lifecycle_sequence == 1
    stored = pg.state["manifests"][ready.manifest.manifest_id]
    assert stored["outbox_event_id"] == ready.envelope.event_id
    assert len(pg.state["outbox_events"]) == 1
    assert pg.state["locks"] == [
        "pressure-radar|deployment-target|AUDUSD",
        "pressure-radar|deployment-target|AUDUSD",
    ]
    assert any("FOR UPDATE" in query for query in pg.conn.queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["outbox", "ready_manifest"])
async def test_atomic_rollback_covers_outbox_and_ready_manifest(failure_point: str) -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    qualifying = _qualifying_payload()
    waiting = await repository.ingest(qualifying)
    assert waiting.manifest is not None
    before = copy.deepcopy(pg.state)
    pg.conn.fail_outbox_insert = failure_point == "outbox"
    pg.conn.fail_ready_manifest = failure_point == "ready_manifest"

    with pytest.raises(ConnectionError):
        await repository.ingest(_lineage_payload(qualifying))

    assert pg.state == before
    assert pg.state["manifests"][waiting.manifest.manifest_id]["manifest"]["status"] == ("WAITING_CANONICAL_LINEAGE")


@pytest.mark.asyncio
async def test_retry_after_commit_before_ack_is_duplicate_and_returns_same_outbox() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    qualifying = _qualifying_payload()
    lineage = _lineage_payload(qualifying)
    await repository.ingest(qualifying)
    pg.raise_after_commit_once = True

    with pytest.raises(ConnectionError, match="after commit"):
        await repository.ingest(lineage)

    retry = await repository.ingest(lineage)

    assert retry.duplicate is True
    assert retry.transition == "ANALYSIS_READY"
    assert retry.envelope is not None
    assert retry.envelope.lifecycle_sequence == 1
    assert len(pg.state["outbox_events"]) == 1
    assert next(iter(pg.state["sequences"].values())) == 1


@pytest.mark.asyncio
async def test_two_workers_ingesting_same_event_produce_one_manifest() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    payload = _qualifying_payload()

    first, second = await asyncio.gather(
        repository.ingest(payload),
        repository.ingest(payload),
    )

    assert sorted((first.duplicate, second.duplicate)) == [False, True]
    assert len(pg.state["manifests"]) == 1
    assert len(pg.state["radar_events"]) == 1
    assert len(pg.state["outbox_events"]) == 0
    assert pg.state["locks"] == [
        "pressure-radar|deployment-target|AUDUSD",
        "pressure-radar|deployment-target|AUDUSD",
    ]


@pytest.mark.asyncio
async def test_duplicate_event_with_changed_content_fails_integrity_check() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    event_id = "b0a3aaf0-0f69-4e91-8b46-68b93618f320"
    payload = _qualifying_payload(event_id=event_id)
    await repository.ingest(payload)

    with pytest.raises(PressureRadarPersistenceIntegrityError, match="EVENT_ID_HASH_MISMATCH"):
        await repository.ingest({**payload, "replica_id": "replica-b"})


@pytest.mark.asyncio
async def test_missing_deployment_is_rejected_before_transaction() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    payload = _qualifying_payload()
    payload.pop("deployment_id")

    with pytest.raises(PressureRadarPersistenceContractError, match="DEPLOYMENT_ID_MISSING"):
        await repository.ingest(payload)

    assert pg.state["locks"] == []


def test_radar_runtime_requires_its_own_granular_write_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_RADAR_WRITE_ENABLED", "false")

    result = PressureRadarRuntime().persist_sync(_qualifying_payload())

    assert result.status == "DISABLED"
    assert result.envelope is None


@pytest.mark.asyncio
async def test_radar_schema_status_requires_both_tables_and_all_indexes() -> None:
    status = await _repository(_FakePostgres()).schema_status()

    assert status.ready is True
    assert status.missing_tables == ()
    assert status.missing_indexes == ()


def test_migration_preserves_non_executable_and_atomic_ready_constraints() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "migrations"
        / "versions"
        / "20260720_02_pressure_radar_manifests.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "20260720_02"' in migration
    assert 'down_revision = "20260720_01"' in migration
    assert "ck_pressure_radar_non_executable" in migration
    assert "ck_pressure_radar_ready_outbox" in migration
    assert "pressure_radar_events" in migration
    assert "pressure_radar_manifests" in migration
