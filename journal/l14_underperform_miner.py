"""
L14 Adaptive Reflection — pattern recognition for historically underperforming setups.

Purpose
-------
Adds a journal-driven pattern recognition layer on top of the existing L13/L14
reflection flow. The module mines J3/J4 journal records to detect setup types
that repeatedly underperform and returns penalties / warnings that can be fed
back into the constitutional pipeline.

Design goals
------------
- Pure Python stdlib only.
- Works with semi-structured journal rows (dicts from JSON/Redis/Postgres).
- Uses real journal data from J3/J4, not heuristic fantasy data.
- Produces explainable output: which pattern, how many trades, expectancy,
  win-rate, loss streak, and why it is flagged.
- Safe by default: high sample threshold, confidence-aware scoring,
  no single-trade superstition nonsense.

Integration into WolfConstitutionalPipeline.execute():
  Phase 2.5 (after Enrichment, before L12):
    1. Load recent J3/J4 rows from storage
    2. report = L14AdaptiveReflection().analyze(j3_rows, j4_rows, current_context={...})
    3. penalty = report.current_setup_penalty (bounded 0..0.35)
    4. synthesis["layers"]["enrichment_confidence_adj"] -= penalty
  This feeds into L12 via existing enrichment mechanism — constitutional-compliant.

Changelog (v1.1.0)
-------------------
- FIX: JournalRecord now frozen=True so mutation raises AttributeError.
- FIX: PatternStats.reasons changed list[str] → tuple[str, ...] for immutability.
- FIX: Added _MAX_GROUPED_KEYS = 5000 constant + early-exit memory guard.
- FIX: 'pair' included in DEFAULT_DIMENSIONS for forex pair-level patterns.
- FIX: min_penalty_score lowered to 0.30 to reflect actual formula output range.
- FIX: Demo data replaced with mixed dataset so baseline ≠ pattern (gap > 0).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import combinations
from math import sqrt
from statistics import mean, median
from typing import Any

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MAX_GROUPED_KEYS: int = 5000
"""Memory guard: maximum number of unique pattern keys before early-exit."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JournalRecord:
    """Normalised, immutable view of a raw J3/J4 row."""

    stage: str
    setup_type: str
    pair: str | None
    timeframe: str | None
    session: str | None
    regime: str | None
    direction: str | None
    confidence_bucket: str | None
    news_state: str | None
    volatility_regime: str | None
    outcome_r: float
    pnl: float | None
    result: str
    timestamp: datetime | None
    raw: Mapping[str, Any] = field(repr=False)

    @property
    def is_win(self) -> bool:
        """Return True when outcome_r > 0."""
        return self.outcome_r > 0

    @property
    def is_loss(self) -> bool:
        """Return True when outcome_r < 0."""
        return self.outcome_r < 0


@dataclass(frozen=True, slots=True)
class PatternStats:
    """Statistical profile of a historically underperforming setup pattern."""

    signature: str
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    trades: int
    wins: int
    losses: int
    breakevens: int
    win_rate: float
    expectancy_r: float
    median_r: float
    avg_pnl: float | None
    total_pnl: float | None
    loss_streak_max: int
    wilson_low: float
    penalty_score: float
    reasons: tuple[str, ...]


@dataclass(slots=True)
class AdaptiveReflectionReport:
    """Full output of one L14 adaptive reflection analysis run."""

    total_records: int
    usable_records: int
    baseline_expectancy_r: float
    baseline_win_rate: float
    flagged_patterns: list[PatternStats]
    current_setup_matches: list[PatternStats]
    current_setup_penalty: float
    adaptive_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this report."""

        def _pattern_dict(p: PatternStats) -> dict[str, Any]:
            d = asdict(p)
            d.update(
                win_rate=round(p.win_rate, 4),
                expectancy_r=round(p.expectancy_r, 4),
                median_r=round(p.median_r, 4),
                avg_pnl=None if p.avg_pnl is None else round(p.avg_pnl, 4),
                total_pnl=None if p.total_pnl is None else round(p.total_pnl, 4),
                wilson_low=round(p.wilson_low, 4),
                penalty_score=round(p.penalty_score, 4),
            )
            return d

        return {
            "total_records": self.total_records,
            "usable_records": self.usable_records,
            "baseline_expectancy_r": round(self.baseline_expectancy_r, 4),
            "baseline_win_rate": round(self.baseline_win_rate, 4),
            "current_setup_penalty": round(self.current_setup_penalty, 4),
            "adaptive_notes": self.adaptive_notes,
            "flagged_patterns": [_pattern_dict(p) for p in self.flagged_patterns],
            "current_setup_matches": [_pattern_dict(p) for p in self.current_setup_matches],
        }


# ---------------------------------------------------------------------------
# Private utility functions
# ---------------------------------------------------------------------------


def _first_present(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first key in *keys* that exists and is non-empty in *data*."""
    for key in keys:
        if key in data and data[key] not in (None, "", [], {}):
            return data[key]
    return default


