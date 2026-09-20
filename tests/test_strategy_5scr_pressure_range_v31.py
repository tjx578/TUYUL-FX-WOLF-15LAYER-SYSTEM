"""PressureRangeV31 acceptance against the APPROVED authority only: SSOT v3.1 + A1-09 … A1-12.

A1-01 … A1-08 are PENDING and grant nothing here. Every assertion traces to a clause that is actually approved.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid5

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_pressure_range_v31 import (
    materialize_pressure_range_v31,
    observe_pressure_range_v31,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31, identity_uuid_v31
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31
from contracts.strategy_5scr_pressure_range_v31 import (
    PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION,
    V31_PRESSURE_RANGE_NAMESPACE,
    CanonicalPeriodPriceEvidenceV31,
    PressureRangePolicyV31,
    PressureRangeV31,
    classify_pressure_range_change_v31,
    downstream_reevaluation_v31,
    pressure_range_id_v31,
)
from tests.test_strategy_5scr_context_epoch_v31 import _relifecycle
from tests.test_strategy_5scr_pressure_hypothesis_v31 import START, _canonical_s1b

POLICY = PressureRangePolicyV31(
    policy_version="test-pressure-range.v1",
    timeframe="M1",
    calendar_policy_version="test-calendar.v1",
    outlier_policy_version="test-outlier.v1",
    policy_hash=canonical_sha256_v31(
        {
            "policy_version": "test-pressure-range.v1",
            "timeframe": "M1",
            "calendar_policy_version": "test-calendar.v1",
            "outlier_policy_version": "test-outlier.v1",
        }
    ),
)
WINDOW_START = START
OBSERVED_THROUGH = START + timedelta(minutes=10)


def _lifecycle() -> Any:
    s1b = _canonical_s1b()
    assert s1b is not None
    return s1b.lifecycle


def _periods(count: int = 3, *, first: int = 0) -> tuple[datetime, ...]:
    return tuple(WINDOW_START + timedelta(minutes=first + n) for n in range(count))


def _evidence(
    minute: int,
    *,
    low: float,
    high: float,
    quality: str = "AUTHORITATIVE",
    symbol: str = "EURUSD",
    tag: str = "",
    is_closed: bool = True,
) -> CanonicalPeriodPriceEvidenceV31:
    open_utc = WINDOW_START + timedelta(minutes=minute)
    digest = "sha256:" + hashlib.sha256(f"{symbol}|{minute}|{low}|{high}|{tag}".encode()).hexdigest()
    material = "sha256:" + hashlib.sha256(f"material|{symbol}|{minute}|{low}|{high}|{tag}".encode()).hexdigest()
    return CanonicalPeriodPriceEvidenceV31(
        canonical_symbol=symbol,
        period_open_utc=open_utc,
        period_close_utc=open_utc + timedelta(minutes=1),
        low=low,
        high=high,
        quality=quality,  # type: ignore[arg-type]
        is_closed=is_closed,
        evidence_id=digest,
        material_evidence_hash=material,
        raw_tick_provenance=(f"tick:{minute}:a", f"tick:{minute}:b"),
    )


def _materialize(
    *,
    lifecycle: Any = None,
    evidence: tuple[CanonicalPeriodPriceEvidenceV31, ...] = (),
    expected: tuple[datetime, ...] | None = None,
    closed_at: datetime | None = None,
    anchor: Any = "RAW_BLOCK_START",
    policy: Any = POLICY,
    observed_through: datetime = OBSERVED_THROUGH,
) -> Any:
    return materialize_pressure_range_v31(
        lifecycle=_lifecycle() if lifecycle is None else lifecycle,
        coverage_anchor_rule=anchor,
        started_at=WINDOW_START,
        market_episode_closed_at=closed_at,
        expected_periods=_periods() if expected is None else expected,
        evidence=evidence,
        policy=policy,
        observed_through_utc=observed_through,
    )


def _complete() -> Any:
    evidence = (
        _evidence(0, low=1.1000, high=1.1010),
        _evidence(1, low=1.0990, high=1.1005),
        _evidence(2, low=1.1002, high=1.1030),
    )
    decision = _materialize(evidence=evidence)
    assert decision.range is not None, decision.reason_code
    return decision.range


# --- 1..3 geometry and cardinality --------------------------------------------------------------------------


def test_1_an_empty_qualified_set_gives_missing_coverage_and_null_bounds():
    """A1-10: never 0, never a fabricated point range."""

    decision = _materialize(evidence=())
    record = decision.range
    assert record is not None and decision.reason_code == "PRESSURE_RANGE_MATERIALIZED"
    assert (record.low, record.high, record.price_coverage_status) == (None, None, "MISSING")
    assert record.source_price_ids == ()
    assert record.coverage_gaps == _periods()
    assert record.structural_authority is False
    # "never 0" and "MISSING means absent bounds" are two separate rejections; both must hold.
    with pytest.raises(ValidationError, match="PRESSURE_RANGE_BOUNDS_MUST_BE_POSITIVE"):
        PressureRangeV31.model_validate({**record.model_dump(), "low": 0.0, "high": 0.0})
    with pytest.raises(ValidationError, match="MISSING_COVERAGE_REQUIRES_ABSENT_BOUNDS"):
        PressureRangeV31.model_validate({**record.model_dump(), "low": 1.1000, "high": 1.1010})


def test_2_one_canonical_period_gives_its_own_bounds_and_one_source_reference():
    decision = _materialize(evidence=(_evidence(0, low=1.1000, high=1.1010),))
    record = decision.range
    assert record is not None
    assert (record.low, record.high) == (1.1000, 1.1010)
    assert len(record.source_price_ids) == 1
    assert record.price_coverage_status == "PARTIAL"  # two expected periods are still unmatched
    assert record.coverage_gaps == _periods()[1:]


def test_3_multiple_periods_give_min_wick_low_and_max_wick_high():
    record = _complete()
    assert (record.low, record.high) == (1.0990, 1.1030)
    assert record.price_coverage_status == "COMPLETE"
    assert record.coverage_gaps == ()
    assert record.structural_authority is True
    assert len(record.source_price_ids) == 3


# --- 4..7 evidence discipline -------------------------------------------------------------------------------


def test_4_identical_duplicate_evidence_dedupes_deterministically():
    one = _evidence(0, low=1.1000, high=1.1010)
    decision = _materialize(evidence=(one, one, one), expected=_periods(1))
    record = decision.range
    assert record is not None
    assert record.source_price_ids == (one.evidence_id,)
    assert record.price_coverage_status == "COMPLETE"


def test_5_conflicting_duplicate_evidence_can_never_become_complete():
    """A1-10 clause 6: two distinct evidence ids for one period is a gap, never a silent pick."""

    decision = _materialize(
        evidence=(
            _evidence(0, low=1.1000, high=1.1010),
            _evidence(0, low=1.1000, high=1.1010, tag="other-provider"),
        ),
        expected=_periods(1),
    )
    record = decision.range
    assert record is not None
    assert record.price_coverage_status != "COMPLETE"
    assert record.price_coverage_status == "MISSING"  # the only expected period is now a gap
    assert record.coverage_gaps == _periods(1)
    assert record.source_price_ids == ()


def test_6_a_raw_tick_id_can_never_be_a_top_level_source_reference():
    """A1-10 clause 7: ticks are provenance under a period, never a member of source_price_ids."""

    record = _complete()
    assert all(ref.startswith("sha256:") for ref in record.source_price_ids)
    assert not any(ref.startswith("tick:") for ref in record.source_price_ids)
    with pytest.raises(ValidationError):
        PressureRangeV31.model_validate({**record.model_dump(), "source_price_ids": ("tick:0:a",)})
    # Ticks still exist, but only underneath the canonical period evidence.
    assert _evidence(0, low=1.0, high=2.0).raw_tick_provenance == ("tick:0:a", "tick:0:b")


def test_7_evidence_outside_the_expected_period_set_never_enters_the_range():
    """If a reference cannot map to an expected period it contributes nothing, so coverage stays decidable."""

    stray = _evidence(9, low=0.9000, high=2.0000)
    decision = _materialize(evidence=(_evidence(0, low=1.1000, high=1.1010), stray), expected=_periods(1))
    record = decision.range
    assert record is not None
    assert stray.evidence_id not in record.source_price_ids
    assert (record.low, record.high) == (1.1000, 1.1010)  # the stray never widened the bounds
    assert len(record.source_price_ids) == 1 and record.price_coverage_status == "COMPLETE"


# --- 8..10 change classification ------------------------------------------------------------------------------


def test_8_partial_to_complete_with_identical_bounds_is_a_coverage_change():
    """The case a two-class model loses. Bounds identical, coverage moved."""

    bounds = (_evidence(0, low=1.0990, high=1.1030),)
    partial = _materialize(evidence=bounds, expected=_periods(2)).range
    complete = _materialize(evidence=(*bounds, _evidence(1, low=1.1000, high=1.1010)), expected=_periods(2)).range
    assert partial is not None and complete is not None
    assert (partial.low, partial.high) == (complete.low, complete.high)
    assert (partial.price_coverage_status, complete.price_coverage_status) == ("PARTIAL", "COMPLETE")
    assert classify_pressure_range_change_v31(partial, complete) == "COVERAGE_CHANGE"
    assert downstream_reevaluation_v31("COVERAGE_CHANGE") == ("LIFECYCLE",)
    assert "EXECUTION_BOX" not in downstream_reevaluation_v31("COVERAGE_CHANGE")


def test_9_more_evidence_with_the_same_bounds_and_coverage_is_only_a_refresh():
    first = _materialize(evidence=(_evidence(0, low=1.0990, high=1.1030),), expected=_periods(3)).range
    second = _materialize(
        evidence=(_evidence(0, low=1.0990, high=1.1030), _evidence(1, low=1.1000, high=1.1010)),
        expected=_periods(3),
    ).range
    assert first is not None and second is not None
    assert (first.low, first.high) == (second.low, second.high)
    assert first.price_coverage_status == second.price_coverage_status == "PARTIAL"
    assert first.coverage_gaps != second.coverage_gaps  # a gap closed, so coverage material moved
    assert classify_pressure_range_change_v31(first, second) == "COVERAGE_CHANGE"
    # A genuine refresh: nothing in the geometry or coverage sets differs, only the as-of bound.
    later = _materialize(
        evidence=(_evidence(0, low=1.0990, high=1.1030),),
        expected=_periods(3),
        observed_through=OBSERVED_THROUGH + timedelta(minutes=5),
    ).range
    assert later is not None
    assert classify_pressure_range_change_v31(first, later) == "EVIDENCE_REFRESH"
    assert downstream_reevaluation_v31("EVIDENCE_REFRESH") == ()


def test_10_a_bound_change_is_a_material_range_change():
    first = _materialize(evidence=(_evidence(0, low=1.1000, high=1.1010),), expected=_periods(1)).range
    wider = _materialize(evidence=(_evidence(0, low=1.0900, high=1.1010),), expected=_periods(1)).range
    assert first is not None and wider is not None
    assert classify_pressure_range_change_v31(first, wider) == "MATERIAL_RANGE_CHANGE"
    assert downstream_reevaluation_v31("MATERIAL_RANGE_CHANGE") == ("LIFECYCLE", "STRUCTURAL_TARGET")
    assert classify_pressure_range_change_v31(first, first) == "NO_MATERIAL_CHANGE"
    assert classify_pressure_range_change_v31(None, first) == "MATERIAL_RANGE_CHANGE"


# --- 11..15 window closure ------------------------------------------------------------------------------------


def test_11_lifecycle_supersession_leaves_the_window_open():
    """A1-09: a superseded lifecycle stops progressing; its episode's price evidence keeps its own window."""

    superseded = _relifecycle(_lifecycle(), state="SUPERSEDED")
    assert _materialize(lifecycle=superseded).reason_code == "LIFECYCLE_TERMINAL"
    # The window itself is untouched: re-observing the open range with a live lifecycle still leaves ended_at None.
    record = _complete()
    again = observe_pressure_range_v31(
        record,
        lifecycle=_lifecycle(),
        expected_periods=_periods(),
        evidence=(
            _evidence(0, low=1.1000, high=1.1010),
            _evidence(1, low=1.0990, high=1.1005),
            _evidence(2, low=1.1002, high=1.1030),
        ),
        policy=POLICY,
        observed_through_utc=OBSERVED_THROUGH,
    )
    assert again.range is not None and again.range.ended_at is None


