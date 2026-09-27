"""Pure producer for PressureRangeV31 (SSOT §16.2 + approved amendment entries A1-09 … A1-12).

Inputs are the S1B ``AnalysisLifecycleV31``, the window anchor, the expected canonical-period set produced by a
versioned calendar policy, and the canonical-period price evidence observed so far. No wall clock, no broker, no
thesis, no route, no target. Fail closed everywhere.

The qualifying universe is decided FIRST (A1-10), then the bounds. Coverage is set completeness against the
expected periods (A1-11) — there is no ratio and no threshold anywhere in this module.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from analysis.strategy_5scr_pressure_hypothesis_v31 import TERMINAL_LIFECYCLE_STATES_V31
from contracts.strategy_5scr_analysis_lifecycle_v31 import AnalysisLifecycleV31
from contracts.strategy_5scr_pressure_range_v31 import (
    CanonicalPeriodPriceEvidenceV31,
    CoverageAnchorRule,
    PressureRangePolicyV31,
    PressureRangeV31,
    PriceCoverageStatus,
    pressure_range_evidence_hash_v31,
    pressure_range_id_v31,
)

Outcome = Literal["MATERIALIZED", "NOT_MATERIALIZED"]


@dataclass(frozen=True)
class PressureRangeDecisionV31:
    outcome: Outcome
    reason_code: str
    range: PressureRangeV31 | None = None


def _no(reason: str) -> PressureRangeDecisionV31:
    return PressureRangeDecisionV31("NOT_MATERIALIZED", reason)


def _aware(name: str, moment: datetime | None) -> None:
    if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


def qualifying_period_evidence_v31(
    evidence: tuple[CanonicalPeriodPriceEvidenceV31, ...],
    *,
    canonical_symbol: str,
    expected_periods: frozenset[datetime],
    started_at: datetime,
    ended_at: datetime | None,
    observed_through_utc: datetime,
) -> tuple[dict[datetime, CanonicalPeriodPriceEvidenceV31], tuple[datetime, ...]]:
    """A1-10: the qualifying-observation universe, decided before any bound is computed.

    Returns the qualifying evidence keyed by expected period, plus the periods that are **conflicted** — two
    distinct evidence ids for the same period. A conflicted period becomes a gap, never a silent pick.
    """

    by_period: dict[datetime, list[CanonicalPeriodPriceEvidenceV31]] = defaultdict(list)
    for raw in evidence:
        item = CanonicalPeriodPriceEvidenceV31.model_validate(raw.model_dump())
        if item.canonical_symbol != canonical_symbol:  # clause 1: the range's own symbol
            continue
        if not item.is_closed or item.quality != "AUTHORITATIVE":  # clauses 2 and 3
            continue
        if item.period_close_utc > observed_through_utc:  # clause 4: no future price
            continue
        if item.period_open_utc < started_at:  # clause 5: inside the window
            continue
        if ended_at is not None and item.period_close_utc > ended_at:
            continue
        if item.period_open_utc not in expected_periods:
            continue
        by_period[item.period_open_utc].append(item)

    qualified: dict[datetime, CanonicalPeriodPriceEvidenceV31] = {}
    conflicted: list[datetime] = []
    for period, items in by_period.items():
        distinct = {item.evidence_id: item for item in items}  # clause 6: identical evidence dedupes silently
        if len(distinct) == 1:
            qualified[period] = next(iter(distinct.values()))
        else:
            conflicted.append(period)  # clause 6: a conflict is a gap, never a pick
    return qualified, tuple(sorted(conflicted))


def _coverage_status(
    *,
    expected_periods: frozenset[datetime],
    qualified: dict[datetime, CanonicalPeriodPriceEvidenceV31],
    quarantined_periods: frozenset[datetime],
) -> PriceCoverageStatus:
    """A1-11, threshold-free. Precedence: QUARANTINED > MISSING > PARTIAL > COMPLETE."""

    if quarantined_periods:
        return "QUARANTINED"
    if not qualified:
        return "MISSING"
    if expected_periods - set(qualified):
        return "PARTIAL"
    return "COMPLETE"


def materialize_pressure_range_v31(
    *,
    lifecycle: AnalysisLifecycleV31,
    coverage_anchor_rule: CoverageAnchorRule,
    started_at: datetime,
    market_episode_closed_at: datetime | None,
    expected_periods: tuple[datetime, ...],
    evidence: tuple[CanonicalPeriodPriceEvidenceV31, ...],
    policy: PressureRangePolicyV31 | None,
    observed_through_utc: datetime,
) -> PressureRangeDecisionV31:
    """Materialise the range for one lifecycle.

    ``market_episode_closed_at`` is the ONLY thing that can close the window (A1-09). A superseded lifecycle and
    a terminated raw block both leave it open, so neither is an input here — the absence is the guarantee.
    """

    _aware("started_at", started_at)
    _aware("observed_through_utc", observed_through_utc)
    _aware("market_episode_closed_at", market_episode_closed_at)
    if policy is None:
        return _no("PRESSURE_RANGE_POLICY_MISSING")
    policy = PressureRangePolicyV31.model_validate(policy.model_dump())
    lifecycle = AnalysisLifecycleV31.model_validate(lifecycle.model_dump())
    if lifecycle.state in TERMINAL_LIFECYCLE_STATES_V31:
        return _no("LIFECYCLE_TERMINAL")
    for period in expected_periods:
        _aware("expected period", period)
    expected = frozenset(expected_periods)
    if len(expected) != len(expected_periods):
        return _no("EXPECTED_PERIODS_NOT_UNIQUE")
    if any(period < started_at for period in expected):
        return _no("EXPECTED_PERIOD_BEFORE_WINDOW_START")
    ended_at = market_episode_closed_at
    if ended_at is not None and ended_at < started_at:
        return _no("PRESSURE_RANGE_WINDOW_ORDER_INVALID")

    qualified, conflicted = qualifying_period_evidence_v31(
        evidence,
        canonical_symbol=lifecycle.symbol,
        expected_periods=expected,
        started_at=started_at,
        ended_at=ended_at,
        observed_through_utc=observed_through_utc,
    )
    # §11.5 owns the outlier ladder; this module only reads the verdict it produced.
    quarantined = frozenset(
        item.period_open_utc
        for item in evidence
        if item.canonical_symbol == lifecycle.symbol
        and item.quality == "QUARANTINED"
        and item.period_open_utc in expected
    )
    status = _coverage_status(expected_periods=expected, qualified=qualified, quarantined_periods=quarantined)
    gaps = tuple(sorted((expected - set(qualified)) | set(conflicted)))
    source_ids = tuple(sorted(item.evidence_id for item in qualified.values()))
    # A1-10 clause 7 / A1-11: one reference per qualifying period, or coverage is undecidable.
    if len(source_ids) != len(qualified):
        return _no("PRESSURE_RANGE_COVERAGE_UNDECIDABLE")

    low = min((item.low for item in qualified.values()), default=None)
    high = max((item.high for item in qualified.values()), default=None)
    if status == "MISSING":
        low, high = None, None  # never 0, never a fabricated point range
        source_ids = ()
        gaps = tuple(sorted(expected))
    elif low is None or high is None:
        return _no("PRESSURE_RANGE_BOUNDS_UNAVAILABLE")

    body = {
        "pressure_range_id": pressure_range_id_v31(
            strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
            coverage_anchor_rule=coverage_anchor_rule,
            started_at=started_at,
            range_policy_hash=policy.policy_hash,
        ),
        "strategy_lifecycle_id": lifecycle.strategy_lifecycle_id,
        "market_episode_id": lifecycle.market_episode_id,
        "canonical_symbol": lifecycle.symbol,
        "coverage_anchor_rule": coverage_anchor_rule,
        "started_at": started_at,
        "ended_at": ended_at,
        "low": low,
        "high": high,
        "price_coverage_status": status,
        "coverage_gaps": gaps,
        "source_price_ids": source_ids,
        "observed_through_utc": observed_through_utc,
        "range_policy_version": policy.policy_version,
        "range_policy_hash": policy.policy_hash,
        "structural_authority": status == "COMPLETE",
    }
    probe = PressureRangeV31.model_construct(**body, evidence_hash="sha256:" + "0" * 64)
    record = PressureRangeV31.model_validate({**body, "evidence_hash": pressure_range_evidence_hash_v31(probe)})
    return PressureRangeDecisionV31("MATERIALIZED", "PRESSURE_RANGE_MATERIALIZED", record)


def observe_pressure_range_v31(
    current: PressureRangeV31,
    *,
    lifecycle: AnalysisLifecycleV31,
    expected_periods: tuple[datetime, ...],
    evidence: tuple[CanonicalPeriodPriceEvidenceV31, ...],
    policy: PressureRangePolicyV31 | None,
    observed_through_utc: datetime,
) -> PressureRangeDecisionV31:
    """Re-observe an existing range. A1-09: once ``ended_at`` is set the record can never change again.

    Late evidence after closure does not mutate the canonical object and does not reopen it; the closed record
    is returned unchanged so the caller can record the arrival as a permanent gap on its own diagnostics.
    """

    current = PressureRangeV31.model_validate(current.model_dump())
    if current.ended_at is not None:
        return PressureRangeDecisionV31("MATERIALIZED", "PRESSURE_RANGE_CLOSED_NO_MUTATION", current)
    return materialize_pressure_range_v31(
        lifecycle=lifecycle,
        coverage_anchor_rule=current.coverage_anchor_rule,
        started_at=current.started_at,
        market_episode_closed_at=None,
        expected_periods=expected_periods,
        evidence=evidence,
        policy=policy,
        observed_through_utc=observed_through_utc,
    )


__all__ = [
    "PressureRangeDecisionV31",
    "materialize_pressure_range_v31",
    "observe_pressure_range_v31",
    "qualifying_period_evidence_v31",
]
