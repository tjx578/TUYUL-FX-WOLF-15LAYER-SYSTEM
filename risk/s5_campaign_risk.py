"""Strategy 5-S campaign risk primitives.

Compounding is based on closed balance. A campaign locks one risk unit when
its parent is authorized; parent and child use the same USD budget. Floating
profit never increases the risk unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from contracts.mt5_execution_protocol import AccountSnapshotV1, SymbolCapability


class S5RiskReason(StrEnum):
    APPROVED_PARENT = "RISK_APPROVED_PARENT"
    APPROVED_CHILD = "RISK_APPROVED_CHILD"
    SNAPSHOT_STALE = "RISK_SNAPSHOT_STALE"
    ACCOUNT_MISMATCH = "RISK_ACCOUNT_MISMATCH"
    SNAPSHOT_INCONSISTENT = "RISK_SNAPSHOT_INCONSISTENT"
    TRADE_DISABLED = "RISK_TRADE_DISABLED"
    INVALID_SYMBOL_SPEC = "RISK_INVALID_SYMBOL_SPEC"
    VOLUME_BELOW_MINIMUM = "RISK_VOLUME_BELOW_MINIMUM"
    VOLUME_ABOVE_MAXIMUM = "RISK_VOLUME_ABOVE_MAXIMUM"
    ACTUAL_EXCEEDS_1R = "RISK_ACTUAL_EXCEEDS_1R"
    CAMPAIGN_EXCEEDS_2R = "RISK_CAMPAIGN_EXCEEDS_2R"
    ACCOUNT_OPEN_RISK_EXCEEDED = "RISK_ACCOUNT_OPEN_RISK_EXCEEDED"
    CHILD_ALREADY_EXISTS = "RISK_CHILD_ALREADY_EXISTS"
    PARENT_NOT_OPEN = "RISK_PARENT_NOT_OPEN"
    INVALID_ENTRY_ROLE = "RISK_INVALID_ENTRY_ROLE"
    RISK_STATE_INVALID = "RISK_STATE_INVALID"


@dataclass(frozen=True, slots=True)
class CampaignRiskPolicy:
    risk_percent_per_entry: Decimal = Decimal("0.05")
    max_entries: int = 2
    max_total_open_risk_percent: Decimal = Decimal("0.10")
    snapshot_max_age_seconds: int = 30

    def __post_init__(self) -> None:
        if not Decimal("0") < self.risk_percent_per_entry <= Decimal("1"):
            raise ValueError("risk_percent_per_entry must be within (0, 1]")
        if self.max_entries != 2:
            raise ValueError("Strategy 5-S production policy supports exactly parent + one child")
        if self.max_total_open_risk_percent < self.risk_percent_per_entry:
            raise ValueError("account open-risk cap cannot be below one entry risk")
        if self.max_total_open_risk_percent > Decimal("1"):
            raise ValueError("account open-risk cap cannot exceed 100%")


@dataclass(frozen=True, slots=True)
class CampaignRiskLock:
    campaign_id: str
    account_id: str
    balance_base: Decimal
    risk_percent_per_entry: Decimal
    risk_unit_usd: Decimal
    max_campaign_risk_usd: Decimal
    locked_at_utc: datetime

    @classmethod
    def create(
        cls,
        *,
        campaign_id: str,
        account_id: str,
        closed_balance: float,
        policy: CampaignRiskPolicy,
        now: datetime | None = None,
    ) -> CampaignRiskLock:
        balance = Decimal(str(closed_balance))
        if balance <= 0:
            raise ValueError("closed_balance must be positive")
        risk_unit = balance * policy.risk_percent_per_entry
        return cls(
            campaign_id=campaign_id,
            account_id=account_id,
            balance_base=balance,
            risk_percent_per_entry=policy.risk_percent_per_entry,
            risk_unit_usd=risk_unit,
            max_campaign_risk_usd=risk_unit * policy.max_entries,
            locked_at_utc=(now or datetime.now(UTC)).astimezone(UTC),
        )


@dataclass(frozen=True, slots=True)
class SnapshotValidation:
    allowed: bool
    reason: S5RiskReason | None
    detail: str


@dataclass(frozen=True, slots=True)
class PositionRiskResult:
    allowed: bool
    reason: S5RiskReason
    risk_budget_usd: Decimal
    effective_loss_per_lot: Decimal
    raw_volume: Decimal
    final_volume: Decimal
    actual_planned_risk_usd: Decimal


def validate_account_snapshot(
    snapshot: AccountSnapshotV1,
    *,
    expected_account_id: str,
    policy: CampaignRiskPolicy,
    now: datetime | None = None,
) -> SnapshotValidation:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    age = (current - snapshot.captured_at_utc).total_seconds()
    if snapshot.account_id != expected_account_id:
        return SnapshotValidation(False, S5RiskReason.ACCOUNT_MISMATCH, "snapshot account binding mismatch")
    if age < -2 or age > policy.snapshot_max_age_seconds:
        return SnapshotValidation(False, S5RiskReason.SNAPSHOT_STALE, f"snapshot age {age:.3f}s outside policy")
    if not snapshot.trade_allowed or not snapshot.autotrading_enabled:
        return SnapshotValidation(False, S5RiskReason.TRADE_DISABLED, "broker or terminal trading is disabled")

    expected_equity = Decimal(str(snapshot.balance)) + Decimal(str(snapshot.floating_pnl))
    observed_equity = Decimal(str(snapshot.equity))
    tolerance = max(Decimal("1.00"), Decimal(str(snapshot.balance)) * Decimal("0.001"))
    if abs(observed_equity - expected_equity) > tolerance:
        return SnapshotValidation(
            False,
            S5RiskReason.SNAPSHOT_INCONSISTENT,
            "equity does not reconcile with balance plus floating P/L",
        )
    return SnapshotValidation(True, None, "snapshot accepted")


def find_symbol_capability(
    snapshot: AccountSnapshotV1,
    *,
    canonical_symbol: str,
    broker_symbol: str,
) -> SymbolCapability | None:
    for spec in snapshot.symbols:
        if spec.canonical_symbol == canonical_symbol and spec.broker_symbol == broker_symbol:
            return spec
    return None


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    units = (value / step).to_integral_value(rounding=ROUND_FLOOR)
    return units * step


def size_position_for_locked_risk(
    *,
    risk_lock: CampaignRiskLock,
    symbol_spec: SymbolCapability,
    entry_price: float,
    stop_loss: float,
    entry_role: str,
    commission_buffer_per_lot: float = 0.0,
    slippage_buffer_per_lot: float = 0.0,
) -> PositionRiskResult:
    role = entry_role.upper()
    if role not in {"PARENT", "CHILD"}:
        return PositionRiskResult(
            False,
            S5RiskReason.INVALID_ENTRY_ROLE,
            risk_lock.risk_unit_usd,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )
    distance = abs(Decimal(str(entry_price)) - Decimal(str(stop_loss)))
    tick_size = Decimal(str(symbol_spec.tick_size))
    tick_value_loss = Decimal(str(symbol_spec.tick_value_loss))
    commission_buffer = Decimal(str(commission_buffer_per_lot))
    slippage_buffer = Decimal(str(slippage_buffer_per_lot))
    if distance <= 0 or tick_size <= 0 or tick_value_loss <= 0 or commission_buffer < 0 or slippage_buffer < 0:
        return PositionRiskResult(
            False,
            S5RiskReason.INVALID_SYMBOL_SPEC,
            risk_lock.risk_unit_usd,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )

    ticks_to_stop = distance / tick_size
    effective_loss = ticks_to_stop * tick_value_loss + commission_buffer + slippage_buffer
    if effective_loss <= 0:
        return PositionRiskResult(
            False,
            S5RiskReason.INVALID_SYMBOL_SPEC,
            risk_lock.risk_unit_usd,
            effective_loss,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )

    raw_volume = risk_lock.risk_unit_usd / effective_loss
    step = Decimal(str(symbol_spec.volume_step))
    final_volume = _floor_to_step(raw_volume, step)
    minimum = Decimal(str(symbol_spec.volume_min))
    maximum = Decimal(str(symbol_spec.volume_max))
    approved_reason = S5RiskReason.APPROVED_CHILD if role == "CHILD" else S5RiskReason.APPROVED_PARENT

    if final_volume < minimum:
        return PositionRiskResult(
            False,
            S5RiskReason.VOLUME_BELOW_MINIMUM,
            risk_lock.risk_unit_usd,
            effective_loss,
            raw_volume,
            final_volume,
            final_volume * effective_loss,
        )
    if final_volume > maximum:
        return PositionRiskResult(
            False,
            S5RiskReason.VOLUME_ABOVE_MAXIMUM,
            risk_lock.risk_unit_usd,
            effective_loss,
            raw_volume,
            final_volume,
            final_volume * effective_loss,
        )

    actual_risk = final_volume * effective_loss
    if actual_risk > risk_lock.risk_unit_usd:
        return PositionRiskResult(
            False,
            S5RiskReason.ACTUAL_EXCEEDS_1R,
            risk_lock.risk_unit_usd,
            effective_loss,
            raw_volume,
            final_volume,
            actual_risk,
        )
    return PositionRiskResult(
        True,
        approved_reason,
        risk_lock.risk_unit_usd,
        effective_loss,
        raw_volume,
        final_volume,
        actual_risk,
    )


def authorize_campaign_risk(
    *,
    risk_lock: CampaignRiskLock,
    candidate: PositionRiskResult,
    entry_role: str,
    parent_is_open: bool,
    child_already_exists: bool,
    committed_or_reserved_campaign_risk_usd: float,
    account_total_open_risk_usd: float,
    policy: CampaignRiskPolicy,
) -> S5RiskReason:
    role = entry_role.upper()
    if role not in {"PARENT", "CHILD"}:
        return S5RiskReason.INVALID_ENTRY_ROLE
    if committed_or_reserved_campaign_risk_usd < 0 or account_total_open_risk_usd < 0:
        return S5RiskReason.RISK_STATE_INVALID
    if not candidate.allowed:
        return candidate.reason
    if role == "CHILD" and not parent_is_open:
        return S5RiskReason.PARENT_NOT_OPEN
    if role == "CHILD" and child_already_exists:
        return S5RiskReason.CHILD_ALREADY_EXISTS

    combined_campaign = Decimal(str(committed_or_reserved_campaign_risk_usd)) + candidate.actual_planned_risk_usd
    if combined_campaign > risk_lock.max_campaign_risk_usd:
        return S5RiskReason.CAMPAIGN_EXCEEDS_2R

    projected_open_risk = Decimal(str(account_total_open_risk_usd)) + candidate.actual_planned_risk_usd
    account_cap = risk_lock.balance_base * policy.max_total_open_risk_percent
    if projected_open_risk > account_cap:
        return S5RiskReason.ACCOUNT_OPEN_RISK_EXCEEDED
    return S5RiskReason.APPROVED_CHILD if role == "CHILD" else S5RiskReason.APPROVED_PARENT


__all__ = [
    "S5RiskReason",
    "CampaignRiskPolicy",
    "CampaignRiskLock",
    "SnapshotValidation",
    "PositionRiskResult",
    "validate_account_snapshot",
    "find_symbol_capability",
    "size_position_for_locked_risk",
    "authorize_campaign_risk",
]