def test_12_raw_block_termination_alone_leaves_the_window_open():
    """The producer has no block-termination input at all. The absence IS the guarantee (A1-09)."""

    import inspect

    names = set(inspect.signature(materialize_pressure_range_v31).parameters)
    assert "market_episode_closed_at" in names
    assert not names & {"block_terminated_at", "raw_block_closed_at", "lifecycle_superseded_at"}
    assert _materialize(evidence=(_evidence(0, low=1.1, high=1.2),)).range.ended_at is None


def test_13_the_market_episode_close_is_the_sole_closure_authority():
    closed_at = WINDOW_START + timedelta(minutes=20)
    decision = _materialize(
        evidence=(
            _evidence(0, low=1.1000, high=1.1010),
            _evidence(1, low=1.0990, high=1.1005),
            _evidence(2, low=1.1002, high=1.1030),
        ),
        closed_at=closed_at,
    )
    record = decision.range
    assert record is not None and record.ended_at == closed_at
    assert record.price_coverage_status == "COMPLETE"


def test_14_evidence_arriving_after_closure_never_mutates_the_canonical_object():
    closed = _materialize(
        evidence=(_evidence(0, low=1.1000, high=1.1010),),
        expected=_periods(1),
        closed_at=WINDOW_START + timedelta(minutes=5),
    ).range
    assert closed is not None
    late = observe_pressure_range_v31(
        closed,
        lifecycle=_lifecycle(),
        expected_periods=_periods(1),
        evidence=(_evidence(0, low=1.1000, high=1.1010), _evidence(0, low=0.5000, high=9.0000, tag="late")),
        policy=POLICY,
        observed_through_utc=OBSERVED_THROUGH + timedelta(hours=1),
    )
    assert late.reason_code == "PRESSURE_RANGE_CLOSED_NO_MUTATION"
    assert late.range is not None and late.range == closed
    assert classify_pressure_range_change_v31(closed, late.range) == "NO_MATERIAL_CHANGE"


