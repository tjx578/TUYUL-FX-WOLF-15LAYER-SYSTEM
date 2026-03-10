# pyright: reportPrivateUsage=false
"""
Integration-style tests for storage/persistence_sync.py — PersistenceSync.

Uses in-memory mocks for both Redis and PostgreSQL, but exercises the full
sync logic (Redis → PG write-behind, PG → Redis recovery) without mocking
internal methods. This validates state survives a "restart" scenario:

1. Write drawdown/CB state to mock Redis.
2. Run sync cycle → verify PG received snapshots.
3. Clear Redis (simulate container restart).
4. Run recover_from_postgres → verify Redis state restored.
5. Verify trade ledger upsert round-trip.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from storage.persistence_sync import PersistenceSync

# ──────────────────────────────────────────────────────────────────
#  In-memory Redis mock (sync interface matching storage.redis_client)
# ──────────────────────────────────────────────────────────────────

class FakeRedis:
    """In-memory dict-backed Redis mock with scan support."""

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[str, str] = {}
        # Expose .client for stream scan operations
        self.client: FakeRedis = self

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0

    def scan(self, cursor: int = 0, match: str = "*", count: int = 50):
        """Simplified scan: return all matching keys in a single pass."""
        import fnmatch
        matched = [k for k in self._store if fnmatch.fnmatch(k, match)]
        return (0, matched)  # cursor=0 means done

    def clear(self) -> None:
        self._store.clear()

    def dump(self) -> dict[str, str]:
        return dict(self._store)


# ──────────────────────────────────────────────────────────────────
#  In-memory PostgreSQL mock (async interface matching PostgresClient)
# ──────────────────────────────────────────────────────────────────

class FakePostgres:
    """In-memory async PG mock that stores INSERT data and supports queries."""

    def __init__(self) -> None:
        self.is_available: bool = True
        self._tables: dict[str, list[dict[str, Any]]] = {
            "risk_snapshots": [],
            "trade_history": [],
            "system_events": [],
        }

    async def execute(self, query: str, *args: Any) -> None:
        query_lower = query.strip().lower()
        if "risk_snapshots" in query_lower and "insert" in query_lower:
            self._tables["risk_snapshots"].append({
                "snapshot_type": args[0],
                "account_id": args[1],
                "state_data": args[2],
                "created_at": args[3],
            })
        elif "trade_history" in query_lower and "insert" in query_lower:
            self._tables["trade_history"].append({
                "trade_id": args[0],
                "signal_id": args[1],
                "account_id": args[2],
                "pair": args[3],
                "direction": args[4],
                "status": args[5],
                "risk_mode": args[6],
                "total_risk_percent": args[7],
                "total_risk_amount": args[8],
                "pnl": args[9],
                "close_reason": args[10],
                "legs": args[11],
                "metadata": args[12],
                "created_at": args[13],
                "updated_at": args[14],
                "closed_at": args[15],
            })
        elif "system_events" in query_lower and "insert" in query_lower:
            self._tables["system_events"].append({
                "event_type": args[0],
                "account_id": args[1],
                "severity": args[2],
                "payload": args[3],
            })

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        query_lower = query.strip().lower()
        if "risk_snapshots" in query_lower:
            snapshot_type = None
            if "drawdown" in query_lower:
                snapshot_type = "DRAWDOWN"
            elif "circuit_breaker" in query_lower:
                snapshot_type = "CIRCUIT_BREAKER"
            rows = [
                r for r in self._tables["risk_snapshots"]
                if r["snapshot_type"] == snapshot_type
            ]
            if rows:
                return rows[-1]  # latest
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        query_lower = query.strip().lower()
        if "trade_history" in query_lower:
            return [
                t for t in self._tables["trade_history"]
                if t.get("status") not in ("CLOSED", "CANCELLED", "SKIPPED", "ABORTED")
            ]
        return []


# ──────────────────────────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def fake_pg() -> FakePostgres:
    return FakePostgres()


@pytest.fixture
def sync_service(fake_redis: FakeRedis, fake_pg: FakePostgres) -> PersistenceSync:
    return PersistenceSync(interval_sec=1.0, pg=fake_pg, redis=fake_redis)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────
#  Drawdown state round-trip
# ──────────────────────────────────────────────────────────────────

class TestDrawdownPersistence:
    @pytest.mark.asyncio
    async def test_sync_writes_drawdown_to_pg(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        """Drawdown state in Redis is captured into PG risk_snapshots."""
        fake_redis.set("wolf15:drawdown:daily", "150.0")
        fake_redis.set("wolf15:drawdown:weekly", "300.0")
        fake_redis.set("wolf15:drawdown:total", "500.0")
        fake_redis.set("wolf15:peak_equity", "105000.0")

        await sync_service._sync_risk_snapshots()

        rows = fake_pg._tables["risk_snapshots"]
        dd_rows = [r for r in rows if r["snapshot_type"] == "DRAWDOWN"]
        assert len(dd_rows) == 1

        data = json.loads(dd_rows[0]["state_data"])
        assert data["daily_dd"] == 150.0
        assert data["weekly_dd"] == 300.0
        assert data["total_dd"] == 500.0
        assert data["peak_equity"] == 105_000.0

    @pytest.mark.asyncio
    async def test_recovery_restores_drawdown_to_redis(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync,
    ) -> None:
        """After PG has a snapshot, clearing Redis and recovering restores state."""
        # Step 1: Seed Redis and sync to PG
        fake_redis.set("wolf15:drawdown:daily", "200.0")
        fake_redis.set("wolf15:drawdown:weekly", "400.0")
        fake_redis.set("wolf15:drawdown:total", "600.0")
        fake_redis.set("wolf15:peak_equity", "110000.0")
        await sync_service._sync_risk_snapshots()

        # Step 2: Wipe Redis (simulate container restart)
        fake_redis.clear()
        assert fake_redis.get("wolf15:drawdown:daily") is None

        # Step 3: Recover
        ok = await sync_service.recover_from_postgres()
        assert ok is True

        # Step 4: Verify
        assert fake_redis.get("wolf15:drawdown:daily") == "200.0"
        assert fake_redis.get("wolf15:drawdown:weekly") == "400.0"
        assert fake_redis.get("wolf15:drawdown:total") == "600.0"
        assert fake_redis.get("wolf15:peak_equity") == "110000.0"


# ──────────────────────────────────────────────────────────────────
#  Circuit breaker state round-trip
# ──────────────────────────────────────────────────────────────────

class TestCircuitBreakerPersistence:
    @pytest.mark.asyncio
    async def test_sync_writes_cb_to_pg(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        fake_redis.set("wolf15:circuit_breaker:state", "OPEN")
        fake_redis.set("wolf15:circuit_breaker:data", "loss_streak|3")
        fake_redis.set("wolf15:consecutive_losses", "3")

        await sync_service._sync_risk_snapshots()

        cb_rows = [
            r for r in fake_pg._tables["risk_snapshots"]
            if r["snapshot_type"] == "CIRCUIT_BREAKER"
        ]
        assert len(cb_rows) == 1
        data = json.loads(cb_rows[0]["state_data"])
        assert data["state"] == "OPEN"
        assert data["consecutive_losses"] == 3

    @pytest.mark.asyncio
    async def test_recovery_restores_cb_to_redis(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync,
    ) -> None:
        fake_redis.set("wolf15:circuit_breaker:state", "HALF_OPEN")
        fake_redis.set("wolf15:circuit_breaker:data", "cooldown|1")
        fake_redis.set("wolf15:consecutive_losses", "2")
        await sync_service._sync_risk_snapshots()

        fake_redis.clear()
        await sync_service.recover_from_postgres()

        assert fake_redis.get("wolf15:circuit_breaker:state") == "HALF_OPEN"
        assert fake_redis.get("wolf15:consecutive_losses") == "2"


# ──────────────────────────────────────────────────────────────────
#  Trade ledger round-trip
# ──────────────────────────────────────────────────────────────────

class TestTradeLedger:
    @pytest.mark.asyncio
    async def test_trade_synced_to_pg(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        trade: dict[str, str | float | list[dict[str, Any]] | dict[str, Any] | None] = {
            "trade_id": "T-001",
            "signal_id": "SIG-001",
            "account_id": "acct-1",
            "pair": "EURUSD",
            "direction": "BUY",
            "status": "FILLED",
            "risk_mode": "STANDARD",
            "total_risk_percent": 1.0,
            "total_risk_amount": 500.0,
            "pnl": None,
            "close_reason": None,
            "legs": [],
            "metadata": {},
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "closed_at": None,
        }
        fake_redis.set("wolf15:TRADE:T-001", json.dumps(trade))

        await sync_service._sync_trade_ledger()

        rows = fake_pg._tables["trade_history"]
        assert len(rows) == 1
        assert rows[0]["trade_id"] == "T-001"
        assert rows[0]["pair"] == "EURUSD"
        assert rows[0]["direction"] == "BUY"

    @pytest.mark.asyncio
    async def test_trade_recovery_to_redis(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        """Active trades in PG are restored to Redis on recovery."""
        # Seed a trade via sync
        trade: dict[str, str | float | list[dict[str, Any]] | dict[str, Any] | None] = {
            "trade_id": "T-002",
            "signal_id": "SIG-002",
            "account_id": "acct-1",
            "pair": "GBPUSD",
            "direction": "SELL",
            "status": "FILLED",
            "risk_mode": "STANDARD",
            "total_risk_percent": 0.5,
            "total_risk_amount": 250.0,
            "pnl": None,
            "close_reason": None,
            "legs": [],
            "metadata": {},
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "closed_at": None,
        }
        fake_redis.set("wolf15:TRADE:T-002", json.dumps(trade))
        await sync_service._sync_trade_ledger()

        # Wipe Redis and recover
        fake_redis.clear()
        # Need drawdown snapshot for recover to not fail
        fake_redis.set("wolf15:drawdown:daily", "0.0")

        ok = await sync_service.recover_from_postgres()
        assert ok is True

        # Active trade should be restored
        restored = fake_redis.get("wolf15:TRADE:T-002")
        assert restored is not None
        data = json.loads(restored)
        assert data["pair"] == "GBPUSD"


# ──────────────────────────────────────────────────────────────────
#  Empty state handling
# ──────────────────────────────────────────────────────────────────

class TestEmptyState:
    @pytest.mark.asyncio
    async def test_sync_with_empty_redis(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        """Sync cycle with no data in Redis should not crash or write garbage."""
        await sync_service._sync_risk_snapshots()
        await sync_service._sync_trade_ledger()
        # No snapshots should be written when Redis is empty
        assert len(fake_pg._tables["risk_snapshots"]) == 0
        assert len(fake_pg._tables["trade_history"]) == 0

    @pytest.mark.asyncio
    async def test_recovery_with_empty_pg(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        """Recovery with no PG data should not crash and return True."""
        ok = await sync_service.recover_from_postgres()
        assert ok is True

    @pytest.mark.asyncio
    async def test_recovery_with_pg_unavailable(
        self, fake_pg: FakePostgres, fake_redis: FakeRedis, sync_service: PersistenceSync
    ) -> None:
        """Recovery returns False when PG is not available."""
        fake_pg.is_available = False
        ok = await sync_service.recover_from_postgres()
        assert ok is False


# ──────────────────────────────────────────────────────────────────
#  System events
# ──────────────────────────────────────────────────────────────────

class TestSystemEvents:
    @pytest.mark.asyncio
    async def test_log_event_writes_to_pg(
        self, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        await sync_service.log_event(
            "CIRCUIT_BREAKER_OPENED",
            account_id="acct-1",
            severity="CRITICAL",
            payload={"consecutive_losses": 5},
        )
        events = fake_pg._tables["system_events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "CIRCUIT_BREAKER_OPENED"
        assert events[0]["severity"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_log_event_skips_when_pg_unavailable(
        self, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        fake_pg.is_available = False
        await sync_service.log_event("TEST_EVENT")
        assert len(fake_pg._tables["system_events"]) == 0


# ──────────────────────────────────────────────────────────────────
#  Run loop
# ──────────────────────────────────────────────────────────────────

class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_stops_on_stop(
        self, fake_redis: FakeRedis, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        """run() loop exits after stop() is called."""
        fake_redis.set("wolf15:drawdown:daily", "100.0")
        fake_redis.set("wolf15:peak_equity", "50000.0")

        async def stop_after_delay():
            await asyncio.sleep(0.1)
            await sync_service.stop()

        task = asyncio.create_task(sync_service.run())
        await stop_after_delay()
        await asyncio.wait_for(task, timeout=3.0)

        # At least one sync should have happened
        assert len(fake_pg._tables["risk_snapshots"]) >= 1

    @pytest.mark.asyncio
    async def test_run_skips_when_pg_unavailable(
        self, fake_pg: FakePostgres, sync_service: PersistenceSync
    ) -> None:
        """run() exits immediately when PG is not available."""
        fake_pg.is_available = False
        await sync_service.run()  # should return immediately
