"""Durable, fail-closed governance for the external MT5 executor bridge."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from contracts.mt5_execution_protocol import ExecutorMode
from storage.postgres_client import PostgresClient, pg_client


class ExecutorGovernanceError(RuntimeError):
    pass


class GovernanceNotReadyError(ExecutorGovernanceError):
    pass


class GovernanceConflictError(ExecutorGovernanceError):
    pass


class ModeTransitionError(ExecutorGovernanceError):
    pass


@dataclass(frozen=True, slots=True)
class GovernanceSnapshot:
    kill_switch_active: bool
    kill_switch_reason: str
    governance_version: int
    executor_id: str | None = None
    execution_mode: str | None = None
    mode_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_text(value: str, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ExecutorGovernanceError(f"{field} must not be blank")
    return resolved


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


async def acquire_executor_advisory_locks(connection: Any, executor_ids: Any) -> tuple[str, ...]:
    """Serialize executor lifecycle mutations before any row lock is taken."""

    normalized = tuple(sorted({str(UUID(str(executor_id))) for executor_id in executor_ids}))
    for executor_id in normalized:
        await connection.execute(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended('wolf15:mt5-executor:' || $1::text, 0)
            )
            """,
            executor_id,
        )
    return normalized


async def acquire_canary_lifecycle_advisory_locks(
    connection: Any,
    executor_ids: Any = (),
) -> tuple[str, ...]:
    """Take the global canary lock before deterministic executor locks."""

    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('wolf15:mt5-canary-lifecycle', 0))")
    return await acquire_executor_advisory_locks(connection, executor_ids)