def test_15_a_closed_range_is_never_reopened():
    closed_at = WINDOW_START + timedelta(minutes=5)
    closed = _materialize(evidence=(_evidence(0, low=1.1, high=1.2),), expected=_periods(1), closed_at=closed_at).range
    assert closed is not None
    reopened = observe_pressure_range_v31(
        closed,
        lifecycle=_lifecycle(),
        expected_periods=_periods(1),
        evidence=(_evidence(0, low=1.1, high=1.2),),
        policy=POLICY,
        observed_through_utc=OBSERVED_THROUGH,
    )
    assert reopened.range is not None and reopened.range.ended_at == closed_at


# --- 16 non-material -------------------------------------------------------------------------------------------


def test_16_the_record_carries_nothing_that_telemetry_or_deployment_could_move():
    record = _complete()
    forbidden = {
        "deployment_id",
        "replica_id",
        "cluster_id",
        "request_id",
        "worker_id",
        "publisher_timestamp",
        "telemetry_count",
        "reference_price",
        "analysis_admission_class",
        "promotion_eligibility",
        "risk_handoff_allowed",
        "direction",
        "selected_route",
        "entry",
        "stop_loss",
        "take_profit",
        "volume",
        "spread",
        "margin",
    }
    assert not forbidden & set(PressureRangeV31.model_fields)
    assert record.authority == "MATERIAL_PRICE_EVIDENCE_ONLY"
    assert (record.direction_authority, record.execution_authority) == (False, False)
    blob = str(record.model_dump(mode="json"))
    assert "CANONICAL_RAW" not in blob and "MATURE_ADVISORY" not in blob


