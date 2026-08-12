"""P4 domain, authority, ordering, identity, and immutability gates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_directional_thesis_v1 import (
    DirectionalThesisBuildArtifact,
    build_directional_thesis_proofs,
    candle_evidence_hash,
    candle_material_hash,
    close_directional_thesis,
)
from analysis.strategy_5scr_structural_proof_provider_v1 import candle_authority_from_row
from contracts.strategy_5scr_context_epoch_v1 import DirectionDomain, StrategyContextEpochV1
from contracts.strategy_5scr_directional_thesis_v1 import (
    ClosedCandleAuthorityRefV1,
    Direction,
    DirectionalThesisEvidenceV1,
    DirectionalThesisV1,
    PressureContractStatus,
    PressureDirectionAuthorityV1,
    RouteDirectionAuthorizationV1,
)

START = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
DECISION = START + timedelta(hours=4)
LIFECYCLE = "5scr-lifecycle:11111111111111111111111111111111"
CONTEXT = "5scr-context:22222222222222222222222222222222"
SYMBOL = "EURUSD"
BUY_ROUTE = "BUY_BREAK_RETEST"
SELL_ROUTE = "SELL_BREAK_RETEST"


def _tag(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _row(
    *,
    row_id: int,
    timeframe: Literal["H1", "M15"],
    open_time: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
    provider: str = "XM_DEMO",
    feed: str = "primary",
    content_seed: str | None = None,
) -> dict[str, Any]:
    duration = timedelta(hours=1) if timeframe == "H1" else timedelta(minutes=15)
    return {
        "id": row_id,
        "symbol": SYMBOL,
        "timeframe": timeframe,
        "open_time": open_time,
        "close_time": open_time + duration,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100,
        "tick_count": 20,
        "selected_provider": provider,
        "selected_feed": feed,
        "provider_timestamp_semantics": "CANONICAL_WINDOW",
        "selected_raw_candle_id": row_id + 1_000,
        "selection_policy": "5scr.provider-priority.v1",
        "selection_rank": 1_300,
        "content_hash": hashlib.sha256((content_seed or f"content-{row_id}").encode()).hexdigest(),
    }


def _candle(**row: Any) -> ClosedCandleAuthorityRefV1:
    return candle_authority_from_row(_row(**row))


def _rehash_candle(payload: dict[str, Any]) -> ClosedCandleAuthorityRefV1:
    """Rebuild both nested hashes after an intentional fixture mutation."""

    payload = dict(payload)
    payload["material_candle_hash"] = "sha256:" + "0" * 64
    payload["candle_evidence_id"] = "sha256:" + "0" * 64
    candidate = ClosedCandleAuthorityRefV1.model_validate(payload)
    candidate = candidate.model_copy(update={"material_candle_hash": candle_material_hash(candidate)})
    return candidate.model_copy(update={"candle_evidence_id": candle_evidence_hash(candidate)})


def _candles(direction: Direction) -> tuple[tuple[ClosedCandleAuthorityRefV1, ...], ...]:
    if direction == "BUY":
        h1 = (
            _candle(
                row_id=1,
                timeframe="H1",
                open_time=START,
                open_price=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1000,
            ),
            _candle(
                row_id=2,
                timeframe="H1",
                open_time=START + timedelta(hours=1),
                open_price=1.1000,
                high=1.1030,
                low=1.0995,
                close=1.1020,
            ),
        )
        m15 = (
            _candle(
                row_id=3,
                timeframe="M15",
                open_time=START + timedelta(hours=1, minutes=45),
                open_price=1.1000,
                high=1.1010,
                low=1.0995,
                close=1.1005,
            ),
            _candle(
                row_id=4,
                timeframe="M15",
                open_time=START + timedelta(hours=2),
                open_price=1.1005,
                high=1.1020,
                low=1.1000,
                close=1.1015,
            ),
            _candle(
                row_id=5,
                timeframe="M15",
                open_time=START + timedelta(hours=2, minutes=15),
                open_price=1.1015,
                high=1.1022,
                low=1.1008,
                close=1.1016,
            ),
        )
    else:
        h1 = (
            _candle(
                row_id=11,
                timeframe="H1",
                open_time=START,
                open_price=1.1020,
                high=1.1030,
                low=1.1000,
                close=1.1020,
            ),
            _candle(
                row_id=12,
                timeframe="H1",
                open_time=START + timedelta(hours=1),
                open_price=1.1020,
                high=1.1025,
                low=1.0980,
                close=1.0990,
            ),
        )
        m15 = (
            _candle(
                row_id=13,
                timeframe="M15",
                open_time=START + timedelta(hours=1, minutes=45),
                open_price=1.1010,
                high=1.1015,
                low=1.1000,
                close=1.1005,
            ),
            _candle(
                row_id=14,
                timeframe="M15",
                open_time=START + timedelta(hours=2),
                open_price=1.1005,
                high=1.1008,
                low=1.0985,
                close=1.0990,
            ),
            _candle(
                row_id=15,
                timeframe="M15",
                open_time=START + timedelta(hours=2, minutes=15),
                open_price=1.0990,
                high=1.1002,
                low=1.0980,
                close=1.0988,
            ),
        )
    return h1, m15


def _context(
    domain: DirectionDomain = "BUY_ONLY",
    *,
    context_id: str = CONTEXT,
    state: Literal["ACTIVE", "SUPERSEDED", "TERMINAL"] = "ACTIVE",
) -> StrategyContextEpochV1:
    closed_at = None if state == "ACTIVE" else START + timedelta(hours=5)
    return StrategyContextEpochV1(
        context_epoch_id=context_id,
        strategy_lifecycle_id=LIFECYCLE,
        symbol=SYMBOL,
        epoch_sequence=1,
        state=state,
        material_context_hash=_tag({"context": context_id}),
        opened_at_utc=START,
        last_confirmed_at_utc=START,
        closed_at_utc=closed_at,
        daily_source_candle_ids=("d1:2026-08-11",),
        h4_source_candle_ids=("h4:2026-08-12T04",),
        daily_bias="BULLISH",
        h4_structure="BULLISH_PULLBACK",
        price_location="H4_DISCOUNT",
        liquidity_state="SELL_SIDE_LIQUIDITY_RECLAIMED",
        direction_domain=domain,
        allowed_routes=(BUY_ROUTE, SELL_ROUTE),
        blocked_routes=(),
        target_map_version="targets-v1",
        structural_invalidation_version="invalidation-v1",
        transition_reason="OPENED",
        evidence_hash=_tag({"evidence": context_id}),
        last_observed_at_utc=START,
        last_source_event_id="pressure:context",
        state_version=1,
    )


def _pressure(
    *,
    mode: Literal["RADAR_ONLY", "CONSOLIDATED_DIRECTION_CONTRACT"] = "RADAR_ONLY",
    status: PressureContractStatus | None = None,
    raw_direction: Direction | None = "BUY",
    contract_direction: Direction | None = None,
    observed_at: datetime = START,
    valid_until: datetime | None = DECISION + timedelta(hours=1),
) -> PressureDirectionAuthorityV1:
    resolved_status: PressureContractStatus = status or ("RADAR_ONLY" if mode == "RADAR_ONLY" else "LOCKED")
    transition = (
        "pressure:formal-transition"
        if mode == "CONSOLIDATED_DIRECTION_CONTRACT" and resolved_status == "LOCKED"
        else None
    )
    source_ids = ("pressure:authority",) if transition is None else ("pressure:authority", transition)
    return PressureDirectionAuthorityV1(
        mode=mode,
        contract_status=resolved_status,
        raw_pressure_direction=raw_direction,
        contract_direction=contract_direction,
        source_event_ids=source_ids,
        formal_transition_event_id=transition,
        rule_version="5scr.pressure-direction-authority.v1",
        observed_at_utc=observed_at,
        valid_until_utc=valid_until,
    )


def _route(
    context: StrategyContextEpochV1, direction: Direction, *, variant: str = "a"
) -> RouteDirectionAuthorizationV1:
    selected_route = BUY_ROUTE if direction == "BUY" else SELL_ROUTE
    return RouteDirectionAuthorizationV1(
        context_epoch_id=context.context_epoch_id,
        material_context_hash=context.material_context_hash,
        selected_route=selected_route,
        strategy_direction=direction,
        source_event_ids=(f"route:{variant}",),
        rule_version="5scr.route-direction.v1",
    )


def _evidence(
    context: StrategyContextEpochV1,
    direction: Direction,
    *,
    pressure: PressureDirectionAuthorityV1 | None = None,
    route: RouteDirectionAuthorizationV1 | None = None,
    h1: tuple[ClosedCandleAuthorityRefV1, ...] | None = None,
    m15: tuple[ClosedCandleAuthorityRefV1, ...] | None = None,
    decision: datetime = DECISION,
    request_id: str = "request-a",
) -> DirectionalThesisEvidenceV1:
    default_h1, default_m15 = _candles(direction)
    return DirectionalThesisEvidenceV1(
        strategy_lifecycle_id=LIFECYCLE,
        context_epoch_id=context.context_epoch_id,
        symbol=SYMBOL,
        decision_at_utc=decision,
        strategy_direction=direction,
        selected_route=BUY_ROUTE if direction == "BUY" else SELL_ROUTE,
        pressure_authority=pressure or _pressure(raw_direction=direction),
        route_authorization=route,
        h1_candles=default_h1 if h1 is None else h1,
        m15_candles=default_m15 if m15 is None else m15,
        source_request_id=request_id,
    )


def _artifact(context: StrategyContextEpochV1, direction: Direction, **kwargs: Any) -> DirectionalThesisBuildArtifact:
    result = build_directional_thesis_proofs(context=context, evidence=_evidence(context, direction, **kwargs))
    assert result.status == "READY", result.reason_code
    assert result.artifact is not None
    return result.artifact


def _thesis(
    context: StrategyContextEpochV1,
    direction: Direction,
    artifact: DirectionalThesisBuildArtifact,
    *,
    pressure: PressureDirectionAuthorityV1,
    route: RouteDirectionAuthorizationV1 | None = None,
    counter_pressure_hash: str | None = None,
    sequence: int = 1,
) -> DirectionalThesisV1:
    return DirectionalThesisV1(
        strategy_thesis_id="5scr-thesis:" + artifact.semantic_identity_hash.removeprefix("sha256:")[:32],
        strategy_lifecycle_id=LIFECYCLE,
        context_epoch_id=context.context_epoch_id,
        thesis_sequence=sequence,
        symbol=SYMBOL,
        strategy_direction=direction,
        direction_domain_at_creation=context.direction_domain,
        selected_route=BUY_ROUTE if direction == "BUY" else SELL_ROUTE,
        route_authorization_hash=None if route is None else route.authorization_hash,
        pressure_authority_mode=pressure.mode,
        pressure_contract_status=pressure.contract_status,
        pressure_reference_direction=(
            pressure.contract_direction
            if pressure.mode == "CONSOLIDATED_DIRECTION_CONTRACT"
            else pressure.raw_pressure_direction
        ),
        pressure_formal_transition_event_id=pressure.formal_transition_event_id,
        pressure_authority_hash=pressure.authority_hash,
        counter_pressure_proof_hash=(
            artifact.counter_pressure_proof_hash if counter_pressure_hash is None else counter_pressure_hash
        ),
        h1_proof_id=artifact.h1_proof.h1_proof_id,
        m15_proof_id=artifact.m15_proof.m15_proof_id,
        structural_proof_hash=artifact.structural_proof_hash,
        semantic_identity_hash=artifact.semantic_identity_hash,
        created_at_utc=DECISION,
    )


@pytest.mark.parametrize(
    ("domain", "direction", "expected_status", "expected_reason"),
    (
        ("BUY_ONLY", "BUY", "READY", None),
        ("BUY_ONLY", "SELL", "REJECTED", "CONTEXT_DIRECTION_DOMAIN_MISMATCH"),
        ("SELL_ONLY", "SELL", "READY", None),
        ("SELL_ONLY", "BUY", "REJECTED", "CONTEXT_DIRECTION_DOMAIN_MISMATCH"),
        ("UNRESOLVED", "BUY", "WAIT", "CONTEXT_DIRECTION_DOMAIN_UNRESOLVED"),
        ("UNRESOLVED", "SELL", "WAIT", "CONTEXT_DIRECTION_DOMAIN_UNRESOLVED"),
        ("EMPTY", "BUY", "WAIT", "CONTEXT_DIRECTION_DOMAIN_UNRESOLVED"),
        ("EMPTY", "SELL", "WAIT", "CONTEXT_DIRECTION_DOMAIN_UNRESOLVED"),
    ),
)
def test_direction_domain_matrix(
    domain: DirectionDomain,
    direction: Direction,
    expected_status: str,
    expected_reason: str | None,
) -> None:
    context = _context(domain)
    result = build_directional_thesis_proofs(context=context, evidence=_evidence(context, direction))

    assert result.status == expected_status
    assert result.reason_code == expected_reason


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
def test_both_conditional_requires_matching_typed_route(direction: Direction) -> None:
    context = _context("BOTH_CONDITIONAL")
    missing = build_directional_thesis_proofs(context=context, evidence=_evidence(context, direction))
    mismatched = _route(context, "SELL" if direction == "BUY" else "BUY")
    wrong = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, direction, route=mismatched),
    )
    valid = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, direction, route=_route(context, direction)),
    )

    assert (missing.status, missing.reason_code) == ("REJECTED", "TYPED_ROUTE_AUTHORITY_REQUIRED")
    assert (wrong.status, wrong.reason_code) == ("REJECTED", "TYPED_ROUTE_AUTHORITY_MISMATCH")
    assert valid.status == "READY"


def test_pressure_authority_matrix_fails_closed() -> None:
    context = _context("BUY_ONLY")
    radar_opposite = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", pressure=_pressure(raw_direction="SELL")),
    )
    radar_opposite_missing_proof = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", pressure=_pressure(raw_direction="SELL"), h1=()),
    )
    locked_buy = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(
            context,
            "BUY",
            pressure=_pressure(
                mode="CONSOLIDATED_DIRECTION_CONTRACT",
                raw_direction="BUY",
                contract_direction="BUY",
            ),
        ),
    )
    locked_sell = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(
            context,
            "BUY",
            pressure=_pressure(
                mode="CONSOLIDATED_DIRECTION_CONTRACT",
                raw_direction="SELL",
                contract_direction="SELL",
            ),
        ),
    )
    unlocked = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(
            context,
            "BUY",
            pressure=_pressure(
                mode="CONSOLIDATED_DIRECTION_CONTRACT",
                status="UNRESOLVED",
                raw_direction="BUY",
            ),
        ),
    )

    assert radar_opposite.status == "READY"
    assert radar_opposite.artifact is not None
    assert radar_opposite.artifact.counter_pressure_proof_hash is not None
    assert (radar_opposite_missing_proof.status, radar_opposite_missing_proof.reason_code) == (
        "WAIT",
        "H1_CLOSED_STRUCTURE_PROOF_MISSING",
    )
    assert locked_buy.status == "READY"
    assert (locked_sell.status, locked_sell.reason_code) == ("REJECTED", "LOCKED_PRESSURE_DIRECTION_MISMATCH")
    assert (unlocked.status, unlocked.reason_code) == ("WAIT", "PRESSURE_DIRECTION_CONTRACT_NOT_LOCKED")


def test_lifecycle_direction_alone_cannot_fabricate_locked_authority() -> None:
    payload = {
        "mode": "CONSOLIDATED_DIRECTION_CONTRACT",
        "contract_status": "LOCKED",
        "raw_pressure_direction": "BUY",
        "contract_direction": "BUY",
        "source_event_ids": ("lifecycle:direction-state",),
        "formal_transition_event_id": None,
        "authority_hash": _tag({"source": "lifecycle-direction-only"}),
        "rule_version": "5scr.pressure-direction-authority.v1",
        "observed_at_utc": START,
    }

    with pytest.raises(ValidationError, match="formal transition"):
        PressureDirectionAuthorityV1.model_validate(payload)


def test_pressure_and_route_material_hashes_reject_caller_tampering() -> None:
    context = _context("BOTH_CONDITIONAL")
    pressure = _pressure(raw_direction="BUY")
    route = _route(context, "BUY")

    with pytest.raises(ValidationError, match="authority_hash"):
        PressureDirectionAuthorityV1.model_validate(
            {**pressure.model_dump(), "authority_hash": _tag({"tampered": "pressure"})}
        )
    with pytest.raises(ValidationError, match="authorization_hash"):
        RouteDirectionAuthorizationV1.model_validate(
            {**route.model_dump(), "authorization_hash": _tag({"tampered": "route"})}
        )

    pressure_refresh = PressureDirectionAuthorityV1.model_validate(
        {
            **pressure.model_dump(exclude={"authority_hash"}),
            "source_event_ids": ("pressure:authority-refresh",),
            "observed_at_utc": pressure.observed_at_utc + timedelta(seconds=30),
        }
    )
    route_refresh = RouteDirectionAuthorizationV1.model_validate(
        {
            **route.model_dump(exclude={"authorization_hash"}),
            "source_event_ids": ("route:refresh",),
        }
    )
    assert pressure_refresh.authority_hash == pressure.authority_hash
    assert route_refresh.authorization_hash == route.authorization_hash

    locked = _pressure(
        mode="CONSOLIDATED_DIRECTION_CONTRACT",
        contract_direction="BUY",
        raw_direction="BUY",
    )
    locked_raw_refresh = PressureDirectionAuthorityV1.model_validate(
        {
            **locked.model_dump(exclude={"authority_hash"}),
            "raw_pressure_direction": "SELL",
            "source_event_ids": ("pressure:authority-refresh", "pressure:formal-transition"),
            "observed_at_utc": locked.observed_at_utc + timedelta(seconds=30),
        }
    )
    assert locked_raw_refresh.authority_hash == locked.authority_hash
    assert (
        _artifact(context, "BUY", pressure=locked, route=route).semantic_identity_hash
        == _artifact(
            context,
            "BUY",
            pressure=locked_raw_refresh,
            route=route,
        ).semantic_identity_hash
    )

    pressure_copy_tamper = pressure.model_copy(update={"raw_pressure_direction": "SELL"})
    route_copy_tamper = route.model_copy(update={"strategy_direction": "SELL"})
    valid_evidence = _evidence(context, "BUY", pressure=pressure, route=route)
    pressure_result = build_directional_thesis_proofs(
        context=context,
        evidence=valid_evidence.model_copy(update={"pressure_authority": pressure_copy_tamper}),
    )
    route_result = build_directional_thesis_proofs(
        context=context,
        evidence=valid_evidence.model_copy(update={"route_authorization": route_copy_tamper}),
    )
    assert (pressure_result.status, pressure_result.reason_code) == (
        "QUARANTINED",
        "PRESSURE_AUTHORITY_HASH_MISMATCH",
    )
    assert (route_result.status, route_result.reason_code) == (
        "QUARANTINED",
        "ROUTE_AUTHORIZATION_HASH_MISMATCH",
    )


def test_future_and_expired_pressure_authority_fail_closed() -> None:
    context = _context()
    future = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", pressure=_pressure(observed_at=DECISION + timedelta(seconds=1))),
    )
    expired = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(
            context,
            "BUY",
            pressure=_pressure(valid_until=DECISION - timedelta(seconds=1)),
        ),
    )

    assert (future.status, future.reason_code) == ("QUARANTINED", "FUTURE_PRESSURE_AUTHORITY")
    assert (expired.status, expired.reason_code) == ("REJECTED", "PRESSURE_AUTHORITY_EXPIRED")


def test_candle_adapter_and_builder_share_exact_hash_contract() -> None:
    candle = _candle(
        row_id=51,
        timeframe="H1",
        open_time=START,
        open_price=1.1000,
        high=1.1010,
        low=1.0990,
        close=1.1005,
    )

    assert candle.material_candle_hash == candle_material_hash(candle)
    assert candle.candle_evidence_id == candle_evidence_hash(candle)


def test_missing_forming_future_and_inactive_context_never_form_thesis() -> None:
    context = _context()
    missing_h1 = build_directional_thesis_proofs(context=context, evidence=_evidence(context, "BUY", h1=()))
    missing_m15 = build_directional_thesis_proofs(context=context, evidence=_evidence(context, "BUY", m15=()))
    inactive_context = _context(state="SUPERSEDED")
    inactive = build_directional_thesis_proofs(
        context=inactive_context,
        evidence=_evidence(inactive_context, "BUY"),
    )

    assert (missing_h1.status, missing_h1.reason_code) == ("WAIT", "H1_CLOSED_STRUCTURE_PROOF_MISSING")
    assert (missing_m15.status, missing_m15.reason_code) == ("WAIT", "M15_ORDERED_BREAK_COMPLETION_MISSING")
    assert (inactive.status, inactive.reason_code) == ("REJECTED", "CONTEXT_EPOCH_NOT_ACTIVE")

    candle_payload = _candles("BUY")[0][0].model_dump(mode="python")
    candle_payload["is_closed"] = False
    with pytest.raises(ValidationError):
        ClosedCandleAuthorityRefV1.model_validate(candle_payload)
    candle_payload["is_closed"] = True
    candle_payload["structural_authority"] = False
    with pytest.raises(ValidationError):
        ClosedCandleAuthorityRefV1.model_validate(candle_payload)

    h1, m15 = _candles("BUY")
    future_payload = m15[-1].model_dump(mode="python")
    future_payload["open_time_utc"] = DECISION
    future_payload["close_time_utc"] = DECISION + timedelta(minutes=15)
    future_payload["material_candle_hash"] = _tag({"future": "material"})
    future_payload["candle_evidence_id"] = _tag({"future": "evidence"})
    future = ClosedCandleAuthorityRefV1.model_validate(future_payload)
    with pytest.raises(ValidationError, match="future candle leakage"):
        _evidence(context, "BUY", h1=h1, m15=(*m15[:-1], future))


def test_h1_and_m15_ordering_are_recomputed_not_trusted() -> None:
    context = _context()
    buy_h1, buy_m15 = _candles("BUY")

    no_h1_break_payload = buy_h1[-1].model_dump(mode="python")
    no_h1_break_payload.update(close=1.1005, high=1.1010)
    no_h1_break = _rehash_candle(no_h1_break_payload)
    h1_result = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", h1=(buy_h1[0], no_h1_break)),
    )

    pre_h1_m15 = tuple(
        candle_authority_from_row(
            _row(
                row_id=100 + index,
                timeframe="M15",
                open_time=START + timedelta(minutes=15 * index),
                open_price=(1.1000, 1.1005, 1.1015)[index],
                high=(1.1010, 1.1020, 1.1022)[index],
                low=(1.0995, 1.1000, 1.1008)[index],
                close=(1.1005, 1.1015, 1.1016)[index],
            )
        )
        for index in range(3)
    )
    order_result = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", h1=buy_h1, m15=pre_h1_m15),
    )
    completion_result = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", m15=buy_m15[:2]),
    )

    assert (h1_result.status, h1_result.reason_code) == ("WAIT", "H1_CLOSED_STRUCTURE_PROOF_MISSING")
    assert (order_result.status, order_result.reason_code) == ("WAIT", "M15_ORDERED_BREAK_COMPLETION_MISSING")
    assert (completion_result.status, completion_result.reason_code) == (
        "WAIT",
        "M15_ORDERED_BREAK_COMPLETION_MISSING",
    )


def test_gapped_h1_or_m15_coverage_cannot_claim_complete_authority() -> None:
    context = _context()
    h1, m15 = _candles("BUY")
    h1_payload = h1[1].model_dump(mode="python")
    h1_payload.update(
        open_time_utc=h1[1].open_time_utc + timedelta(hours=1),
        close_time_utc=h1[1].close_time_utc + timedelta(hours=1),
    )
    gapped_h1 = (h1[0], _rehash_candle(h1_payload))
    m15_payload = m15[1].model_dump(mode="python")
    m15_payload.update(
        open_time_utc=m15[1].open_time_utc + timedelta(minutes=15),
        close_time_utc=m15[1].close_time_utc + timedelta(minutes=15),
    )
    gapped_m15 = (m15[0], _rehash_candle(m15_payload), m15[2])

    h1_result = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", h1=gapped_h1, m15=m15),
    )
    m15_result = build_directional_thesis_proofs(
        context=context,
        evidence=_evidence(context, "BUY", h1=h1, m15=gapped_m15),
    )

    assert (h1_result.status, h1_result.reason_code) == (
        "WAIT",
        "H1_CLOSED_STRUCTURE_PROOF_MISSING",
    )
    assert (m15_result.status, m15_result.reason_code) == (
        "WAIT",
        "M15_ORDERED_BREAK_COMPLETION_MISSING",
    )


def test_proof_coverage_starts_at_selected_pair_not_earlier_scanner_history() -> None:
    context = _context()
    h1, m15 = _candles("BUY")
    earlier_h1 = _candle(
        row_id=200,
        timeframe="H1",
        open_time=START - timedelta(hours=1),
        open_price=1.1500,
        high=1.1600,
        low=1.0900,
        close=1.1500,
    )
    earlier_m15 = _candle(
        row_id=201,
        timeframe="M15",
        open_time=START + timedelta(hours=1, minutes=30),
        open_price=1.1500,
        high=1.1600,
        low=1.0900,
        close=1.1500,
    )

    artifact = _artifact(context, "BUY", h1=(earlier_h1, *h1), m15=(earlier_m15, *m15))

    assert artifact.h1_proof.anchor_candle == h1[0]
    assert artifact.h1_proof.coverage_start_at_utc == h1[0].open_time_utc
    assert artifact.m15_proof.reference_candle == m15[0]
    assert artifact.m15_proof.coverage_start_at_utc == m15[0].open_time_utc


def test_m15_failed_reclaim_is_derived_from_closed_ordered_candles() -> None:
    context = _context()
    h1, m15 = _candles("BUY")
    completion_payload = m15[-1].model_dump(mode="python")
    completion_payload.update(open=1.1008, high=1.1022, low=1.1005, close=1.1016)
    failed_reclaim = _artifact(
        context,
        "BUY",
        h1=h1,
        m15=(*m15[:-1], _rehash_candle(completion_payload)),
    )

    assert failed_reclaim.m15_proof.completion_kind == "FAILED_RECLAIM"


def test_nonmaterial_lineage_and_irrelevant_route_churn_keep_identity_stable() -> None:
    context = _context("BUY_ONLY")
    first = _artifact(context, "BUY", route=_route(context, "BUY", variant="a"), request_id="request-a")
    h1, m15 = _candles("BUY")

    def churn(candle: ClosedCandleAuthorityRefV1, suffix: str) -> ClosedCandleAuthorityRefV1:
        payload = candle.model_dump(mode="python")
        payload.update(
            canonical_row_id=(candle.canonical_row_id or 0) + 10_000,
            selected_raw_candle_id=(candle.selected_raw_candle_id or 0) + 10_000,
            provider="XM_DEMO_REVISION",
            feed=f"replica-{suffix}",
            source_content_hash=_tag({"source": suffix}),
            volume=candle.volume + 500,
            tick_count=candle.tick_count + 50,
        )
        return _rehash_candle(payload)

    churned_h1 = tuple(churn(item, f"h1-{index}") for index, item in enumerate(h1))
    churned_m15 = tuple(churn(item, f"m15-{index}") for index, item in enumerate(m15))
    second = _artifact(
        context,
        "BUY",
        route=_route(context, "BUY", variant="b"),
        request_id="request-b",
        h1=churned_h1,
        m15=churned_m15,
    )

    assert first.h1_proof.material_proof_hash == second.h1_proof.material_proof_hash
    assert first.m15_proof.material_proof_hash == second.m15_proof.material_proof_hash
    assert first.h1_proof.evidence_hash != second.h1_proof.evidence_hash
    assert first.m15_proof.evidence_hash != second.m15_proof.evidence_hash
    assert first.semantic_identity_hash == second.semantic_identity_hash


def test_material_candle_or_context_epoch_change_changes_semantic_identity() -> None:
    context = _context()
    first = _artifact(context, "BUY")
    h1, m15 = _candles("BUY")
    completion_payload = m15[-1].model_dump(mode="python")
    completion_payload.update(close=1.1019, high=1.1024)
    changed_completion = _rehash_candle(completion_payload)
    changed_candle = _artifact(context, "BUY", h1=h1, m15=(*m15[:-1], changed_completion))

    next_context = _context(context_id="5scr-context:33333333333333333333333333333333")
    changed_context = _artifact(next_context, "BUY")

    assert first.semantic_identity_hash != changed_candle.semantic_identity_hash
    assert first.semantic_identity_hash != changed_context.semantic_identity_hash


def test_closure_preserves_direction_and_later_opposite_uses_new_identity() -> None:
    context = _context("BOTH_CONDITIONAL")
    buy_pressure = _pressure(raw_direction="BUY")
    buy_route = _route(context, "BUY")
    buy_artifact = _artifact(context, "BUY", pressure=buy_pressure, route=buy_route)
    buy = _thesis(context, "BUY", buy_artifact, pressure=buy_pressure, route=buy_route)

    closed = close_directional_thesis(
        buy,
        state="INVALIDATED",
        closed_at_utc=DECISION + timedelta(minutes=1),
        reason="STRUCTURAL_INVALIDATION",
    )
    closed_again = close_directional_thesis(
        closed,
        state="TERMINAL",
        closed_at_utc=DECISION + timedelta(minutes=2),
        reason="LIFECYCLE_TERMINAL",
    )

    sell_pressure = _pressure(raw_direction="SELL")
    sell_route = _route(context, "SELL")
    sell_artifact = _artifact(context, "SELL", pressure=sell_pressure, route=sell_route)
    sell = _thesis(
        context,
        "SELL",
        sell_artifact,
        pressure=sell_pressure,
        route=sell_route,
        sequence=2,
    )

    assert closed.state == "INVALIDATED"
    assert closed.strategy_direction == buy.strategy_direction == "BUY"
    assert closed.h1_proof_id == buy.h1_proof_id
    assert closed.m15_proof_id == buy.m15_proof_id
    assert closed.semantic_identity_hash == buy.semantic_identity_hash
    assert closed_again == closed
    assert sell.strategy_direction == "SELL"
    assert sell.strategy_thesis_id != buy.strategy_thesis_id
    assert sell.semantic_identity_hash != buy.semantic_identity_hash
    with pytest.raises(ValidationError):
        buy.strategy_direction = "SELL"