def _norm_text(value: Any) -> str | None:
    """Normalise a value to an upper-case underscore-delimited string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.upper().replace(" ", "_")


def _to_float(value: Any) -> float | None:
    """Coerce *value* to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    """Parse *value* into a datetime object, returning None on failure."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    # (format, truncate_to_19) — truncate only for datetime formats that may
    # include sub-second or timezone suffixes that strptime cannot consume.
    _FORMATS: tuple[tuple[str, bool], ...] = (  # noqa: N806
        ("%Y-%m-%d %H:%M:%S", True),
        ("%Y-%m-%dT%H:%M:%S", True),
        ("%Y-%m-%d", False),
        ("%d-%m-%Y %H:%M:%S", True),
        ("%d-%m-%Y", False),
    )
    for fmt, truncate in _FORMATS:
        try:
            return datetime.strptime(text[:19] if truncate else text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _infer_result(outcome_r: float | None, explicit_result: Any) -> str:
    """Derive a canonical result string from an explicit label or the R value."""
    result = _norm_text(explicit_result)
    if result in {"WIN", "LOSS", "BE", "BREAKEVEN", "BREAK_EVEN"}:
        return "BE" if result in {"BE", "BREAKEVEN", "BREAK_EVEN"} else result
    if outcome_r is None:
        return "UNKNOWN"
    if outcome_r > 0:
        return "WIN"
    if outcome_r < 0:
        return "LOSS"
    return "BE"


def _wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Compute the Wilson score lower confidence bound for a win proportion."""
    if total <= 0:
        return 0.0
    phat = wins / total
    denom = 1 + z * z / total
    center = phat + z * z / (2 * total)
    margin = z * sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return max(0.0, (center - margin) / denom)


def _max_loss_streak(records: list[JournalRecord]) -> int:
    """Return the longest consecutive-loss streak in *records* (sorted by timestamp)."""
    streak = 0
    max_streak = 0
    for record in sorted(records, key=lambda r: r.timestamp or datetime.min):
        if record.is_loss:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


# ---------------------------------------------------------------------------
# JournalExtractor
# ---------------------------------------------------------------------------


