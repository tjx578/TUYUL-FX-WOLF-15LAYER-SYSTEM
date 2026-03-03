"""Canonical PostgreSQL models for account, prop-firm, and EA instances.

These models define data ownership for dashboard/risk governance only.
They do not carry any strategy or Layer-12 decision authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for governance persistence models."""


class RiskProfileLevel(StrEnum):
    """Risk profile label used by dashboard position sizing."""

    CONSERVATIVE = "Conservative"
    BALANCED = "Balanced"
    AGGRESSIVE = "Aggressive"


class AccountMode(StrEnum):
    """Trading mode of account."""

    PAPER = "PAPER"
    LIVE = "LIVE"


class EAStatus(StrEnum):
    """Runtime status of an EA instance."""

    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class StrategyType(StrEnum):
    """Executor parameter profile per EA instance."""

    H1_SWING = "H1_SWING"
    M15_SCALP = "M15_SCALP"


class PropFirmRule(Base):
    """Prop-firm limits and phase policy metadata."""

    __tablename__ = "prop_firm_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, nullable=False)
    max_total_loss: Mapped[float] = mapped_column(Float, nullable=False)
    profit_target: Mapped[float] = mapped_column(Float, nullable=False)
    consistency_rule: Mapped[str] = mapped_column(String(255), nullable=False)
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    accounts: Mapped[list[Account]] = relationship(back_populates="prop_firm", cascade="save-update")


class Account(Base):
    """Canonical account model for dashboard/risk governance state."""

    __tablename__ = "core_accounts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    broker: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    equity_high: Mapped[float] = mapped_column(Float, nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_profile: Mapped[RiskProfileLevel] = mapped_column(
        Enum(RiskProfileLevel, name="risk_profile_level"),
        nullable=False,
        default=RiskProfileLevel.BALANCED,
    )
    prop_firm_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prop_firm_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[AccountMode] = mapped_column(Enum(AccountMode, name="account_mode"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    prop_firm: Mapped[PropFirmRule | None] = relationship(back_populates="accounts")
    ea_instances: Mapped[list[EAInstance]] = relationship(back_populates="account", cascade="all, delete-orphan")


class EAInstance(Base):
    """EA runtime instance attached to an account (parameterized executor)."""

    __tablename__ = "ea_instances"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    strategy_type: Mapped[StrategyType] = mapped_column(
        Enum(StrategyType, name="strategy_type"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("core_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[EAStatus] = mapped_column(
        Enum(EAStatus, name="ea_status"),
        nullable=False,
        default=EAStatus.STOPPED,
    )
    safe_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    account: Mapped[Account] = relationship(back_populates="ea_instances")
