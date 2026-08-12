"""Material identity, state-machine, and fail-closed gates for P3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_context_epoch_v1 import (
    ContextEpochReducerV1,
    context_evidence_hash,
    material_context_hash,
)
from contracts.strategy_5scr_context_epoch_v1 import (
    ContextCandleAuthorityV1,
    ContextTimeframe,
    DirectionDomain,
    MaterialContextEvidenceV1,
    ProviderTimestampSemantics,
)

START = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
LIFECYCLE = "5scr-lifecycle:11111111111111111111111111111111"
SYMBOL = "EURUSD"


def _candle(
    timeframe: ContextTimeframe,
    candle_id: str,
    *,
    close: datetime,
    complete: bool = True,
    semantics: ProviderTimestampSemantics = "PERIOD_OPEN",
    lineage_valid: bool = True,
    authority: bool = True,
) -> ContextCandleAuthorityV1:
    duration = timedelta(days=1) if timeframe == "D1" else timedelta(hours=4)
    return ContextCandleAuthorityV1(
        candle_id=candle_id,
        symbol=SYMBOL,
        timeframe=timeframe,
        open_time_utc=close - duration,
        close_time_utc=close,
        complete=complete,
        provider="XM_DEMO",
        provider_timestamp_semantics=semantics,
        provider_session_lineage_valid=lineage_valid,
        structural_authority=authority,
    )


def _evidence(
    index: int = 0,
    *,
    daily_bias: str | None = "BULLISH",
    h4_structure: str | None = "BULLISH_PULLBACK",
    price_location: str | None = "H4_DISCOUNT",
    liquidity_state: str | None = "SELL_SIDE_LIQUIDITY_RECLAIMED",
    direction_domain: DirectionDomain | None = "BUY_ONLY",
    d1_candles: tuple[ContextCandleAuthorityV1, ...] | None = None,
    h4_candles: tuple[ContextCandleAuthorityV1, ...] | None = None,
    target_map_version: str | None = "targets-v1",
    invalidation_version: str | None = "invalidation-v1",
    deterministic: bool = True,
    future_leakage: bool = False,
    deployment: str = "deploy-a",
    cluster: str = "cluster-a",
    stage: str = "SIGNAL_THROTTLE_INTEL",
    family: str = "PRESSURE_REFRESH",
    reference_price: float = 1.1,
    microboost_hash: str = "sha256:" + "a" * 64,
    allowed_routes: tuple[str, ...] = ("BUY_BREAK_RETEST",),
    blocked_routes: tuple[str, ...] = ("SELL_BREAKOUT_CHASE",),
) -> MaterialContextEvidenceV1:
    observed = START + timedelta(seconds=index)
    event_id = f"pressure:{index:04d}"
    return MaterialContextEvidenceV1(
        source_pressure_event_id=event_id,
        source_event_ids=(event_id,),
        symbol=SYMBOL,
        observed_at_utc=observed,
        d1_candles=(_candle("D1", "d1:2026-08-11", close=START - timedelta(hours=8)),)
        if d1_candles is None
        else d1_candles,
        h4_candles=(_candle("H4", "h4:2026-08-12T04", close=START - timedelta(hours=1)),)
        if h4_candles is None
        else h4_candles,
        daily_bias=daily_bias,
        h4_structure=h4_structure,
        price_location=price_location,
        liquidity_state=liquidity_state,
        direction_domain=direction_domain,
        allowed_routes=allowed_routes,
        blocked_routes=blocked_routes,
        target_map_version=target_map_version,
        structural_invalidation_version=invalidation_version,
        deterministic_context=deterministic,
        future_candle_leakage_detected=future_leakage,
        source_deployment_id=deployment,
        source_replica_id=f"replica-{index}",
        source_cluster_id=cluster,
        source_stage=stage,
        source_family=family,
        reference_price=reference_price,
        microboost_evidence_hash=microboost_hash,
    )


def test_same_context_repeated_100_times_is_one_epoch() -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    results = [reducer.ingest(_evidence(index)) for index in range(100)]

    assert results[0].status == "OPENED"
    assert all(item.status == "CONFIRMED" for item in results[1:])
    assert reducer.epoch is not None
    assert reducer.epoch.epoch_sequence == 1
    assert reducer.epoch.state_version == 100


def test_lineage_and_reference_price_churn_do_not_change_material_identity() -> None:
    first = _evidence()
    churned = _evidence(
        1,
        deployment="deploy-z",
        cluster="cluster-z",
        stage="BLOCK_FINALIZER",
        family="BLOCK_REFRESH",
        reference_price=1.12345,
        microboost_hash="sha256:" + "f" * 64,
    )

    assert material_context_hash(first) == material_context_hash(churned)
    assert context_evidence_hash(first) != context_evidence_hash(churned)
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    reducer.ingest(first)
    result = reducer.ingest(churned)
    assert result.status == "CONFIRMED"
    assert result.epoch is not None and result.epoch.epoch_sequence == 1


@pytest.mark.parametrize(
    "change",
    (
        {"liquidity_state": "BUY_SIDE_LIQUIDITY_REJECTED"},
        {"price_location": "H4_PREMIUM"},
        {"direction_domain": "SELL_ONLY"},
        {"target_map_version": "targets-v2"},
        {"invalidation_version": "invalidation-v2"},
        {"daily_bias": "BEARISH"},
        {"h4_structure": "BEARISH_IMPULSE"},
        {"d1_candles": (_candle("D1", "d1:2026-08-12", close=START - timedelta(hours=4)),)},
        {"h4_candles": (_candle("H4", "h4:2026-08-12T08", close=START - timedelta(minutes=30)),)},
        {"allowed_routes": ("BUY_BREAK_RETEST", "BUY_CONTINUATION")},
        {"blocked_routes": ("BUY_REVERSAL", "SELL_BREAKOUT_CHASE")},
    ),
)
def test_material_change_opens_successor_epoch(change: dict[str, Any]) -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    opened = reducer.ingest(_evidence())
    transitioned = reducer.ingest(_evidence(1, **change))

    assert opened.epoch is not None
    assert transitioned.status == "TRANSITIONED"
    assert transitioned.previous_epoch is not None
    assert transitioned.previous_epoch.state == "SUPERSEDED"
    assert transitioned.previous_epoch.last_source_event_id == opened.epoch.last_source_event_id
    assert transitioned.epoch is not None
    assert transitioned.epoch.epoch_sequence == 2
    assert transitioned.transition is not None
    assert transitioned.transition.reason == "MATERIAL_CONTEXT_CHANGED"


def test_a_to_b_to_a_creates_three_distinct_epoch_identities() -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    first = reducer.ingest(_evidence())
    second = reducer.ingest(_evidence(1, liquidity_state="BUY_SIDE_LIQUIDITY_REJECTED"))
    third = reducer.ingest(_evidence(2))

    epochs = [first.epoch, second.epoch, third.epoch]
    assert all(epoch is not None for epoch in epochs)
    resolved = [epoch for epoch in epochs if epoch is not None]
    assert [item.epoch_sequence for item in resolved] == [1, 2, 3]
    assert resolved[0].material_context_hash == resolved[2].material_context_hash
    assert resolved[0].context_epoch_id != resolved[2].context_epoch_id


def test_duplicate_and_restart_recover_same_active_epoch() -> None:
    first = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    opened = first.ingest(_evidence())
    assert opened.epoch is not None

    restarted = ContextEpochReducerV1(LIFECYCLE, SYMBOL, initial_epoch=opened.epoch)
    duplicate = restarted.ingest(_evidence())
    confirmed = restarted.ingest(_evidence(1))

    assert duplicate.status == "DUPLICATE"
    assert confirmed.status == "CONFIRMED"
    assert confirmed.epoch is not None
    assert confirmed.epoch.context_epoch_id == opened.epoch.context_epoch_id


def test_same_source_event_with_changed_material_is_quarantined() -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    opened = reducer.ingest(_evidence())
    drifted = reducer.ingest(_evidence(liquidity_state="BUY_SIDE_LIQUIDITY_REJECTED"))

    assert opened.epoch is not None
    assert drifted.status == "QUARANTINED_CONTEXT_EVIDENCE"
    assert drifted.reason_code == "SOURCE_EVENT_MATERIAL_CONTEXT_DRIFT"
    assert reducer.epoch == opened.epoch


@pytest.mark.parametrize("advance_timestamp", (False, True))
def test_same_source_event_with_changed_lineage_is_quarantined(advance_timestamp: bool) -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    evidence = _evidence()
    opened = reducer.ingest(evidence)
    updates: dict[str, object] = {"source_deployment_id": "deploy-drifted"}
    if advance_timestamp:
        updates["observed_at_utc"] = evidence.observed_at_utc + timedelta(seconds=1)
    drifted_evidence = evidence.model_copy(update=updates)
    drifted = reducer.ingest(drifted_evidence)

    assert opened.epoch is not None
    assert material_context_hash(evidence) == material_context_hash(drifted_evidence)
    assert context_evidence_hash(evidence) != context_evidence_hash(drifted_evidence)
    assert drifted.status == "QUARANTINED_CONTEXT_EVIDENCE"
    assert drifted.reason_code == "SOURCE_EVENT_CONTEXT_EVIDENCE_DRIFT"
    assert reducer.epoch == opened.epoch


@pytest.mark.parametrize(
    ("evidence", "status", "reason"),
    (
        (_evidence(d1_candles=()), "WAITING_CONTEXT_EVIDENCE", "D1_CLOSED_CANDLE_EVIDENCE_MISSING"),
        (_evidence(h4_candles=()), "WAITING_CONTEXT_EVIDENCE", "H4_CLOSED_CANDLE_EVIDENCE_MISSING"),
        (
            _evidence(d1_candles=(_candle("D1", "d1:incomplete", close=START - timedelta(hours=8), complete=False),)),
            "WAITING_CONTEXT_EVIDENCE",
            "SOURCE_CANDLE_INCOMPLETE",
        ),
        (
            _evidence(
                h4_candles=(_candle("H4", "h4:unknown", close=START - timedelta(hours=1), semantics="UNSPECIFIED"),)
            ),
            "QUARANTINED_CONTEXT_EVIDENCE",
            "PROVIDER_SESSION_LINEAGE_INVALID",
        ),
        (
            _evidence(
                d1_candles=(_candle("D1", "d1:no-authority", close=START - timedelta(hours=8), authority=False),)
            ),
            "WAITING_CONTEXT_EVIDENCE",
            "D1_STRUCTURAL_AUTHORITY_MISSING",
        ),
        (
            _evidence(
                h4_candles=(_candle("H4", "h4:no-authority", close=START - timedelta(hours=1), authority=False),)
            ),
            "WAITING_CONTEXT_EVIDENCE",
            "H4_STRUCTURAL_AUTHORITY_MISSING",
        ),
        (
            _evidence(
                h4_candles=(_candle("H4", "h4:bad-lineage", close=START - timedelta(hours=1), lineage_valid=False),)
            ),
            "QUARANTINED_CONTEXT_EVIDENCE",
            "PROVIDER_SESSION_LINEAGE_INVALID",
        ),
        (
            _evidence(h4_candles=(_candle("H4", "h4:future", close=START + timedelta(hours=1)),)),
            "QUARANTINED_CONTEXT_EVIDENCE",
            "FUTURE_CANDLE_LEAKAGE",
        ),
        (_evidence(future_leakage=True), "QUARANTINED_CONTEXT_EVIDENCE", "FUTURE_CANDLE_LEAKAGE"),
        (
            _evidence(deterministic=False),
            "QUARANTINED_CONTEXT_EVIDENCE",
            "MATERIAL_CONTEXT_NON_DETERMINISTIC",
        ),
        (_evidence(daily_bias=None), "WAITING_CONTEXT_EVIDENCE", "MATERIAL_CONTEXT_FIELDS_MISSING:DAILY_BIAS"),
    ),
)
def test_invalid_authority_fails_closed(
    evidence: MaterialContextEvidenceV1,
    status: str,
    reason: str,
) -> None:
    result = ContextEpochReducerV1(LIFECYCLE, SYMBOL).ingest(evidence)
    assert result.status == status
    assert result.reason_code == reason
    assert result.epoch is None


def test_terminal_epoch_cannot_resurrect() -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    reducer.ingest(_evidence())
    terminal = reducer.terminalize(_evidence(1))
    resurrect = reducer.ingest(_evidence(2, liquidity_state="BUY_SIDE_LIQUIDITY_REJECTED"))

    assert terminal.status == "TERMINATED"
    assert terminal.previous_epoch is not None and terminal.previous_epoch.state == "TERMINAL"
    assert terminal.epoch is not None and terminal.epoch.state == "TERMINAL"
    assert terminal.epoch.evidence_hash == context_evidence_hash(_evidence(1))
    assert resurrect.status == "REJECTED"
    assert resurrect.reason_code == "TERMINAL_CONTEXT_EPOCH"


@pytest.mark.parametrize("terminal_index", (5, 4), ids=("same-event", "late-event"))
def test_parent_terminal_authority_closes_epoch_despite_nonadvancing_context_cursor(terminal_index: int) -> None:
    reducer = ContextEpochReducerV1(LIFECYCLE, SYMBOL)
    opened_evidence = _evidence(5)
    opened = reducer.ingest(opened_evidence)
    terminal_at = _evidence(6).observed_at_utc

    terminal = reducer.terminalize(_evidence(terminal_index), terminal_at_utc=terminal_at)

    assert opened.epoch is not None
    assert terminal.status == "TERMINATED"
    assert terminal.epoch is not None and terminal.epoch.state == "TERMINAL"
    assert terminal.epoch.closed_at_utc == terminal_at
    assert terminal.epoch.last_observed_at_utc == opened.epoch.last_observed_at_utc
    assert terminal.epoch.last_source_event_id == opened.epoch.last_source_event_id
    assert terminal.epoch.evidence_hash == opened.epoch.evidence_hash
    assert terminal.transition is not None
    assert terminal.transition.reason == "LIFECYCLE_TERMINAL"
    assert terminal.transition.occurred_at_utc == terminal_at


def test_execution_authority_cannot_be_enabled() -> None:
    payload = _evidence().model_dump(mode="python")
    payload["execution_authority"] = True
    with pytest.raises(ValidationError):
        MaterialContextEvidenceV1.model_validate(payload)