class JournalExtractor:
    """Tolerant extraction of :class:`JournalRecord` instances from raw dict rows.

    Accepts multiple field-name aliases so it works with schemas from Redis,
    Postgres, and flat JSON exports without pre-processing.
    """

    def extract(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> tuple[list[JournalRecord], int]:
        """Extract normalised records from raw journal rows.

        Args:
            rows: Iterable of raw dict rows from J3/J4 journal storage.

        Returns:
            A 2-tuple of (usable_records, total_rows_seen).  Records missing
            ``setup_type`` or ``outcome_r`` are silently skipped.
        """
        records: list[JournalRecord] = []
        total = 0
        for row in rows:
            total += 1
            setup_type = _norm_text(
                _first_present(row, "setup_type", "setup", "setup_name", "model", "pattern")
            )
            outcome_r = _to_float(
                _first_present(
                    row,
                    "outcome_r", "realized_r", "r_multiple", "r", "result_r", "rr_realized",
                )
            )
            if setup_type is None or outcome_r is None:
                continue
            record = JournalRecord(
                stage=_norm_text(
                    _first_present(row, "journal_stage", "stage", default="J?")
                ) or "J?",
                setup_type=setup_type,
                pair=_norm_text(_first_present(row, "pair", "symbol", "instrument")),
                timeframe=_norm_text(_first_present(row, "timeframe", "tf")),
                session=_norm_text(_first_present(row, "session")),
                regime=_norm_text(_first_present(row, "regime", "market_regime")),
                direction=_norm_text(_first_present(row, "direction", "side")),
                confidence_bucket=_norm_text(
                    _first_present(
                        row, "confidence_bucket", "quality_bucket", "confidence"
                    )
                ),
                news_state=_norm_text(_first_present(row, "news_state", "news_filter")),
                volatility_regime=_norm_text(
                    _first_present(row, "volatility_regime", "vol_regime")
                ),
                outcome_r=outcome_r,
                pnl=_to_float(_first_present(row, "pnl", "realized_pnl", "profit")),
                result=_infer_result(
                    outcome_r, _first_present(row, "result", "outcome")
                ),
                timestamp=_to_datetime(
                    _first_present(row, "timestamp", "closed_at", "created_at", "date")
                ),
                raw=row,
            )
            records.append(record)
        return records, total


# ---------------------------------------------------------------------------
# UnderperformPatternMiner
# ---------------------------------------------------------------------------


class UnderperformPatternMiner:
    """Combinatorial pattern miner over :class:`JournalRecord` collections.

    Mines all 1–N-dimensional combinations of setup dimensions to find
    historically underperforming patterns.  Uses Wilson lower bound to
    suppress conclusions from tiny samples.
    """

    DEFAULT_DIMENSIONS: tuple[str, ...] = (
        "setup_type",
        "pair",
        "timeframe",
        "session",
        "regime",
        "direction",
        "confidence_bucket",
        "news_state",
        "volatility_regime",
    )

    def __init__(
        self,
        *,
        min_trades: int = 8,
        max_combo_size: int = 3,
        min_expectancy_gap: float = 0.25,
        min_negative_expectancy: float = -0.10,
        min_loss_streak: int = 3,
        min_penalty_score: float = 0.30,  # FIX: was 0.55, formula rarely exceeds ~0.44
        max_patterns: int = 12,
    ) -> None:
        super().__init__()
        self.min_trades = min_trades
        self.max_combo_size = max_combo_size
        self.min_expectancy_gap = min_expectancy_gap
        self.min_negative_expectancy = min_negative_expectancy
        self.min_loss_streak = min_loss_streak
        self.min_penalty_score = min_penalty_score
        self.max_patterns = max_patterns

    def mine(
        self, records: list[JournalRecord]
    ) -> tuple[list[PatternStats], float, float]:
        """Mine *records* for underperforming patterns.

        Args:
            records: Normalised journal records to analyse.

        Returns:
            A 3-tuple of (flagged_patterns, baseline_expectancy, baseline_win_rate).
        """
        if not records:
            return [], 0.0, 0.0

        baseline_expectancy = mean(r.outcome_r for r in records)
        baseline_win_rate = sum(r.is_win for r in records) / len(records)

        grouped: dict[
            tuple[tuple[str, ...], tuple[str, ...]], list[JournalRecord]
        ] = defaultdict(list)

        _limit_reached = False
        for record in records:
            if _limit_reached:
                break
            for combo_size in range(1, self.max_combo_size + 1):
                if _limit_reached:
                    break
                for dims in combinations(self.DEFAULT_DIMENSIONS, combo_size):
                    # Memory guard: stop building groups if the dict is too large.
                    if len(grouped) >= _MAX_GROUPED_KEYS:
                        _limit_reached = True
                        break
                    values: list[str] = []
                    skip = False
                    for dim in dims:
                        value = getattr(record, dim)
                        if value is None:
                            skip = True
                            break
                        values.append(value)
                    if skip:
                        continue
                    grouped[(dims, tuple(values))].append(record)

        flagged: list[PatternStats] = []
        for (dims, dim_values), subset in grouped.items():
            if len(subset) < self.min_trades:
                continue

            wins = sum(r.is_win for r in subset)
            losses = sum(r.is_loss for r in subset)
            bes = len(subset) - wins - losses
            expectancy = mean(r.outcome_r for r in subset)
            wr = wins / len(subset)
            expectancy_gap = baseline_expectancy - expectancy
            wilson_low = _wilson_lower_bound(wins, len(subset))
            loss_streak_max = _max_loss_streak(subset)
            pnl_values = [r.pnl for r in subset if r.pnl is not None]
            avg_pnl = mean(pnl_values) if pnl_values else None
            total_pnl = sum(pnl_values) if pnl_values else None

            reasons: list[str] = []
            if expectancy <= self.min_negative_expectancy:
                reasons.append(f"negative_expectancy={expectancy:.2f}R")
            if expectancy_gap >= self.min_expectancy_gap:
                reasons.append(f"below_baseline_by={expectancy_gap:.2f}R")
            if loss_streak_max >= self.min_loss_streak:
                reasons.append(f"loss_streak={loss_streak_max}")
            if wilson_low < max(0.25, baseline_win_rate * 0.6):
                reasons.append(f"weak_wilson_low={wilson_low:.2f}")

            if not reasons:
                continue

            sample_factor = min(1.0, len(subset) / (self.min_trades * 2))
            expectancy_factor = max(0.0, baseline_expectancy - expectancy)
            streak_factor = min(1.0, loss_streak_max / 6)
            win_deficit_factor = max(0.0, baseline_win_rate - wr)
            penalty_score = min(
                1.0,
                0.45 * expectancy_factor
                + 0.20 * streak_factor
                + 0.20 * win_deficit_factor
                + 0.15 * sample_factor,
            )

            if penalty_score < self.min_penalty_score:
                continue

            flagged.append(
                PatternStats(
                    signature=" | ".join(f"{d}={v}" for d, v in zip(dims, dim_values, strict=False)),
                    dimensions=dims,
                    values=dim_values,
                    trades=len(subset),
                    wins=wins,
                    losses=losses,
                    breakevens=bes,
                    win_rate=wr,
                    expectancy_r=expectancy,
                    median_r=median(r.outcome_r for r in subset),
                    avg_pnl=avg_pnl,
                    total_pnl=total_pnl,
                    loss_streak_max=loss_streak_max,
                    wilson_low=wilson_low,
                    penalty_score=penalty_score,
                    reasons=tuple(reasons),
                )
            )

        flagged.sort(
            key=lambda p: (p.penalty_score, len(p.dimensions), p.trades),
            reverse=True,
        )

        pruned: list[PatternStats] = []
        seen: set[str] = set()
        for pattern in flagged:
            key = pattern.signature
            if key in seen:
                continue
            seen.add(key)
            pruned.append(pattern)
            if len(pruned) >= self.max_patterns:
                break

        return pruned, baseline_expectancy, baseline_win_rate


# ---------------------------------------------------------------------------
# L14AdaptiveReflection orchestrator
# ---------------------------------------------------------------------------


class L14AdaptiveReflection:
    """Orchestrator: extraction → mining → context matching → penalty aggregation.

    Constitutional boundary
    -----------------------
    This class is ADVISORY ONLY.  It produces penalty scores and insight notes
    that *may* be injected into the enrichment layer via
    ``enrichment_confidence_adj``.  It cannot override L12 verdicts and has no
    execution side-effects.
    """

    def __init__(self, miner: UnderperformPatternMiner | None = None) -> None:
        super().__init__()
        self.extractor = JournalExtractor()
        self.miner = miner or UnderperformPatternMiner()

    def analyze(
        self,
        j3_rows: Iterable[Mapping[str, Any]],
        j4_rows: Iterable[Mapping[str, Any]],
        *,
        current_context: Mapping[str, Any] | None = None,
    ) -> AdaptiveReflectionReport:
        """Run a full adaptive reflection analysis.

        Args:
            j3_rows: Raw J3 (execution) journal rows.
            j4_rows: Raw J4 (reflection) journal rows.
            current_context: Optional dict of the current setup's dimension values
                used to match against flagged patterns.

        Returns:
            :class:`AdaptiveReflectionReport` with penalty scores and notes.
        """
        all_rows = list(j3_rows) + list(j4_rows)
        records, total_rows = self.extractor.extract(all_rows)
        patterns, baseline_expectancy, baseline_win_rate = self.miner.mine(records)
        matches = self._match_current_context(patterns, current_context or {})
        penalty = self._aggregate_penalty(matches)
        notes = self._build_notes(matches, penalty)
        return AdaptiveReflectionReport(
            total_records=total_rows,
            usable_records=len(records),
            baseline_expectancy_r=baseline_expectancy,
            baseline_win_rate=baseline_win_rate,
            flagged_patterns=patterns,
            current_setup_matches=matches,
            current_setup_penalty=penalty,
            adaptive_notes=notes,
        )

    def penalty_for_current_setup(
        self,
        report: AdaptiveReflectionReport,
        *,
        max_penalty: float = 0.35,
    ) -> float:
        """Return the capped penalty suitable for injecting into enrichment_confidence_adj.

        Args:
            report: A previously computed :class:`AdaptiveReflectionReport`.
            max_penalty: Hard cap on the returned value (default 0.35).

        Returns:
            A penalty in ``[0.0, max_penalty]``.
        """
        return min(max_penalty, report.current_setup_penalty)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _match_current_context(
        self,
        patterns: list[PatternStats],
        current_context: Mapping[str, Any],
    ) -> list[PatternStats]:
        if not current_context:
            return []
        normalized = {
            k: _norm_text(v)
            for k, v in current_context.items()
            if v not in (None, "")
        }
        matches: list[PatternStats] = []
        for pattern in patterns:
            ok = True
            for dim, value in zip(pattern.dimensions, pattern.values, strict=False):
                if normalized.get(dim) != value:
                    ok = False
                    break
            if ok:
                matches.append(pattern)
        matches.sort(
            key=lambda p: (len(p.dimensions), p.penalty_score), reverse=True
        )
        return matches

    def _aggregate_penalty(self, matches: list[PatternStats]) -> float:
        if not matches:
            return 0.0
        weighted: list[float] = []
        for pattern in matches:
            specificity = min(1.0, len(pattern.dimensions) / 3)
            weighted.append(pattern.penalty_score * (0.65 + 0.35 * specificity))
        weighted.sort(reverse=True)
        penalty = weighted[0]
        for tail in weighted[1:3]:
            penalty += tail * 0.20
        return min(1.0, penalty)

    def _build_notes(
        self, matches: list[PatternStats], penalty: float
    ) -> list[str]:
        if not matches:
            return [
                "Tidak ada pola underperform yang cukup kuat dari J3/J4 "
                "untuk setup saat ini."
            ]
        notes = [
            f"Adaptive penalty {penalty:.2f}: setup saat ini match dengan "
            "pola underperform historis."
        ]
        for pattern in matches[:3]:
            notes.append(
                f"Waspada {pattern.signature} → expectancy "
                f"{pattern.expectancy_r:.2f}R dari {pattern.trades} trade, "
                f"win-rate {pattern.win_rate:.0%}, "
                f"alasan: {', '.join(pattern.reasons)}"
            )
        return notes


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def analyze_underperforming_setups(
    j3_rows: Iterable[Mapping[str, Any]],
    j4_rows: Iterable[Mapping[str, Any]],
    *,
    current_context: Mapping[str, Any] | None = None,
    min_trades: int = 8,
    max_combo_size: int = 3,
) -> dict[str, Any]:
    """One-call helper that returns a JSON-friendly analysis dict.

    Args:
        j3_rows: Raw J3 journal rows.
        j4_rows: Raw J4 journal rows.
        current_context: Optional current setup context for penalty matching.
        min_trades: Minimum trades required to flag a pattern (anti-superstition).
        max_combo_size: Maximum dimension combination depth.

    Returns:
        JSON-serialisable dict from :meth:`AdaptiveReflectionReport.to_dict`.
    """
    engine = L14AdaptiveReflection(
        UnderperformPatternMiner(
            min_trades=min_trades, max_combo_size=max_combo_size
        )
    )
    return engine.analyze(
        j3_rows, j4_rows, current_context=current_context
    ).to_dict()


# ---------------------------------------------------------------------------
# Demo / smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import json

    # Mixed demo: two setup types with different outcomes so baseline ≠ pattern.
    _good_setup = [
        {
            "setup_type": "LONDON_SWEEP",
            "pair": "EURUSD",
            "timeframe": "H1",
            "session": "LONDON",
            "regime": "TREND",
            "direction": "LONG",
            "outcome_r": r,
            "pnl": r * 50,
            "journal_stage": "J4",
        }
        for r in [1.5, 2.0, 1.2, 1.8, 2.5, 1.0, 2.2, 1.7, 2.1, 1.9]
    ]
    _bad_setup = [
        {
            "setup_type": "LONDON_SWEEP",
            "pair": "XAUUSD",
            "timeframe": "M15",
            "session": "LONDON",
            "regime": "RANGE",
            "direction": "SHORT",
            "outcome_r": r,
            "pnl": r * 50,
            "journal_stage": "J4",
        }
        for r in [-0.8, -1.0, -0.5, -1.2, -0.7, -0.9, -0.6, -1.1, -0.4, -0.8]
    ]

    _j4_rows = _good_setup + _bad_setup
    _context = {
        "setup_type": "LONDON_SWEEP",
        "pair": "XAUUSD",
        "timeframe": "M15",
        "session": "LONDON",
        "regime": "RANGE",
        "direction": "SHORT",
    }

    _result = analyze_underperforming_setups(
        [], _j4_rows, current_context=_context, min_trades=8
    )
    print(json.dumps(_result, indent=2, default=str))