# --- authority-level invariants --------------------------------------------------------------------------------


def test_coverage_vocabulary_is_closed_and_never_defaults():
    from typing import get_args

    from contracts.strategy_5scr_pressure_range_v31 import PriceCoverageStatus as Status

    assert set(get_args(Status)) == {"COMPLETE", "PARTIAL", "MISSING", "QUARANTINED"}
    quarantined = _materialize(
        evidence=(
            _evidence(0, low=1.1000, high=1.1010),
            _evidence(1, low=1.0990, high=1.1005),
            _evidence(2, low=1.1002, high=1.1030, quality="QUARANTINED"),
        )
    ).range
    assert quarantined is not None and quarantined.price_coverage_status == "QUARANTINED"
    assert quarantined.structural_authority is False
    with pytest.raises(ValidationError, match="STRUCTURAL_AUTHORITY_NOT_DERIVED_FROM_COVERAGE"):
        PressureRangeV31.model_validate({**quarantined.model_dump(), "structural_authority": True})


def test_only_closed_authoritative_in_window_evidence_qualifies():
    base = _evidence(0, low=1.1000, high=1.1010)
    for bad in (
        _evidence(0, low=0.5, high=9.0, quality="FORMING", tag="forming"),
        _evidence(0, low=0.5, high=9.0, quality="INCOMPLETE", tag="incomplete"),
        _evidence(0, low=0.5, high=9.0, quality="UNKNOWN", tag="unknown"),
        _evidence(0, low=0.5, high=9.0, symbol="GBPUSD", tag="other-symbol"),
        _evidence(0, low=0.5, high=9.0, is_closed=False, tag="open"),
    ):
        record = _materialize(evidence=(base, bad), expected=_periods(1)).range
        assert record is not None
        assert (record.low, record.high) == (1.1000, 1.1010), bad.evidence_id
    # Future price: a period closing after the as-of bound never contributes.
    future = _materialize(
        evidence=(base, _evidence(5, low=0.5, high=9.0)),
        expected=_periods(6),
        observed_through=WINDOW_START + timedelta(minutes=3),
    ).range
    assert future is not None and (future.low, future.high) == (1.1000, 1.1010)


