"""Business logic service for the Agent Manager domain.

Orchestrates repository calls, validation, audit logging, and event emission.
All write operations produce an audit log entry.  Status changes also emit an
agent event.

Zone: agents/ — domain service, no execution or decision authority.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agents.exceptions import (
    AgentConflictError,
    AgentError,
    AgentLockError,
    AgentNotFoundError,
    AgentValidationError,
)
from agents.models import (
    CreateAgentRequest,
    CreateProfileRequest,
    IngestHeartbeatRequest,
    IngestPortfolioSnapshotRequest,
    IngestStatusChangeRequest,
    LockAgentRequest,
    UpdateAgentRequest,
)
from agents.repository import AgentRepository

__all__ = ["AgentManagerService"]

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _safe_str(value: Any) -> str | None:
    """Convert UUID/any to str, preserving None."""
    return str(value) if value is not None else None


def _is_unique_violation(exc: Exception) -> bool:
    """Return True if *exc* is an asyncpg unique-constraint violation.

    Uses structured exception type when asyncpg is available; falls back to
    message inspection as a last resort for environments without asyncpg.
    """
    try:
        import asyncpg  # noqa: PLC0415

        return isinstance(exc, asyncpg.UniqueViolationError)
    except ImportError:
        pass
    _msg = str(exc).lower()
    return "unique" in _msg or "duplicate" in _msg


class AgentManagerService:
    """High-level service for EA agent lifecycle management.

    Injects an AgentRepository instance for all persistence calls.
    """

    def __init__(self, repo: AgentRepository | None = None) -> None:
        self._repo = repo or AgentRepository()

    # ------------------------------------------------------------------
    # Agents — read
    # ------------------------------------------------------------------

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Fetch a single agent with its runtime metrics.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Agent dict with optional 'runtime' sub-dict.

        Raises:
            AgentNotFoundError: If no agent with the given ID exists.
        """
        agent = await self._repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        runtime = await self._repo.get_runtime(agent_id)
        agent["runtime"] = runtime
        return agent

    async def list_agents(
        self,
        ea_class: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List agents with optional filters and pagination.

        Args:
            ea_class: Optional ea_class filter ('PRIMARY' or 'PORTFOLIO').
            status: Optional agent status filter.
            limit: Max rows to return.
            offset: Row offset.

        Returns:
            Tuple of (agent_dicts, total_count).
        """
        return await self._repo.list_agents(ea_class, status, limit, offset)

    # ------------------------------------------------------------------
    # Agents — write
    # ------------------------------------------------------------------

    async def create_agent(
        self,
        request: CreateAgentRequest,
        performed_by: str = "SYSTEM",
    ) -> dict[str, Any]:
        """Create a new EA agent.

        Args:
            request: Validated create request.
            performed_by: Actor performing the action.

        Returns:
            Created agent dict.

        Raises:
            AgentConflictError: If duplicate mt5_login/mt5_server pair exists.
            AgentError: On unexpected persistence failure.
        """
        data: dict[str, Any] = {
            "agent_name": request.agent_name,
            "ea_class": request.ea_class.value,
            "ea_subtype": request.ea_subtype.value,
            "execution_mode": request.execution_mode.value,
            "reporter_mode": request.reporter_mode.value,
            "linked_account_id": _safe_str(request.linked_account_id),
            "linked_profile_id": _safe_str(request.linked_profile_id),
            "mt5_login": request.mt5_login,
            "mt5_server": request.mt5_server,
            "broker_name": request.broker_name,
            "strategy_profile": request.strategy_profile,
            "risk_multiplier": request.risk_multiplier,
            "news_lock_setting": request.news_lock_setting,
            "notes": request.notes,
        }
        try:
            agent = await self._repo.create_agent(data)
        except Exception as exc:
            if _is_unique_violation(exc):
                raise AgentConflictError("An agent with the same mt5_login/mt5_server already exists") from exc
            raise AgentError(f"Failed to create agent: {exc}") from exc

        await self._repo.insert_audit_log(
            agent_id=str(agent["id"]),
            action="CREATE_AGENT",
            performed_by=performed_by,
            details=data,
            previous_state=None,
            new_state=agent,
        )
        logger.info("Agent created: %s by %s", agent["id"], performed_by)
        return agent

    async def update_agent(
        self,
        agent_id: str,
        request: UpdateAgentRequest,
        performed_by: str = "SYSTEM",
    ) -> dict[str, Any]:
        """Update mutable fields of an existing agent.

        Args:
            agent_id: UUID string of the agent.
            request: Validated update request (only set fields are applied).
            performed_by: Actor performing the action.

        Returns:
            Updated agent dict.

        Raises:
            AgentNotFoundError: If agent does not exist.
        """
        previous = await self._repo.get_agent(agent_id)
        if previous is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")

        updates: dict[str, Any] = {}
        for field, value in request.model_dump(exclude_none=True).items():
            if isinstance(value, UUID):
                updates[field] = str(value)
            elif hasattr(value, "value"):
                updates[field] = value.value
            else:
                updates[field] = value

        updated = await self._repo.update_agent(agent_id, updates)
        if updated is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found after update")

        await self._repo.insert_audit_log(
            agent_id=agent_id,
            action="UPDATE_AGENT",
            performed_by=performed_by,
            details=updates,
            previous_state=previous,
            new_state=updated,
        )
        return updated

    async def delete_agent(
        self,
        agent_id: str,
        performed_by: str = "SYSTEM",
    ) -> bool:
        """Delete an agent by UUID.

        Args:
            agent_id: UUID string of the agent.
            performed_by: Actor performing the action.

        Returns:
            True if the agent was deleted.

        Raises:
            AgentNotFoundError: If agent does not exist.
        """
        previous = await self._repo.get_agent(agent_id)
        if previous is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")

        deleted = await self._repo.delete_agent(agent_id)
        if deleted:
            # Audit log insert may fail after delete — log and swallow
            try:
                await self._repo.insert_audit_log(
                    agent_id=agent_id,
                    action="DELETE_AGENT",
                    performed_by=performed_by,
                    details={"agent_id": agent_id},
                    previous_state=previous,
                    new_state=None,
                )
            except Exception:
                logger.warning("Could not write audit log after agent delete %s", agent_id)
        return deleted

    async def lock_agent(
        self,
        agent_id: str,
        request: LockAgentRequest,
        performed_by: str = "SYSTEM",
    ) -> dict[str, Any]:
        """Lock an agent, preventing state transitions.

        Args:
            agent_id: UUID string of the agent.
            request: Lock request with reason and locked_by.
            performed_by: Actor performing the action.

        Returns:
            Updated agent dict.

        Raises:
            AgentNotFoundError: If agent does not exist.
            AgentLockError: If agent is already locked.
        """
        previous = await self._repo.get_agent(agent_id)
        if previous is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        if previous.get("locked"):
            raise AgentLockError(f"Agent {agent_id!r} is already locked")

        updated = await self._repo.lock_agent(agent_id, request.reason, request.locked_by)
        if updated is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found after lock")

        await self._repo.insert_audit_log(
            agent_id=agent_id,
            action="LOCK_AGENT",
            performed_by=performed_by,
            details={"reason": request.reason, "locked_by": request.locked_by},
            previous_state=previous,
            new_state=updated,
        )
        await self._repo.insert_event(
            agent_id=agent_id,
            event_type="CONFIG_CHANGE",
            severity="WARNING",
            message=f"Agent locked: {request.reason}",
            metadata={"locked_by": request.locked_by},
        )
        return updated

    async def unlock_agent(
        self,
        agent_id: str,
        performed_by: str = "SYSTEM",
    ) -> dict[str, Any]:
        """Unlock a previously locked agent.

        Args:
            agent_id: UUID string of the agent.
            performed_by: Actor performing the action.

        Returns:
            Updated agent dict.

        Raises:
            AgentNotFoundError: If agent does not exist.
            AgentLockError: If agent is not locked.
        """
        previous = await self._repo.get_agent(agent_id)
        if previous is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        if not previous.get("locked"):
            raise AgentLockError(f"Agent {agent_id!r} is not locked")

        updated = await self._repo.unlock_agent(agent_id)
        if updated is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found after unlock")

        await self._repo.insert_audit_log(
            agent_id=agent_id,
            action="UNLOCK_AGENT",
            performed_by=performed_by,
            details={"agent_id": agent_id},
            previous_state=previous,
            new_state=updated,
        )
        await self._repo.insert_event(
            agent_id=agent_id,
            event_type="CONFIG_CHANGE",
            severity="INFO",
            message="Agent unlocked",
            metadata={"performed_by": performed_by},
        )
        return updated

    # ------------------------------------------------------------------
    # Ingest / runtime
    # ------------------------------------------------------------------

    async def record_heartbeat(self, request: IngestHeartbeatRequest) -> dict[str, Any]:
        """Upsert runtime metrics from a heartbeat payload.

        Args:
            request: Validated heartbeat payload.

        Returns:
            Upserted runtime row dict.

        Raises:
            AgentNotFoundError: If the agent does not exist.
        """
        agent_id = str(request.agent_id)
        agent = await self._repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")

        data: dict[str, Any] = {
            "last_heartbeat": request.timestamp,
            "trades_executed": request.trades_executed,
            "trades_failed": request.trades_failed,
            "uptime_seconds": request.uptime_seconds,
            "cpu_usage_pct": request.cpu_usage_pct,
            "memory_mb": request.memory_mb,
            "connection_latency_ms": request.connection_latency_ms,
        }
        return await self._repo.upsert_runtime(agent_id, data)

    async def change_status(
        self,
        request: IngestStatusChangeRequest,
        performed_by: str = "SYSTEM",
    ) -> dict[str, Any]:
        """Record a status change for an agent.

        Args:
            request: Validated status-change payload.
            performed_by: Actor performing the change.

        Returns:
            Updated agent dict.

        Raises:
            AgentNotFoundError: If the agent does not exist.
            AgentLockError: If the agent is locked (status changes blocked).
            AgentValidationError: If new_status equals current status.
        """
        agent_id = str(request.agent_id)
        previous = await self._repo.get_agent(agent_id)
        if previous is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        if previous.get("locked"):
            raise AgentLockError(f"Agent {agent_id!r} is locked — status changes are blocked")

        old_status = str(previous.get("status", ""))
        new_status = request.new_status.value
        if old_status == new_status:
            raise AgentValidationError(f"Agent {agent_id!r} already has status {new_status!r}")

        updated = await self._repo.update_agent_status(agent_id, new_status)
        if updated is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found after status update")

        await self._repo.insert_event(
            agent_id=agent_id,
            event_type="STATUS_CHANGE",
            severity="INFO",
            message=f"Status changed from {old_status} to {new_status}",
            metadata={
                "old_status": old_status,
                "new_status": new_status,
                "reason": request.reason,
            },
        )
        await self._repo.insert_audit_log(
            agent_id=agent_id,
            action="STATUS_CHANGE",
            performed_by=performed_by,
            details={"old_status": old_status, "new_status": new_status, "reason": request.reason},
            previous_state=previous,
            new_state=updated,
        )
        return updated

    async def record_portfolio_snapshot(
        self,
        request: IngestPortfolioSnapshotRequest,
    ) -> dict[str, Any]:
        """Insert a portfolio snapshot for an agent.

        Args:
            request: Validated portfolio snapshot payload.

        Returns:
            Inserted snapshot row dict.

        Raises:
            AgentNotFoundError: If the agent does not exist.
        """
        agent_id = str(request.agent_id)
        agent = await self._repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")

        data: dict[str, Any] = {
            "agent_id": agent_id,
            "account_id": request.account_id,
            "balance": request.balance,
            "equity": request.equity,
            "margin_used": request.margin_used,
            "margin_free": request.margin_free,
            "open_positions": request.open_positions,
            "daily_pnl": request.daily_pnl,
            "floating_pnl": request.floating_pnl,
            "captured_at": _utcnow(),
        }
        return await self._repo.insert_portfolio_snapshot(data)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def get_agent_events(
        self,
        agent_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List events for an agent.

        Args:
            agent_id: UUID string of the agent.
            limit: Max rows.
            offset: Row offset.

        Returns:
            List of event dicts.

        Raises:
            AgentNotFoundError: If agent does not exist.
        """
        agent = await self._repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        return await self._repo.list_events(agent_id, limit, offset)

    async def get_agent_audit_log(
        self,
        agent_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List audit log entries for an agent.

        Args:
            agent_id: UUID string of the agent.
            limit: Max rows.
            offset: Row offset.

        Returns:
            List of audit log dicts.

        Raises:
            AgentNotFoundError: If agent does not exist.
        """
        agent = await self._repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        return await self._repo.list_audit_logs(agent_id, limit, offset)

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    async def create_profile(
        self,
        request: CreateProfileRequest,
        performed_by: str = "SYSTEM",
    ) -> dict[str, Any]:
        """Create a new EA profile.

        Args:
            request: Validated profile create request.
            performed_by: Actor performing the action.

        Returns:
            Created profile dict.

        Raises:
            AgentConflictError: If profile_name is already taken.
        """
        data: dict[str, Any] = {
            "profile_name": request.profile_name,
            "description": request.description,
            "ea_class": request.ea_class.value,
            "ea_subtype": request.ea_subtype.value,
            "execution_mode": request.execution_mode.value,
            "reporter_mode": request.reporter_mode.value,
            "default_risk_multiplier": request.default_risk_multiplier,
            "default_news_lock": request.default_news_lock,
            "allowed_strategies": request.allowed_strategies,
        }
        try:
            profile = await self._repo.create_profile(data)
        except Exception as exc:
            if _is_unique_violation(exc):
                raise AgentConflictError(f"Profile name {request.profile_name!r} already exists") from exc
            raise AgentError(f"Failed to create profile: {exc}") from exc
        return profile

    async def list_profiles(self) -> list[dict[str, Any]]:
        """List all EA profiles.

        Returns:
            List of profile dicts.
        """
        return await self._repo.list_profiles()

    async def list_portfolio_snapshots(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List recent portfolio snapshots for an agent.

        Args:
            agent_id: UUID string of the agent.
            limit: Max rows.

        Returns:
            List of snapshot dicts.

        Raises:
            AgentNotFoundError: If agent does not exist.
        """
        agent = await self._repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id!r} not found")
        return await self._repo.list_portfolio_snapshots(agent_id, limit)
