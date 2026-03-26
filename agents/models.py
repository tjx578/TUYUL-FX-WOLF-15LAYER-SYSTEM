"""Pydantic v2 request/response models for the Agent Manager API.

All models use strict typing and Google-style docstrings.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "EAClassEnum",
    "EASubtypeEnum",
    "ExecutionModeEnum",
    "ReporterModeEnum",
    "AgentStatusEnum",
    "CreateAgentRequest",
    "UpdateAgentRequest",
    "LockAgentRequest",
    "AgentRuntimeResponse",
    "AgentEventResponse",
    "AgentAuditLogResponse",
    "AgentResponse",
    "AgentListResponse",
    "CreateProfileRequest",
    "ProfileResponse",
    "PortfolioSnapshotResponse",
    "IngestHeartbeatRequest",
    "IngestStatusChangeRequest",
    "IngestPortfolioSnapshotRequest",
]

# ---------------------------------------------------------------------------
# String enums (mirrors of ORM enums)
# ---------------------------------------------------------------------------


class EAClassEnum(StrEnum):
    """EA classification."""

    PRIMARY = "PRIMARY"
    PORTFOLIO = "PORTFOLIO"


class EASubtypeEnum(StrEnum):
    """EA operational subtype."""

    BROKER = "BROKER"
    PROP_FIRM = "PROP_FIRM"
    EDUMB = "EDUMB"
    STANDARD_REPORTER = "STANDARD_REPORTER"


class ExecutionModeEnum(StrEnum):
    """Execution environment mode."""

    LIVE = "LIVE"
    DEMO = "DEMO"
    SHADOW = "SHADOW"


class ReporterModeEnum(StrEnum):
    """Data reporting granularity."""

    FULL = "FULL"
    BALANCE_ONLY = "BALANCE_ONLY"
    DISABLED = "DISABLED"


class AgentStatusEnum(StrEnum):
    """Runtime status of an EA agent.

    Distinct from the legacy EAStatus (RUNNING/STOPPED) used by ea_instances.
    """

    ONLINE = "ONLINE"
    WARNING = "WARNING"
    OFFLINE = "OFFLINE"
    QUARANTINED = "QUARANTINED"
    DISABLED = "DISABLED"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    """Payload for creating a new EA agent."""

    agent_name: str = Field(..., min_length=1, max_length=150)
    ea_class: EAClassEnum
    ea_subtype: EASubtypeEnum
    execution_mode: ExecutionModeEnum = ExecutionModeEnum.DEMO
    reporter_mode: ReporterModeEnum = ReporterModeEnum.FULL
    linked_account_id: UUID | None = None
    linked_profile_id: UUID | None = None
    mt5_login: int | None = None
    mt5_server: str | None = Field(None, max_length=200)
    broker_name: str | None = Field(None, max_length=200)
    strategy_profile: str = Field("default", max_length=100)
    risk_multiplier: float = Field(1.0, ge=0.0)
    news_lock_setting: str = Field("DEFAULT", max_length=50)
    notes: str | None = None


class UpdateAgentRequest(BaseModel):
    """Payload for updating an existing EA agent (all fields optional)."""

    agent_name: str | None = Field(default=None, min_length=1, max_length=150)
    ea_class: EAClassEnum | None = None
    ea_subtype: EASubtypeEnum | None = None
    execution_mode: ExecutionModeEnum | None = None
    reporter_mode: ReporterModeEnum | None = None
    linked_account_id: UUID | None = None
    linked_profile_id: UUID | None = None
    mt5_login: int | None = None
    mt5_server: str | None = Field(default=None, max_length=200)
    broker_name: str | None = Field(default=None, max_length=200)
    strategy_profile: str | None = Field(default=None, max_length=100)
    risk_multiplier: float | None = Field(default=None, ge=0.0)
    news_lock_setting: str | None = Field(default=None, max_length=50)
    safe_mode: bool | None = None
    notes: str | None = None
    version: str | None = Field(default=None, max_length=50)


class LockAgentRequest(BaseModel):
    """Payload for locking an EA agent."""

    reason: str = Field(..., min_length=1)
    locked_by: str = Field("SYSTEM", min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AgentRuntimeResponse(BaseModel):
    """Runtime metrics snapshot for an EA agent."""

    agent_id: UUID
    last_heartbeat: datetime
    last_success: datetime | None
    last_failure: datetime | None
    failure_reason: str | None
    trades_executed: int
    trades_failed: int
    uptime_seconds: int
    cpu_usage_pct: float | None
    memory_mb: float | None
    connection_latency_ms: float | None
    updated_at: datetime


class AgentEventResponse(BaseModel):
    """A single agent event record."""

    id: UUID
    agent_id: UUID
    event_type: str
    severity: str
    message: str
    metadata: dict[str, Any]
    created_at: datetime


class AgentAuditLogResponse(BaseModel):
    """A single agent audit log record."""

    id: UUID
    agent_id: UUID
    action: str
    performed_by: str
    details: dict[str, Any]
    previous_state: dict[str, Any] | None
    new_state: dict[str, Any] | None
    created_at: datetime


class AgentResponse(BaseModel):
    """Full agent representation returned by the API."""

    id: UUID
    agent_name: str
    ea_class: EAClassEnum
    ea_subtype: EASubtypeEnum
    execution_mode: ExecutionModeEnum
    reporter_mode: ReporterModeEnum
    status: AgentStatusEnum
    linked_account_id: UUID | None
    linked_profile_id: UUID | None
    mt5_login: int | None
    mt5_server: str | None
    broker_name: str | None
    strategy_profile: str
    risk_multiplier: float
    news_lock_setting: str
    safe_mode: bool
    locked: bool
    lock_reason: str | None
    locked_at: datetime | None
    locked_by: str | None
    notes: str | None
    version: str | None
    created_at: datetime
    updated_at: datetime
    runtime: AgentRuntimeResponse | None = None


class AgentListResponse(BaseModel):
    """Paginated list of agents."""

    agents: list[AgentResponse]
    total: int


class CreateProfileRequest(BaseModel):
    """Payload for creating a new EA profile."""

    profile_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    ea_class: EAClassEnum
    ea_subtype: EASubtypeEnum
    execution_mode: ExecutionModeEnum
    reporter_mode: ReporterModeEnum
    default_risk_multiplier: float = Field(1.0, ge=0.0)
    default_news_lock: str = Field("DEFAULT", max_length=50)
    allowed_strategies: list[str] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    """EA profile representation returned by the API."""

    id: UUID
    profile_name: str
    description: str | None
    ea_class: EAClassEnum
    ea_subtype: EASubtypeEnum
    execution_mode: ExecutionModeEnum
    reporter_mode: ReporterModeEnum
    default_risk_multiplier: float
    default_news_lock: str
    allowed_strategies: list[str]
    created_at: datetime
    updated_at: datetime


class PortfolioSnapshotResponse(BaseModel):
    """A single account portfolio snapshot."""

    id: UUID
    agent_id: UUID
    account_id: str
    balance: float
    equity: float
    margin_used: float
    margin_free: float
    open_positions: int
    daily_pnl: float
    floating_pnl: float
    snapshot_source: str
    captured_at: datetime


# ---------------------------------------------------------------------------
# Ingest request models (MT5 EA → backend)
# ---------------------------------------------------------------------------


class IngestHeartbeatRequest(BaseModel):
    """Heartbeat payload sent by an MT5 EA."""

    agent_id: UUID
    timestamp: datetime
    trades_executed: int | None = None
    trades_failed: int | None = None
    uptime_seconds: int | None = None
    cpu_usage_pct: float | None = None
    memory_mb: float | None = None
    connection_latency_ms: float | None = None


class IngestStatusChangeRequest(BaseModel):
    """Status-change notification sent by an MT5 EA."""

    agent_id: UUID
    new_status: AgentStatusEnum
    reason: str | None = None


class IngestPortfolioSnapshotRequest(BaseModel):
    """Portfolio snapshot payload sent by an MT5 EA."""

    agent_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    balance: float
    equity: float
    margin_used: float = 0.0
    margin_free: float = 0.0
    open_positions: int = 0
    daily_pnl: float = 0.0
    floating_pnl: float = 0.0
