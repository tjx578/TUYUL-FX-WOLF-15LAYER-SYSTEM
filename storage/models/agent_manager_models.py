"""SQLAlchemy ORM models for Agent Manager tables.

These models are the canonical replacement for ea_instances (deprecated).
Both ea_instances and ea_agents coexist during transition.

Zone: storage/models/ — persistence models, no decision authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.models.governance_models import Base

__all__ = [
    "EAClassEnum",
    "EASubtypeEnum",
    "ExecutionModeEnum",
    "ReporterModeEnum",
    "AgentStatusEnum",
    "EAProfile",
    "EAAgent",
    "EAAgentRuntime",
    "EAAgentEvent",
    "EAAgentAuditLog",
    "AccountPortfolioSnapshot",
]


# ---------------------------------------------------------------------------
# Python-side enum mirrors (StrEnum for easy comparison / serialisation)
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

    Intentionally distinct from EAStatus (RUNNING/STOPPED) used by ea_instances.
    """

    ONLINE = "ONLINE"
    WARNING = "WARNING"
    OFFLINE = "OFFLINE"
    QUARANTINED = "QUARANTINED"
    DISABLED = "DISABLED"


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------


class EAProfile(Base):
    """Reusable configuration template for EA agents."""

    __tablename__ = "ea_profiles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    profile_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    ea_class: Mapped[EAClassEnum] = mapped_column(
        Enum(EAClassEnum, name="ea_class_enum"),
        nullable=False,
    )
    ea_subtype: Mapped[EASubtypeEnum] = mapped_column(
        Enum(EASubtypeEnum, name="ea_subtype_enum"),
        nullable=False,
    )
    execution_mode: Mapped[ExecutionModeEnum] = mapped_column(
        Enum(ExecutionModeEnum, name="execution_mode_enum"),
        nullable=False,
    )
    reporter_mode: Mapped[ReporterModeEnum] = mapped_column(
        Enum(ReporterModeEnum, name="reporter_mode_enum"),
        nullable=False,
    )
    default_risk_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    default_news_lock: Mapped[str] = mapped_column(String(50), nullable=False, default="DEFAULT")
    allowed_strategies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    agents: Mapped[list[EAAgent]] = relationship(back_populates="profile", cascade="save-update")


class EAAgent(Base):
    """Canonical EA agent entity — replaces ea_instances (deprecated).

    Both tables coexist during transition. ea_instances is considered
    deprecated from migration 20260321_01 onward.
    """

    __tablename__ = "ea_agents"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_name: Mapped[str] = mapped_column(String(150), nullable=False)
    ea_class: Mapped[EAClassEnum] = mapped_column(
        Enum(EAClassEnum, name="ea_class_enum"),
        nullable=False,
    )
    ea_subtype: Mapped[EASubtypeEnum] = mapped_column(
        Enum(EASubtypeEnum, name="ea_subtype_enum"),
        nullable=False,
    )
    execution_mode: Mapped[ExecutionModeEnum] = mapped_column(
        Enum(ExecutionModeEnum, name="execution_mode_enum"),
        nullable=False,
        default=ExecutionModeEnum.DEMO,
    )
    reporter_mode: Mapped[ReporterModeEnum] = mapped_column(
        Enum(ReporterModeEnum, name="reporter_mode_enum"),
        nullable=False,
        default=ReporterModeEnum.FULL,
    )
    status: Mapped[AgentStatusEnum] = mapped_column(
        Enum(AgentStatusEnum, name="ea_agent_status"),
        nullable=False,
        default=AgentStatusEnum.OFFLINE,
    )
    # No FK constraint — accounts table may not have UUID PK yet
    linked_account_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    linked_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ea_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    mt5_login: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mt5_server: Mapped[str | None] = mapped_column(String(200), nullable=True)
    broker_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    strategy_profile: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    risk_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    news_lock_setting: Mapped[str] = mapped_column(String(50), nullable=False, default="DEFAULT")
    auth_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    safe_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    profile: Mapped[EAProfile | None] = relationship(back_populates="agents")
    runtime: Mapped[EAAgentRuntime | None] = relationship(
        back_populates="agent", cascade="all, delete-orphan", uselist=False
    )
    events: Mapped[list[EAAgentEvent]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    audit_logs: Mapped[list[EAAgentAuditLog]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    portfolio_snapshots: Mapped[list[AccountPortfolioSnapshot]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class EAAgentRuntime(Base):
    """Live runtime metrics for an EA agent (one-to-one with EAAgent)."""

    __tablename__ = "ea_agent_runtime"

    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ea_agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    trades_executed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cpu_usage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    connection_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    agent: Mapped[EAAgent] = relationship(back_populates="runtime")


class EAAgentEvent(Base):
    """Operational event log entry for an EA agent."""

    __tablename__ = "ea_agent_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ea_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    # Column is named 'metadata' in DB; Python attr renamed to avoid DeclarativeBase conflict
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    agent: Mapped[EAAgent] = relationship(back_populates="events")


class EAAgentAuditLog(Base):
    """Immutable audit log entry for agent configuration/state changes."""

    __tablename__ = "ea_agent_audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ea_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    performed_by: Mapped[str] = mapped_column(String(100), nullable=False, default="SYSTEM")
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    agent: Mapped[EAAgent] = relationship(back_populates="audit_logs")


class AccountPortfolioSnapshot(Base):
    """Point-in-time snapshot of an account's portfolio metrics."""

    __tablename__ = "account_portfolio_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ea_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    margin_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    margin_free: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    floating_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    snapshot_source: Mapped[str] = mapped_column(String(50), nullable=False, default="MT5")
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    agent: Mapped[EAAgent] = relationship(back_populates="portfolio_snapshots")