def test_identity_is_pinned_anchored_at_the_window_start_and_free_of_volatile_inputs():
    """G1 GAP_FILL: the tuple is spelled out, because a silently widened identity shifts every id uniformly."""

    lifecycle = _lifecycle()
    record = _complete()
    assert record.pressure_range_id == identity_uuid_v31(
        V31_PRESSURE_RANGE_NAMESPACE,
        [
            PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION,
            str(lifecycle.strategy_lifecycle_id),
            "RAW_BLOCK_START",
            WINDOW_START.isoformat(),
            POLICY.policy_hash,
        ],
    )
    # The id survives a growing window: more evidence, wider bounds, same id.
    wider = _materialize(evidence=(_evidence(0, low=0.9000, high=1.9000),), expected=_periods(1)).range
    assert wider is not None and wider.pressure_range_id == record.pressure_range_id
    # A different anchor rule is a different object (section 8.5 gives the classes different windows).
    advisory = _materialize(anchor="FIRST_RETAINED_ADVISORY_EVENT", evidence=()).range
    assert advisory is not None and advisory.pressure_range_id != record.pressure_range_id
    # Episode-rooted, and the episode binding is auditable but outside the identity.
    assert record.strategy_lifecycle_id == strategy_lifecycle_id_from_episode_v31(record.market_episode_id)
    stranger = uuid5(record.market_episode_id, "elsewhere")
    with pytest.raises(ValidationError, match="PRESSURE_RANGE_LIFECYCLE_NOT_EPISODE_ROOTED"):
        PressureRangeV31.model_validate({**record.model_dump(), "market_episode_id": stranger})
    with pytest.raises(ValidationError, match="PRESSURE_RANGE_ID_NOT_DERIVED"):
        PressureRangeV31.model_validate({**record.model_dump(), "pressure_range_id": stranger})


def test_policy_is_mandatory_hashed_and_carries_no_default():
    assert _materialize(policy=None).reason_code == "PRESSURE_RANGE_POLICY_MISSING"
    with pytest.raises(ValidationError, match="PRESSURE_RANGE_POLICY_HASH_MISMATCH"):
        PressureRangePolicyV31.model_validate({**POLICY.model_dump(), "policy_version": "tampered.v1"})
    record = _complete()
    assert (record.range_policy_version, record.range_policy_hash) == (
        POLICY.policy_version,
        POLICY.policy_hash,
    )


