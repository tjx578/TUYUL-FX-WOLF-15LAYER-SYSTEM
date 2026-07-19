from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from contracts.mt5_execution_protocol import AccountSnapshotV1, MarginMode, SymbolCapability
from risk.s5_campaign_risk import (
    CampaignRiskLock,
    CampaignRiskPolicy,
    S5RiskReason,
    authorize_campaign_risk,
    size_position_for_locked_risk,
    validate_account_snapshot,
)


def _symbol(**overrides: float) -> SymbolCapability:
    payload = {
        "canonical_symbol": "EURUSD",
        "broker_symbol": "EURUSD.a",
        "digits": 5,
        "point": 0.00001,
        "tick_size": 0.00001,
        "tick_value_profit": 1.0,
        "tick_value_loss": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "stops_level_points": 10,
        "freeze_level_points": 0,
        "expiration_modes": ["SPECIFIED"],
    }
    payload.update(overrides)
    return SymbolCapability.model_validate(payload)


def _snapshot(*, captured_at: datetime | None = None) -> AccountSnapshotV1:
    executor_id = uuid4()
    return AccountSnapshotV1(
        snapshot_id="snapshot-001",
        captured_at_utc=captured_at or datetime.now(UTC),
        executor_id=executor_id,
        account_id="acct-01",
        currency="USD",
        balance=1000,
        equity=1030,
        floating_pnl=30,
        used_margin=100,
        free_margin=930,
        margin_level_pct=1030,
        margin_mode=MarginMode.HEDGING,
        trade_allowed=True,
        autotrading_enabled=True,
        symbols=[_symbol()],
    )


def _risk_lock() -> CampaignRiskLock:
    return CampaignRiskLock.create(
        campaign_id="EURUSD-CAMPAIGN-001",
        account_id="acct-01",
        closed_balance=1000,
        policy=CampaignRiskPolicy(),
    )


def test_campaign_locks_five_percent_from_closed_balance() -> None:
    lock = _risk_lock()
    assert lock.risk_unit_usd == Decimal("50.00")
    assert lock.max_campaign_risk_usd == Decimal("100.00")


def test_broker_aware_volume_rounds_down() -> None:
    result = size_position_for_locked_risk(
        risk_lock=_risk_lock(),
        symbol_spec=_symbol(volume_step=0.01),
        entry_price=1.10000,
        stop_loss=1.09490,
        entry_role="PARENT",
    )
    assert result.allowed
    assert result.final_volume == Decimal("0.09")
    assert result.actual_planned_risk_usd <= Decimal("50")


def test_volume_is_never_clamped_up_to_broker_minimum() -> None:
    result = size_position_for_locked_risk(
        risk_lock=_risk_lock(),
        symbol_spec=_symbol(volume_min=0.1, volume_step=0.1),
        entry_price=1.10000,
        stop_loss=1.00000,
        entry_role="PARENT",
    )
    assert not result.allowed
    assert result.reason == S5RiskReason.VOLUME_BELOW_MINIMUM
    assert result.final_volume == Decimal("0.0")


def test_negative_cost_buffer_fails_closed() -> None:
    result = size_position_for_locked_risk(
        risk_lock=_risk_lock(),
        symbol_spec=_symbol(),
        entry_price=1.10000,
        stop_loss=1.09500,
        entry_role="PARENT",
        commission_buffer_per_lot=-1,
    )
    assert not result.allowed
    assert result.reason == S5RiskReason.INVALID_SYMBOL_SPEC


def test_unknown_entry_role_fails_closed() -> None:
    result = size_position_for_locked_risk(
        risk_lock=_risk_lock(),
        symbol_spec=_symbol(),
        entry_price=1.10000,
        stop_loss=1.09500,
        entry_role="REVERSAL",
    )
    assert not result.allowed
    assert result.reason == S5RiskReason.INVALID_ENTRY_ROLE


def test_child_requires_open_parent() -> None:
    candidate = size_position_for_locked_risk(
        risk_lock=_risk_lock(),
        symbol_spec=_symbol(),
        entry_price=1.10000,
        stop_loss=1.09500,
        entry_role="CHILD",
    )
    reason = authorize_campaign_risk(
        risk_lock=_risk_lock(),
        candidate=candidate,
        entry_role="CHILD",
        parent_is_open=False,
        child_already_exists=False,
        committed_or_reserved_campaign_risk_usd=50,
        account_total_open_risk_usd=50,
        policy=CampaignRiskPolicy(),
    )
    assert reason == S5RiskReason.PARENT_NOT_OPEN


def test_account_cap_blocks_additional_campaign() -> None:
    candidate = size_position_for_locked_risk(
        risk_lock=_risk_lock(),
        symbol_spec=_symbol(),
        entry_price=1.10000,
        stop_loss=1.09500,
        entry_role="PARENT",
    )
    reason = authorize_campaign_risk(
        risk_lock=_risk_lock(),
        candidate=candidate,
        entry_role="PARENT",
        parent_is_open=False,
        child_already_exists=False,
        committed_or_reserved_campaign_risk_usd=0,
        account_total_open_risk_usd=75,
        policy=CampaignRiskPolicy(),
    )
    assert reason == S5RiskReason.ACCOUNT_OPEN_RISK_EXCEEDED


def test_stale_snapshot_fails_closed() -> None:
    snapshot = _snapshot(captured_at=datetime.now(UTC) - timedelta(minutes=2))
    result = validate_account_snapshot(
        snapshot,
        expected_account_id="acct-01",
        policy=CampaignRiskPolicy(snapshot_max_age_seconds=30),
    )
    assert not result.allowed
    assert result.reason == S5RiskReason.SNAPSHOT_STALE
