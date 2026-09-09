from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from contracts.mt5_execution_protocol import AccountSnapshotV1, MarginMode, SymbolCapability
from risk.s5_campaign_risk import (
    CampaignRiskLock,
    CampaignRiskPolicy,
    S5RiskReason,
    authorize_campaign_risk,
    campaign_risk_lock_fingerprint,
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
        now=datetime(2026, 9, 9, tzinfo=UTC),
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


def _authorize(candidate, **overrides):
    args = dict(
        risk_lock=_risk_lock(),
        candidate=candidate,
        entry_role="PARENT",
        parent_is_open=False,
        child_already_exists=False,
        committed_or_reserved_campaign_risk_usd=0,
        account_total_open_risk_usd=0,
        policy=CampaignRiskPolicy(),
    )
    args.update(overrides)
    return authorize_campaign_risk(**args)


def _sized_parent():
    return size_position_for_locked_risk(
        risk_lock=_risk_lock(), symbol_spec=_symbol(), entry_price=1.1, stop_loss=1.095, entry_role="PARENT"
    )


def test_sizing_from_different_risk_lock_cannot_borrow_current_campaign_capacity():
    larger = CampaignRiskLock.create(
        campaign_id="OTHER", account_id="acct-01", closed_balance=1200, policy=CampaignRiskPolicy()
    )
    candidate = size_position_for_locked_risk(
        risk_lock=larger, symbol_spec=_symbol(), entry_price=1.1, stop_loss=1.095, entry_role="PARENT"
    )
    assert candidate.actual_planned_risk_usd == Decimal("60")
    assert _authorize(candidate) == S5RiskReason.RISK_STATE_INVALID


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed": False},
        {"actual_planned_risk_usd": Decimal("-1")},
        {"actual_planned_risk_usd": Decimal("NaN")},
        {"effective_loss_per_lot": Decimal("Infinity")},
        {"actual_planned_risk_usd": Decimal("1")},
        {"reason": S5RiskReason.APPROVED_CHILD},
    ],
)
def test_inconsistent_sizing_cannot_authorize(changes):
    assert _authorize(replace(_sized_parent(), **changes)) == S5RiskReason.RISK_STATE_INVALID


@pytest.mark.parametrize("field", ["committed_or_reserved_campaign_risk_usd", "account_total_open_risk_usd"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_ledger_numbers_return_rejection(field, value):
    assert _authorize(_sized_parent(), **{field: value}) == S5RiskReason.RISK_STATE_INVALID


def test_current_lock_valid_candidate_is_still_approved():
    assert _authorize(_sized_parent()) == S5RiskReason.APPROVED_PARENT


def test_one_risk_unit_is_rechecked_even_when_campaign_cap_has_room():
    candidate = replace(
        _sized_parent(), final_volume=Decimal("0.12"), raw_volume=Decimal("0.12"), actual_planned_risk_usd=Decimal("60")
    )
    assert _authorize(candidate) == S5RiskReason.ACTUAL_EXCEEDS_1R


@pytest.mark.parametrize(
    "field,reason",
    [
        ("committed_or_reserved_campaign_risk_usd", S5RiskReason.CAMPAIGN_EXCEEDS_2R),
        ("account_total_open_risk_usd", S5RiskReason.ACCOUNT_OPEN_RISK_EXCEEDED),
    ],
)
def test_decimal_ledger_excess_is_not_rounded_down_at_cap(field, reason):
    total = Decimal("50.000000000000000000000000001")
    assert float(total) == 50.0  # The old repository conversion lost this excess.
    assert _authorize(_sized_parent(), **{field: total}) == reason


@pytest.mark.parametrize(
    "changes",
    [
        {"campaign_id": "OTHER_CAMPAIGN"},
        {"account_id": "OTHER_ACCOUNT"},
        {"locked_at_utc": datetime(2026, 9, 9, 0, 0, 1, tzinfo=UTC)},
        {"max_campaign_risk_usd": Decimal("101")},
    ],
)
def test_equal_budget_does_not_allow_cross_lock_sizing(changes):
    other = replace(_risk_lock(), **changes)
    candidate = size_position_for_locked_risk(
        risk_lock=other, symbol_spec=_symbol(), entry_price=1.1, stop_loss=1.095, entry_role="PARENT"
    )
    assert candidate.risk_budget_usd == _risk_lock().risk_unit_usd
    assert _authorize(candidate) == S5RiskReason.RISK_STATE_INVALID


def test_unbound_legacy_sizing_cannot_authorize():
    assert _authorize(replace(_sized_parent(), risk_lock_fingerprint=None)) == S5RiskReason.RISK_STATE_INVALID


def test_risk_lock_fingerprint_survives_decimal_database_scale():
    original = _risk_lock()
    restored = replace(
        original,
        balance_base=Decimal("1000.00000000"),
        risk_percent_per_entry=Decimal("0.05000000"),
        risk_unit_usd=Decimal("50.00000000"),
        max_campaign_risk_usd=Decimal("100.00000000"),
    )
    assert campaign_risk_lock_fingerprint(original) == campaign_risk_lock_fingerprint(restored)
    assert _authorize(_sized_parent(), risk_lock=restored) == S5RiskReason.APPROVED_PARENT


def test_naive_lock_clock_is_rejected_explicitly():
    invalid = replace(_risk_lock(), locked_at_utc=datetime(2026, 9, 9))
    assert _authorize(_sized_parent(), risk_lock=invalid) == S5RiskReason.RISK_STATE_INVALID


@pytest.mark.parametrize("currency", ["JPY", "EUR", "USC"])
def test_usd_risk_does_not_assume_account_currency_conversion(currency):
    snapshot = _snapshot().model_copy(update={"currency": currency})
    verdict = validate_account_snapshot(snapshot, expected_account_id="acct-01", policy=CampaignRiskPolicy())
    assert not verdict.allowed
    assert verdict.reason == S5RiskReason.ACCOUNT_CURRENCY_UNSUPPORTED
