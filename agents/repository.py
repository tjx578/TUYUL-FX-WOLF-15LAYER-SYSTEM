"""Raw asyncpg query layer for the Agent Manager domain.

All SQL queries are fully parameterised ($1, $2, …).  No f-string interpolation
is used inside query strings.  Singleton PostgresClient is obtained via the
module-level helper to match the codebase singleton pattern.

Zone: agents/ — domain repository, read/write via PostgresClient.  No decision
authority.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.exceptions import AgentValidationError
from storage.postgres_client import PostgresClient

__all__ = ["AgentRepository"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed enum values — validated before they enter query strings
# ---------------------------------------------------------------------------

_VALID_EA_CLASSES: frozenset[str] = frozenset({"PRIMARY", "PORTFOLIO"})
_VALID_AGENT_STATUSES: frozenset[str] = frozenset({"ONLINE", "WARNING", "OFFLINE", "QUARANTINED", "DISABLED"})

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict."""
    return dict(row) if row is not None else {}


def _rows_to_list(rows: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of asyncpg Records to plain dicts."""
    return [dict(r) for r in rows]


class AgentRepository:
    """Raw-query repository for agent manager tables.

    All public methods are async and use parameterised SQL to prevent injection.
    """

    def __init__(self) -> None:
        self._pg = PostgresClient()

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch a single agent by UUID.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Row dict or None if not found.
        """
        row = await self._pg.fetchrow(
            "SELECT * FROM ea_agents WHERE id = $1::uuid",
            agent_id,
        )
        return _row_to_dict(row) if row else None

    async def list_agents(
        self,
        ea_class: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """List agents with optional filters and pagination.

        Args:
            ea_class: Optional ea_class_enum filter ('PRIMARY' or 'PORTFOLIO').
            status: Optional ea_agent_status filter (e.g. 'ONLINE', 'OFFLINE').
            limit: Max rows to return.
            offset: Row offset for pagination.

        Returns:
            Tuple of (rows, total_count).

        Raises:
            AgentValidationError: If ea_class or status is not a valid enum value.
        """
        # Validate enum inputs to avoid any possibility of SQL structure manipulation.
        # Note: user values are always passed as $N parameters — they never appear in
        # the query string itself. The WHERE clause only uses hardcoded SQL fragments
        # like 'ea_class = $1::ea_class_enum'. Validation is belt-and-suspenders.
        if ea_class is not None and ea_class not in _VALID_EA_CLASSES:
            raise AgentValidationError(
                f"Invalid ea_class filter {ea_class!r}. Must be one of {sorted(_VALID_EA_CLASSES)}"
            )
        if status is not None and status not in _VALID_AGENT_STATUSES:
            raise AgentValidationError(
                f"Invalid status filter {status!r}. Must be one of {sorted(_VALID_AGENT_STATUSES)}"
            )

        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if ea_class is not None:
            conditions.append(f"ea_class = ${idx}::ea_class_enum")
            params.append(ea_class)
            idx += 1

        if status is not None:
            conditions.append(f"status = ${idx}::ea_agent_status")
            params.append(status)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        count_row = await self._pg.fetchrow(
            f"SELECT COUNT(*) AS total FROM ea_agents {where}",
            *params,
        )
        total: int = int(count_row["total"]) if count_row else 0

        params.extend([limit, offset])
        rows = await self._pg.fetch(
            f"SELECT * FROM ea_agents {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
        )
        return _rows_to_list(rows), total

    async def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a new agent and return the created row.

        Args:
            data: Field dictionary for the new agent.

        Returns:
            Created row dict.
        """
        row = await self._pg.fetchrow(
            """
            INSERT INTO ea_agents (
                agent_name, ea_class, ea_subtype, execution_mode, reporter_mode,
                linked_account_id, linked_profile_id, mt5_login, mt5_server,
                broker_name, strategy_profile, risk_multiplier, news_lock_setting,
                notes
            ) VALUES (
                $1, $2::ea_class_enum, $3::ea_subtype_enum, $4::execution_mode_enum,
                $5::reporter_mode_enum, $6::uuid, $7::uuid, $8, $9, $10, $11, $12, $13, $14
            )
            RETURNING *
            """,
            data["agent_name"],
            data["ea_class"],
            data["ea_subtype"],
            data.get("execution_mode", "DEMO"),
            data.get("reporter_mode", "FULL"),
            data.get("linked_account_id"),
            data.get("linked_profile_id"),
            data.get("mt5_login"),
            data.get("mt5_server"),
            data.get("broker_name"),
            data.get("strategy_profile", "default"),
            data.get("risk_multiplier", 1.0),
            data.get("news_lock_setting", "DEFAULT"),
            data.get("notes"),
        )
        return _row_to_dict(row)

    async def update_agent(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Update mutable agent fields and return the updated row.

        Args:
            agent_id: UUID string of the agent to update.
            data: Dictionary of fields to update (only non-None values).

        Returns:
            Updated row dict or None if agent not found.
        """
        if not data:
            return await self.get_agent(agent_id)

        # Build SET clause dynamically from provided keys
        allowed = {
            "agent_name",
            "ea_class",
            "ea_subtype",
            "execution_mode",
            "reporter_mode",
            "linked_account_id",
            "linked_profile_id",
            "mt5_login",
            "mt5_server",
            "broker_name",
            "strategy_profile",
            "risk_multiplier",
            "news_lock_setting",
            "safe_mode",
            "notes",
            "version",
        }
        filtered = {k: v for k, v in data.items() if k in allowed}
        if not filtered:
            return await self.get_agent(agent_id)

        _type_cast: dict[str, str] = {
            "ea_class": "::ea_class_enum",
            "ea_subtype": "::ea_subtype_enum",
            "execution_mode": "::execution_mode_enum",
            "reporter_mode": "::reporter_mode_enum",
            "linked_account_id": "::uuid",
            "linked_profile_id": "::uuid",
        }

        set_parts: list[str] = []
        params: list[Any] = []
        for i, (key, val) in enumerate(filtered.items(), start=1):
            cast = _type_cast.get(key, "")
            set_parts.append(f"{key} = ${i}{cast}")
            params.append(val)

        params.extend([agent_id])
        id_idx = len(params)

        row = await self._pg.fetchrow(
            f"UPDATE ea_agents SET {', '.join(set_parts)}, updated_at = now() WHERE id = ${id_idx}::uuid RETURNING *",
            *params,
        )
        return _row_to_dict(row) if row else None

    async def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent by UUID.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            True if a row was deleted, False otherwise.
        """
        result: str = await self._pg.execute(
            "DELETE FROM ea_agents WHERE id = $1::uuid",
            agent_id,
        )
        # asyncpg returns e.g. "DELETE 1"
        return result.endswith("1")

    async def lock_agent(
        self,
        agent_id: str,
        reason: str,
        locked_by: str,
    ) -> dict[str, Any] | None:
        """Lock an agent, setting locked=true with metadata.

        Args:
            agent_id: UUID string of the agent.
            reason: Human-readable lock reason.
            locked_by: Actor who requested the lock.

        Returns:
            Updated row dict or None if not found.
        """
        row = await self._pg.fetchrow(
            """
            UPDATE ea_agents
            SET locked = true, lock_reason = $2, locked_at = now(), locked_by = $3,
                updated_at = now()
            WHERE id = $1::uuid
            RETURNING *
            """,
            agent_id,
            reason,
            locked_by,
        )
        return _row_to_dict(row) if row else None

    async def unlock_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Unlock an agent, clearing all lock metadata.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Updated row dict or None if not found.
        """
        row = await self._pg.fetchrow(
            """
            UPDATE ea_agents
            SET locked = false, lock_reason = NULL, locked_at = NULL, locked_by = NULL,
                updated_at = now()
            WHERE id = $1::uuid
            RETURNING *
            """,
            agent_id,
        )
        return _row_to_dict(row) if row else None

    async def update_agent_status(
        self,
        agent_id: str,
        new_status: str,
    ) -> dict[str, Any] | None:
        """Update only the status field of an agent.

        Args:
            agent_id: UUID string of the agent.
            new_status: New ea_agent_status value.

        Returns:
            Updated row dict or None if not found.
        """
        row = await self._pg.fetchrow(
            """
            UPDATE ea_agents
            SET status = $2::ea_agent_status, updated_at = now()
            WHERE id = $1::uuid
            RETURNING *
            """,
            agent_id,
            new_status,
        )
        return _row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    async def get_runtime(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch runtime metrics for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Runtime row dict or None.
        """
        row = await self._pg.fetchrow(
            "SELECT * FROM ea_agent_runtime WHERE agent_id = $1::uuid",
            agent_id,
        )
        return _row_to_dict(row) if row else None

    async def upsert_runtime(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Insert or update runtime metrics for an agent.

        Args:
            agent_id: UUID string of the agent.
            data: Runtime metric values.

        Returns:
            Upserted row dict.
        """
        row = await self._pg.fetchrow(
            """
            INSERT INTO ea_agent_runtime (
                agent_id, last_heartbeat, trades_executed, trades_failed,
                uptime_seconds, cpu_usage_pct, memory_mb, connection_latency_ms, updated_at
            ) VALUES (
                $1::uuid, $2, $3, $4, $5, $6, $7, $8, now()
            )
            ON CONFLICT (agent_id) DO UPDATE SET
                last_heartbeat = EXCLUDED.last_heartbeat,
                trades_executed = COALESCE(EXCLUDED.trades_executed, ea_agent_runtime.trades_executed),
                trades_failed = COALESCE(EXCLUDED.trades_failed, ea_agent_runtime.trades_failed),
                uptime_seconds = COALESCE(EXCLUDED.uptime_seconds, ea_agent_runtime.uptime_seconds),
                cpu_usage_pct = EXCLUDED.cpu_usage_pct,
                memory_mb = EXCLUDED.memory_mb,
                connection_latency_ms = EXCLUDED.connection_latency_ms,
                updated_at = now()
            RETURNING *
            """,
            agent_id,
            data["last_heartbeat"],
            data.get("trades_executed"),
            data.get("trades_failed"),
            data.get("uptime_seconds"),
            data.get("cpu_usage_pct"),
            data.get("memory_mb"),
            data.get("connection_latency_ms"),
        )
        return _row_to_dict(row)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def insert_event(
        self,
        agent_id: str,
        event_type: str,
        severity: str,
        message: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert an agent event record.

        Args:
            agent_id: UUID string of the agent.
            event_type: e.g. 'HEARTBEAT', 'STATUS_CHANGE', 'ERROR'.
            severity: 'INFO', 'WARNING', or 'CRITICAL'.
            message: Human-readable event message.
            metadata: Arbitrary JSON payload.

        Returns:
            Inserted row dict.
        """
        row = await self._pg.fetchrow(
            """
            INSERT INTO ea_agent_events (agent_id, event_type, severity, message, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
            RETURNING *
            """,
            agent_id,
            event_type,
            severity,
            message,
            json.dumps(metadata),
        )
        return _row_to_dict(row)

    async def list_events(
        self,
        agent_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """List events for an agent ordered by created_at DESC.

        Args:
            agent_id: UUID string of the agent.
            limit: Max rows.
            offset: Row offset.

        Returns:
            List of event row dicts.
        """
        rows = await self._pg.fetch(
            """
            SELECT * FROM ea_agent_events
            WHERE agent_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            agent_id,
            limit,
            offset,
        )
        return _rows_to_list(rows)

    # ------------------------------------------------------------------
    # Audit logs
    # ------------------------------------------------------------------

    async def insert_audit_log(
        self,
        agent_id: str,
        action: str,
        performed_by: str,
        details: dict[str, Any],
        previous_state: dict[str, Any] | None,
        new_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Insert an agent audit log entry.

        Args:
            agent_id: UUID string of the agent.
            action: Action label (e.g. 'CREATE_AGENT', 'LOCK_AGENT').
            performed_by: Actor identifier.
            details: Structured details dict.
            previous_state: State before the action (nullable).
            new_state: State after the action (nullable).

        Returns:
            Inserted row dict.
        """
        row = await self._pg.fetchrow(
            """
            INSERT INTO ea_agent_audit_logs
                (agent_id, action, performed_by, details, previous_state, new_state)
            VALUES
                ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb)
            RETURNING *
            """,
            agent_id,
            action,
            performed_by,
            json.dumps(details),
            json.dumps(previous_state) if previous_state is not None else None,
            json.dumps(new_state) if new_state is not None else None,
        )
        return _row_to_dict(row)

    async def list_audit_logs(
        self,
        agent_id: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """List audit logs for an agent ordered by created_at DESC.

        Args:
            agent_id: UUID string of the agent.
            limit: Max rows.
            offset: Row offset.

        Returns:
            List of audit log row dicts.
        """
        rows = await self._pg.fetch(
            """
            SELECT * FROM ea_agent_audit_logs
            WHERE agent_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            agent_id,
            limit,
            offset,
        )
        return _rows_to_list(rows)

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    async def create_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a new EA profile.

        Args:
            data: Profile field dictionary.

        Returns:
            Created row dict.
        """
        row = await self._pg.fetchrow(
            """
            INSERT INTO ea_profiles (
                profile_name, description, ea_class, ea_subtype, execution_mode,
                reporter_mode, default_risk_multiplier, default_news_lock, allowed_strategies
            ) VALUES (
                $1, $2, $3::ea_class_enum, $4::ea_subtype_enum, $5::execution_mode_enum,
                $6::reporter_mode_enum, $7, $8, $9::jsonb
            )
            RETURNING *
            """,
            data["profile_name"],
            data.get("description"),
            data["ea_class"],
            data["ea_subtype"],
            data["execution_mode"],
            data["reporter_mode"],
            data.get("default_risk_multiplier", 1.0),
            data.get("default_news_lock", "DEFAULT"),
            json.dumps(data.get("allowed_strategies", [])),
        )
        return _row_to_dict(row)

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Fetch a profile by UUID.

        Args:
            profile_id: UUID string of the profile.

        Returns:
            Row dict or None.
        """
        row = await self._pg.fetchrow(
            "SELECT * FROM ea_profiles WHERE id = $1::uuid",
            profile_id,
        )
        return _row_to_dict(row) if row else None

    async def list_profiles(self) -> list[dict[str, Any]]:
        """List all EA profiles ordered by profile_name.

        Returns:
            List of profile row dicts.
        """
        rows = await self._pg.fetch(
            "SELECT * FROM ea_profiles ORDER BY profile_name ASC",
        )
        return _rows_to_list(rows)

    # ------------------------------------------------------------------
    # Portfolio snapshots
    # ------------------------------------------------------------------

    async def insert_portfolio_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a portfolio snapshot.

        Args:
            data: Snapshot field dictionary.

        Returns:
            Inserted row dict.
        """
        row = await self._pg.fetchrow(
            """
            INSERT INTO account_portfolio_snapshots (
                agent_id, account_id, balance, equity, margin_used, margin_free,
                open_positions, daily_pnl, floating_pnl, snapshot_source, captured_at
            ) VALUES (
                $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
            )
            RETURNING *
            """,
            str(data["agent_id"]),
            data["account_id"],
            data["balance"],
            data["equity"],
            data.get("margin_used", 0.0),
            data.get("margin_free", 0.0),
            data.get("open_positions", 0),
            data.get("daily_pnl", 0.0),
            data.get("floating_pnl", 0.0),
            data.get("snapshot_source", "MT5"),
            data.get("captured_at"),
        )
        return _row_to_dict(row)

    async def list_portfolio_snapshots(
        self,
        agent_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """List recent portfolio snapshots for an agent.

        Args:
            agent_id: UUID string of the agent.
            limit: Max rows to return.

        Returns:
            List of snapshot row dicts.
        """
        rows = await self._pg.fetch(
            """
            SELECT * FROM account_portfolio_snapshots
            WHERE agent_id = $1::uuid
            ORDER BY captured_at DESC
            LIMIT $2
            """,
            agent_id,
            limit,
        )
        return _rows_to_list(rows)