class MT5ExecutorGovernanceRepository:
    """Owns operator mutations and governance snapshots in PostgreSQL."""

    def __init__(self, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    def _require_database(self) -> None:
        if not self._pg.is_available:
            raise GovernanceNotReadyError("PostgreSQL is required for executor governance")

    async def schema_status(self) -> dict[str, Any]:
        """Prove the minimum schema contract used by fail-closed delivery."""

        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT
                to_regclass('public.executor_bridge_governance') IS NOT NULL AS governance_table,
                to_regclass('public.executor_governance_audit') IS NOT NULL AS audit_table,
                EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'executor_instances'
                      AND column_name = 'mode_version' AND is_nullable = 'NO'
                ) AS mode_version_column,
                EXISTS (
                    SELECT 1 FROM pg_trigger AS t
                    JOIN pg_class AS c ON c.oid = t.tgrelid
                    JOIN pg_namespace AS n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'executor_governance_audit'
                      AND t.tgname = 'trg_executor_governance_audit_immutable'
                      AND t.tgenabled <> 'D'
                      AND NOT t.tgisinternal
                ) AS immutable_audit_trigger
            """
        )
        if not row:
            return {"ready": False, "reason": "schema status query returned no row"}
        details = dict(row)
        singleton_row = False
        if bool(details["governance_table"]):
            singleton = await self._pg.fetchrow(
                "SELECT EXISTS (SELECT 1 FROM executor_bridge_governance WHERE singleton_id = 1) AS present"
            )
            singleton_row = bool(singleton and singleton["present"])
        details["singleton_row"] = singleton_row
        return {"ready": all(bool(value) for value in details.values()), **details}

    async def global_snapshot(self) -> GovernanceSnapshot:
        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT kill_switch_active, kill_switch_reason, governance_version
            FROM executor_bridge_governance
            WHERE singleton_id = 1
            """
        )
        if not row:
            raise GovernanceNotReadyError("executor governance singleton is missing")
        return GovernanceSnapshot(
            kill_switch_active=bool(row["kill_switch_active"]),
            kill_switch_reason=str(row["kill_switch_reason"]),
            governance_version=int(row["governance_version"]),
        )

    async def executor_snapshot(self, executor_id: UUID | str) -> GovernanceSnapshot:
        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT g.kill_switch_active, g.kill_switch_reason, g.governance_version,
                   e.executor_id, e.execution_mode, e.mode_version
            FROM executor_bridge_governance AS g
            JOIN executor_instances AS e ON e.executor_id = $1::uuid
            WHERE g.singleton_id = 1 AND e.revoked_at IS NULL
            """,
            str(executor_id),
        )
        if not row:
            raise GovernanceNotReadyError("executor governance state is missing")
        return GovernanceSnapshot(
            kill_switch_active=bool(row["kill_switch_active"]),
            kill_switch_reason=str(row["kill_switch_reason"]),
            governance_version=int(row["governance_version"]),
            executor_id=str(row["executor_id"]),
            execution_mode=str(row["execution_mode"]),
            mode_version=int(row["mode_version"]),
        )

    async def set_kill_switch(
        self,
        *,
        active: bool,
        actor: str,
        reason: str,
        expected_version: int | None = None,
    ) -> GovernanceSnapshot:
        self._require_database()
        actor = _required_text(actor, "actor")
        reason = _required_text(reason, "reason")
        async with self._pg.transaction() as connection:
            await acquire_canary_lifecycle_advisory_locks(connection)
            row = await connection.fetchrow(
                """
                SELECT kill_switch_active, kill_switch_reason, governance_version
                FROM executor_bridge_governance
                WHERE singleton_id = 1
                FOR UPDATE
                """
            )
            if not row:
                raise GovernanceNotReadyError("executor governance singleton is missing")
            version = int(row["governance_version"])
            if expected_version is not None and version != expected_version:
                raise GovernanceConflictError(
                    f"stale governance version: expected {expected_version}, current {version}"
                )
            previous = {
                "kill_switch_active": bool(row["kill_switch_active"]),
                "kill_switch_reason": str(row["kill_switch_reason"]),
                "governance_version": version,
            }
            updated = await connection.fetchrow(
                """
                UPDATE executor_bridge_governance
                SET kill_switch_active = $1, kill_switch_reason = $2,
                    governance_version = governance_version + 1,
                    updated_by = $3, updated_at = now()
                WHERE singleton_id = 1
                RETURNING kill_switch_active, kill_switch_reason, governance_version
                """,
                active,
                reason,
                actor,
            )
            if active:
                expired = await connection.fetchrow(
                    """
                    WITH changed AS (
                        UPDATE execution_commands
                        SET state = 'EXPIRED', terminal_at = now(), updated_at = now()
                        WHERE (
                                state = 'QUEUED'
                                AND payload #>> '{executor_binding,execution_mode}' <> 'SHADOW'
                              )
                           OR (
                                state = 'CLAIMED'
                                AND source_event = 'ENGINEERING_DEMO_CANARY'
                              )
                        RETURNING 1
                    )
                    SELECT count(*) AS count FROM changed
                    """
                )
                claimed = await connection.fetchrow(
                    """
                    SELECT count(*) AS count
                    FROM execution_commands
                    WHERE state = 'CLAIMED'
                      AND payload #>> '{executor_binding,execution_mode}' <> 'SHADOW'
                    """
                )
                canary_table = await connection.fetchval("SELECT to_regclass('public.engineering_demo_canary_windows')")
                if canary_table is not None:
                    reconciliation = await connection.fetchrow(
                        """
                        WITH changed AS (
                            UPDATE engineering_demo_canary_windows AS w
                            SET state='RECONCILIATION_REQUIRED', terminal_at=NULL, updated_at=now()
                            FROM execution_commands AS c
                            WHERE c.command_id=w.command_id
                              AND c.state IN ('SUBMITTING','BROKER_ACCEPTED','ACTIVE','AMBIGUOUS')
                              AND w.state IN ('ARMED','RECONCILIATION_REQUIRED')
                            RETURNING 1
                        )
                        SELECT count(*) AS count FROM changed
                        """
                    )
                    expired_windows = await connection.fetchrow(
                        """
                        WITH changed AS (
                            UPDATE engineering_demo_canary_windows AS w
                            SET state='EXPIRED', terminal_at=now(), updated_at=now()
                            FROM execution_commands AS c
                            WHERE c.command_id=w.command_id
                              AND c.state IN ('QUEUED','CLAIMED','EXPIRED')
                              AND w.state IN ('QUEUED','ARMED')
                            RETURNING 1
                        )
                        SELECT count(*) AS count FROM changed
                        """
                    )
                else:
                    reconciliation = {"count": 0}
                    expired_windows = {"count": 0}
            else:
                expired = {"count": 0}
                claimed = {"count": 0}
                reconciliation = {"count": 0}
                expired_windows = {"count": 0}
            new_state = {
                "kill_switch_active": bool(updated["kill_switch_active"]),
                "kill_switch_reason": str(updated["kill_switch_reason"]),
                "governance_version": int(updated["governance_version"]),
                "queued_commands_expired": int(expired["count"]),
                "claimed_commands_outstanding": int(claimed["count"]),
                "canary_windows_expired": int(expired_windows["count"]),
                "canary_windows_requiring_reconciliation": int(reconciliation["count"]),
            }
            await connection.execute(
                """
                INSERT INTO executor_governance_audit (
                    action, actor, reason, previous_state, new_state
                ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                """,
                "KILL_SWITCH_ENGAGED" if active else "KILL_SWITCH_DISENGAGED",
                actor,
                reason,
                _json(previous),
                _json(new_state),
            )
        return GovernanceSnapshot(
            kill_switch_active=bool(updated["kill_switch_active"]),
            kill_switch_reason=str(updated["kill_switch_reason"]),
            governance_version=int(updated["governance_version"]),
        )

    async def transition_mode(
        self,
        executor_id: UUID | str,
        *,
        target_mode: ExecutorMode | str,
        actor: str,
        reason: str,
        expected_mode: ExecutorMode | str | None = None,
        expected_version: int | None = None,
    ) -> GovernanceSnapshot:
        self._require_database()
        actor = _required_text(actor, "actor")
        reason = _required_text(reason, "reason")
        target = ExecutorMode(str(target_mode))
        expected = ExecutorMode(str(expected_mode)) if expected_mode is not None else None
        async with self._pg.transaction() as connection:
            await acquire_canary_lifecycle_advisory_locks(connection, (executor_id,))
            row = await connection.fetchrow(
                """
                SELECT e.executor_id, e.execution_mode, e.mode_version, e.revoked_at,
                       a.execution_mode::text AS agent_execution_mode,
                       a.ea_subtype::text AS ea_subtype, a.locked,
                       g.kill_switch_active, g.kill_switch_reason, g.governance_version
                FROM executor_instances AS e
                JOIN ea_agents AS a ON a.id = e.executor_id
                JOIN executor_bridge_governance AS g ON g.singleton_id = 1
                WHERE e.executor_id = $1::uuid
                FOR UPDATE OF e, a, g
                """,
                str(executor_id),
            )
            if not row:
                raise GovernanceNotReadyError("executor or governance state is missing")
            if row["revoked_at"] is not None or bool(row["locked"]) or str(row["ea_subtype"]) != "EDUMB":
                raise ModeTransitionError("executor must be an unlocked, non-revoked EDUMB agent")
            current = ExecutorMode(str(row["execution_mode"]))
            if str(row["agent_execution_mode"]) != current.value:
                raise ModeTransitionError("executor mode drift detected between governance tables")
            version = int(row["mode_version"])
            if expected is not None and current != expected:
                raise GovernanceConflictError(
                    f"stale executor mode: expected {expected.value}, current {current.value}"
                )
            if expected_version is not None and version != expected_version:
                raise GovernanceConflictError(f"stale mode version: expected {expected_version}, current {version}")
            if target is ExecutorMode.LIVE:
                raise ModeTransitionError("LIVE promotion is blocked by the B2 rollout contract")
            if current is ExecutorMode.SHADOW and target is ExecutorMode.DEMO and not bool(row["kill_switch_active"]):
                raise ModeTransitionError("SHADOW to DEMO requires the global kill switch to remain engaged")

            draining_to_shadow = current is ExecutorMode.DEMO and target is ExecutorMode.SHADOW
            canary_commands_expired = 0
            canary_windows_expired = 0
            canary_windows_requiring_reconciliation = 0
            governance_kill_switch_active = bool(row["kill_switch_active"])
            governance_kill_switch_reason = str(row["kill_switch_reason"])
            governance_version = int(row["governance_version"])

            previous = {
                "execution_mode": current.value,
                "mode_version": version,
                "kill_switch_active": governance_kill_switch_active,
                "kill_switch_reason": governance_kill_switch_reason,
                "governance_version": governance_version,
            }
            if draining_to_shadow:
                canary_table = await connection.fetchval("SELECT to_regclass('public.engineering_demo_canary_windows')")
                if canary_table is not None:
                    expired_canary_commands = await connection.fetchrow(
                        """
                        WITH changed AS (
                            UPDATE execution_commands AS c
                            SET state='EXPIRED', terminal_at=now(), updated_at=now()
                            WHERE c.executor_id=$1::uuid
                              AND c.source_event='ENGINEERING_DEMO_CANARY'
                              AND c.state IN ('QUEUED','CLAIMED')
                              AND EXISTS (
                                  SELECT 1
                                  FROM engineering_demo_canary_windows AS w
                                  WHERE w.command_id=c.command_id
                                    AND w.state IN ('QUEUED','ARMED','RECONCILIATION_REQUIRED')
                              )
                            RETURNING 1
                        )
                        SELECT count(*) AS count FROM changed
                        """,
                        str(executor_id),
                    )
                    expired_canary_windows = await connection.fetchrow(
                        """
                        WITH changed AS (
                            UPDATE engineering_demo_canary_windows AS w
                            SET state='EXPIRED', terminal_at=now(), updated_at=now()
                            FROM execution_commands AS c
                            WHERE c.command_id=w.command_id
                              AND c.executor_id=$1::uuid
                              AND c.source_event='ENGINEERING_DEMO_CANARY'
                              AND c.state='EXPIRED'
                              AND w.state IN ('QUEUED','ARMED','RECONCILIATION_REQUIRED')
                            RETURNING 1
                        )
                        SELECT count(*) AS count FROM changed
                        """,
                        str(executor_id),
                    )
                    reconciliation_windows = await connection.fetchrow(
                        """
                        WITH changed AS (
                            UPDATE engineering_demo_canary_windows AS w
                            SET state='RECONCILIATION_REQUIRED', terminal_at=NULL, updated_at=now()
                            FROM execution_commands AS c
                            WHERE c.command_id=w.command_id
                              AND c.executor_id=$1::uuid
                              AND c.source_event='ENGINEERING_DEMO_CANARY'
                              AND c.state IN ('SUBMITTING','BROKER_ACCEPTED','ACTIVE','AMBIGUOUS')
                              AND w.state IN ('ARMED','RECONCILIATION_REQUIRED')
                            RETURNING 1
                        )
                        SELECT count(*) AS count FROM changed
                        """,
                        str(executor_id),
                    )
                    canary_commands_expired = int(expired_canary_commands["count"])
                    canary_windows_expired = int(expired_canary_windows["count"])
                    canary_windows_requiring_reconciliation = int(reconciliation_windows["count"])

                governed = await connection.fetchrow(
                    """
                    UPDATE executor_bridge_governance
                    SET kill_switch_active=true,
                        kill_switch_reason='MODE_TRANSITION_DRAINING_TO_SHADOW',
                        governance_version=governance_version+1,
                        updated_by=$1,
                        updated_at=now()
                    WHERE singleton_id=1
                    RETURNING kill_switch_active, kill_switch_reason, governance_version
                    """,
                    actor,
                )
                governance_kill_switch_active = bool(governed["kill_switch_active"])
                governance_kill_switch_reason = str(governed["kill_switch_reason"])
                governance_version = int(governed["governance_version"])

            updated = await connection.fetchrow(
                """
                UPDATE executor_instances
                SET execution_mode = $2, mode_version = mode_version + 1,
                    mode_changed_at = now(), mode_changed_by = $3,
                    mode_change_reason = $4, updated_at = now()
                WHERE executor_id = $1::uuid
                RETURNING mode_version
                """,
                str(executor_id),
                target.value,
                actor,
                reason,
            )
            await connection.execute(
                """
                UPDATE ea_agents
                SET execution_mode = $2::execution_mode_enum, updated_at = now()
                WHERE id = $1::uuid
                """,
                str(executor_id),
                target.value,
            )
            expired = await connection.fetchrow(
                """
                WITH changed AS (
                    UPDATE execution_commands
                    SET state = 'EXPIRED', terminal_at = now(), updated_at = now()
                    WHERE executor_id = $1::uuid
                      AND state = 'QUEUED'
                      AND payload #>> '{executor_binding,execution_mode}' <> $2
                    RETURNING 1
                )
                SELECT count(*) AS count FROM changed
                """,
                str(executor_id),
                target.value,
            )
            new_state = {
                "execution_mode": target.value,
                "mode_version": int(updated["mode_version"]),
                "kill_switch_active": governance_kill_switch_active,
                "kill_switch_reason": governance_kill_switch_reason,
                "governance_version": governance_version,
                "queued_commands_expired": int(expired["count"]),
                "canary_commands_expired": canary_commands_expired,
                "canary_windows_expired": canary_windows_expired,
                "canary_windows_requiring_reconciliation": canary_windows_requiring_reconciliation,
            }
            await connection.execute(
                """
                INSERT INTO executor_governance_audit (
                    executor_id, action, actor, reason, previous_state, new_state
                ) VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb)
                """,
                str(executor_id),
                (
                    "MODE_TRANSITION_DRAINING_TO_SHADOW"
                    if draining_to_shadow
                    else "MODE_REASSERTED"
                    if current is target
                    else "MODE_TRANSITION"
                ),
                actor,
                reason,
                _json(previous),
                _json(new_state),
            )
        return GovernanceSnapshot(
            kill_switch_active=governance_kill_switch_active,
            kill_switch_reason=governance_kill_switch_reason,
            governance_version=governance_version,
            executor_id=str(executor_id),
            execution_mode=target.value,
            mode_version=int(updated["mode_version"]),
        )


_repository = MT5ExecutorGovernanceRepository()


def get_mt5_executor_governance_repository() -> MT5ExecutorGovernanceRepository:
    return _repository


__all__ = [
    "ExecutorGovernanceError",
    "GovernanceConflictError",
    "GovernanceNotReadyError",
    "GovernanceSnapshot",
    "ModeTransitionError",
    "MT5ExecutorGovernanceRepository",
    "acquire_canary_lifecycle_advisory_locks",
    "acquire_executor_advisory_locks",
    "get_mt5_executor_governance_repository",
]