def test_the_evidence_hash_is_the_only_hash_and_no_material_hash_exists():
    """G8: material change is detected by explicit field comparison, never by a canonical material hash."""

    record = _complete()
    assert "material_pressure_range_hash" not in PressureRangeV31.model_fields
    # Only the pinned SSOT hash, the policy hash and the single §16.2 evidence hash exist.
    assert [f for f in PressureRangeV31.model_fields if f.endswith("_hash")] == [
        "selected_ssot_hash",
        "range_policy_hash",
        "evidence_hash",
    ]
    with pytest.raises(ValidationError, match="PRESSURE_RANGE_EVIDENCE_HASH_MISMATCH"):
        PressureRangeV31.model_validate({**record.model_dump(), "evidence_hash": "sha256:" + "1" * 64})


def test_the_producer_never_reaches_a_target_a_box_or_a_broker():
    import ast
    from pathlib import Path

    forbidden = ("execution_box", "structural_target", "tradeplan", "broker", "risk_", "ordered_proof")
    for path in (
        "contracts/strategy_5scr_pressure_range_v31.py",
        "analysis/strategy_5scr_pressure_range_v31.py",
    ):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not any(token in module for token in forbidden), f"{path} imports {module}"
    assert "EXECUTION_BOX" not in str(downstream_reevaluation_v31("MATERIAL_RANGE_CHANGE"))


def test_a_range_cannot_be_compared_across_two_different_ranges():
    canonical = _complete()
    advisory = _materialize(anchor="FIRST_RETAINED_ADVISORY_EVENT", evidence=()).range
    assert advisory is not None
    with pytest.raises(ValueError, match="PRESSURE_RANGE_CHANGE_ACROSS_DIFFERENT_RANGES"):
        classify_pressure_range_change_v31(canonical, advisory)


def test_pressure_range_id_derivation_is_versioned_and_deterministic():
    lifecycle = _lifecycle()
    first = pressure_range_id_v31(
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        coverage_anchor_rule="RAW_BLOCK_START",
        started_at=WINDOW_START,
        range_policy_hash=POLICY.policy_hash,
    )
    assert first == pressure_range_id_v31(
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        coverage_anchor_rule="RAW_BLOCK_START",
        started_at=WINDOW_START,
        range_policy_hash=POLICY.policy_hash,
    )
    moved = pressure_range_id_v31(
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        coverage_anchor_rule="RAW_BLOCK_START",
        started_at=WINDOW_START + timedelta(minutes=1),
        range_policy_hash=POLICY.policy_hash,
    )
    assert moved != first
    assert PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION == "v31.pressure-range-identity.v1"


def test_coverage_is_set_completeness_not_a_ratio():
    """Five expected periods, four qualified. Set completeness says PARTIAL. An 80% ratio would say COMPLETE —
    which is exactly the magic threshold A1-11 forbids."""

    expected = _periods(5)
    evidence = tuple(_evidence(n, low=1.1000 + n / 10000, high=1.1010 + n / 10000) for n in range(4))
    record = _materialize(evidence=evidence, expected=expected).range
    assert record is not None
    assert len(record.source_price_ids) == 4 and len(expected) == 5
    assert record.price_coverage_status == "PARTIAL"
    assert record.structural_authority is False
    assert record.coverage_gaps == (expected[4],)
    # And the boundary case a ratio would also get wrong in the other direction.
    nine_of_ten = _materialize(
        evidence=tuple(_evidence(n, low=1.1, high=1.2) for n in range(9)), expected=_periods(10)
    ).range
    assert nine_of_ten is not None and nine_of_ten.price_coverage_status == "PARTIAL"


def test_a_raw_tick_id_is_rejected_as_such_not_merely_as_a_hash_mismatch():
    """A1-10 clause 7 at contract level: the element pattern refuses `tick:<id>` before any hash is consulted."""

    record = _complete()
    with pytest.raises(ValidationError, match="String should match pattern"):
        PressureRangeV31.model_validate({**record.model_dump(), "source_price_ids": ("tick:0:a",)})
    body = {k: v for k, v in record.model_dump().items() if k != "evidence_hash"}
    with pytest.raises(ValidationError, match="String should match pattern"):
        PressureRangeV31.model_construct(**body).__class__.model_validate(
            {**record.model_dump(), "source_price_ids": ("tick:0:a", *record.source_price_ids)}
        )
