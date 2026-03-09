"""
Layer 13 — Post-Trade Reflection Engine
Zone: Journal (J4). Append-only. NO execution side-effects. NO decision authority.

Evaluates completed or rejected setups after the fact:
  - Was the L12 verdict correct given the actual outcome?
  - What was the quality of entry/exit timing?
  - Which analysis layers contributed most to accuracy or error?
  - Emotional/psychological factors in hindsight.

Output is an immutable reflection record appended to the journal.
L13 NEVER overrides, modifies, or feeds back into L12 verdicts in real-time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ReflectionVerdict(StrEnum):
    """Was the original L12 decision correct in hindsight?"""
    CORRECT_EXECUTE = "CORRECT_EXECUTE"         # took trade, was profitable
    CORRECT_REJECT = "CORRECT_REJECT"           # rejected, would have lost
    INCORRECT_EXECUTE = "INCORRECT_EXECUTE"     # took trade, lost
    INCORRECT_REJECT = "INCORRECT_REJECT"       # rejected, would have been profitable
    INCONCLUSIVE = "INCONCLUSIVE"               # no clear outcome


class OutcomeType(StrEnum):
    """Actual trade outcome category."""
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    EXPIRED = "EXPIRED"             # pending never filled
    REJECTED_NO_TRADE = "REJECTED"  # L12 said no


@dataclass(frozen=True)
class TradeOutcome:
    """Actual result data for a completed or expired setup."""
    symbol: str
    outcome_type: OutcomeType
    pnl_pips: float | None = None
    pnl_percent: float | None = None
    actual_rr: float | None = None       # actual risk:reward achieved
    planned_rr: float | None = None      # what L12 planned
    hold_duration_minutes: float | None = None
    exit_reason: str = ""                   # TP hit, SL hit, manual, expired


@dataclass(frozen=True)
class OriginalDecision:
    """Snapshot of what L12 decided at signal time."""
    signal_id: str
    symbol: str
    verdict: str                    # EXECUTE / REJECT / HOLD
    confidence: float
    wolf_score: float | None = None
    tii_score: float | None = None
    psych_state: str | None = None
    timestamp: str = ""


@dataclass(frozen=True)
class LayerContribution:
    """How much a specific layer contributed to the outcome — positive or negative."""
    layer: str
    accuracy_contribution: str      # POSITIVE | NEGATIVE | NEUTRAL
    note: str = ""


@dataclass(frozen=True)
class L13ReflectionRecord:
    """
    Immutable reflection output. Appended to journal (J4).
    This record MUST NOT feed back into L12 in real-time.
    """
    signal_id: str
    symbol: str
    reflection_verdict: ReflectionVerdict
    original_decision: OriginalDecision
    trade_outcome: TradeOutcome
    layer_contributions: tuple[LayerContribution, ...]
    timing_quality: float               # 0–100: how good was entry timing
    exit_quality: float                 # 0–100: how good was exit execution
    lesson_tags: tuple[str, ...]        # e.g. ("early_entry", "held_too_long")
    reflection_notes: str
    timestamp: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BREAKEVEN_THRESHOLD_PIPS: float = 2.0


def _classify_reflection_verdict(
    original_verdict: str,
    outcome: TradeOutcome,
) -> ReflectionVerdict:
    """
    Compare what L12 decided vs. what actually happened.
    Pure function — no side-effects.
    """
    was_executed = original_verdict.upper() in ("EXECUTE", "EXECUTED")

    if outcome.outcome_type == OutcomeType.REJECTED_NO_TRADE:
        # Check if price moved favourably after rejection
        if outcome.pnl_pips is not None and outcome.pnl_pips > BREAKEVEN_THRESHOLD_PIPS:
            return ReflectionVerdict.INCORRECT_REJECT
        if outcome.pnl_pips is not None and outcome.pnl_pips < -BREAKEVEN_THRESHOLD_PIPS:
            return ReflectionVerdict.CORRECT_REJECT
        return ReflectionVerdict.INCONCLUSIVE

    if was_executed:
        if outcome.outcome_type == OutcomeType.WIN:
            return ReflectionVerdict.CORRECT_EXECUTE
        if outcome.outcome_type == OutcomeType.LOSS:
            return ReflectionVerdict.INCORRECT_EXECUTE
        if outcome.outcome_type == OutcomeType.BREAKEVEN:
            return ReflectionVerdict.INCONCLUSIVE
        return ReflectionVerdict.INCONCLUSIVE

    # Was rejected but we have hypothetical outcome data
    if outcome.outcome_type == OutcomeType.WIN:
        return ReflectionVerdict.INCORRECT_REJECT
    if outcome.outcome_type == OutcomeType.LOSS:
        return ReflectionVerdict.CORRECT_REJECT
    return ReflectionVerdict.INCONCLUSIVE


def _evaluate_timing_quality(
    outcome: TradeOutcome,
) -> float:
    """
    Score entry timing quality 0–100 based on actual RR vs planned.
    If actual_rr >= planned_rr → excellent timing.
    Pure function.
    """
    if outcome.actual_rr is None or outcome.planned_rr is None:
        return 50.0     # neutral when data unavailable

    if outcome.planned_rr <= 0:
        return 50.0

    ratio = outcome.actual_rr / outcome.planned_rr
    # ratio > 1 means we achieved better than planned
    score = min(100.0, max(0.0, 50.0 + (ratio - 1.0) * 50.0))
    return round(score, 2)


def _evaluate_exit_quality(
    outcome: TradeOutcome,
) -> float:
    """
    Score exit quality 0–100.
    TP hit = good. SL hit after being in profit = poor. Manual early = context-dependent.
    """
    exit_lower = outcome.exit_reason.lower()

    if "tp" in exit_lower or "take_profit" in exit_lower:
        return 90.0
    if "sl" in exit_lower or "stop_loss" in exit_lower:
        if outcome.pnl_pips is not None and outcome.pnl_pips > 0:
            return 60.0     # trailed but hit SL in profit
        return 30.0
    if "manual" in exit_lower:
        if outcome.outcome_type == OutcomeType.WIN:
            return 65.0
        return 40.0
    if "expired" in exit_lower:
        return 50.0
    return 50.0


def _extract_lesson_tags(
    reflection_verdict: ReflectionVerdict,
    outcome: TradeOutcome,
    timing_quality: float,
    exit_quality: float,
) -> list[str]:
    """Generate lesson tags for pattern recognition. Pure function."""
    tags: list[str] = []

    if reflection_verdict == ReflectionVerdict.INCORRECT_EXECUTE:
        tags.append("loss_taken")
    if reflection_verdict == ReflectionVerdict.INCORRECT_REJECT:
        tags.append("missed_opportunity")
    if reflection_verdict == ReflectionVerdict.CORRECT_REJECT:
        tags.append("good_rejection")

    if timing_quality < 30.0:
        tags.append("poor_entry_timing")
    if timing_quality > 80.0:
        tags.append("excellent_entry_timing")

    if exit_quality < 30.0:
        tags.append("poor_exit")
    if exit_quality > 80.0:
        tags.append("clean_exit")

    if outcome.hold_duration_minutes is not None:
        if outcome.hold_duration_minutes < 5.0:
            tags.append("very_short_hold")
        elif outcome.hold_duration_minutes > 480.0:
            tags.append("extended_hold")

    if outcome.actual_rr is not None and outcome.planned_rr is not None:  # noqa: SIM102
        if outcome.actual_rr < outcome.planned_rr * 0.5 and outcome.outcome_type == OutcomeType.WIN:
            tags.append("cut_winner_short")

    return tags


def _evaluate_layer_contributions(
    original: OriginalDecision,
    outcome: TradeOutcome,
) -> list[LayerContribution]:
    """
    Coarse attribution of which layers helped or hurt.
    This is a simplified heuristic — real attribution requires deeper analysis.
    """
    contributions: list[LayerContribution] = []
    was_correct = outcome.outcome_type in (OutcomeType.WIN, OutcomeType.BREAKEVEN)

    # L4 scoring
    if original.wolf_score is not None:
        if original.wolf_score >= 70 and was_correct:
            contributions.append(LayerContribution(
                layer="L4_scoring", accuracy_contribution="POSITIVE",
                note=f"High wolf score {original.wolf_score:.1f} aligned with win",
            ))
        elif original.wolf_score >= 70 and not was_correct:
            contributions.append(LayerContribution(
                layer="L4_scoring", accuracy_contribution="NEGATIVE",
                note=f"High wolf score {original.wolf_score:.1f} but trade lost",
            ))
        else:
            contributions.append(LayerContribution(
                layer="L4_scoring", accuracy_contribution="NEUTRAL",
            ))

    # L8 TII
    if original.tii_score is not None:
        if original.tii_score >= 70 and was_correct:
            contributions.append(LayerContribution(
                layer="L8_tii", accuracy_contribution="POSITIVE",
                note=f"High TII {original.tii_score:.1f} confirmed clean setup",
            ))
        elif original.tii_score < 50 and not was_correct:
            contributions.append(LayerContribution(
                layer="L8_tii", accuracy_contribution="POSITIVE",
                note=f"Low TII {original.tii_score:.1f} correctly flagged risk",
            ))
        else:
            contributions.append(LayerContribution(
                layer="L8_tii", accuracy_contribution="NEUTRAL",
            ))

    # L5 psych
    if original.psych_state:
        if original.psych_state in ("TILT", "IMPAIRED") and not was_correct:
            contributions.append(LayerContribution(
                layer="L5_psychology", accuracy_contribution="POSITIVE",
                note=f"Psych state '{original.psych_state}' warned correctly",
            ))
        elif original.psych_state in ("TILT", "IMPAIRED") and was_correct:
            contributions.append(LayerContribution(
                layer="L5_psychology", accuracy_contribution="NEGATIVE",
                note=f"Psych state '{original.psych_state}' was false alarm",
            ))
        else:
            contributions.append(LayerContribution(
                layer="L5_psychology", accuracy_contribution="NEUTRAL",
            ))

    return contributions


def reflect(
    original_decision: OriginalDecision,
    trade_outcome: TradeOutcome,
    reflection_notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> L13ReflectionRecord:
    """
    Main entry point for Layer-13 post-trade reflection.

    This is a JOURNAL operation — append-only.
    MUST NOT modify any upstream state or feed into L12 in real-time.

    Parameters
    ----------
    original_decision : OriginalDecision
        Snapshot of what L12 decided.
    trade_outcome : TradeOutcome
        Actual result after trade/rejection.
    reflection_notes : str
        Optional human notes.
    metadata : dict, optional
        Additional context.

    Returns
    -------
    L13ReflectionRecord
        Immutable reflection to be appended to J4 journal.
    """
    reflection_verdict = _classify_reflection_verdict(
        original_decision.verdict,
        trade_outcome,
    )
    timing_quality = _evaluate_timing_quality(trade_outcome)
    exit_quality = _evaluate_exit_quality(trade_outcome)
    lesson_tags = _extract_lesson_tags(
        reflection_verdict, trade_outcome, timing_quality, exit_quality,
    )
    layer_contributions = _evaluate_layer_contributions(
        original_decision, trade_outcome,
    )

    record = L13ReflectionRecord(
        signal_id=original_decision.signal_id,
        symbol=original_decision.symbol,
        reflection_verdict=reflection_verdict,
        original_decision=original_decision,
        trade_outcome=trade_outcome,
        layer_contributions=tuple(layer_contributions),
        timing_quality=timing_quality,
        exit_quality=exit_quality,
        lesson_tags=tuple(lesson_tags),
        reflection_notes=reflection_notes,
        timestamp=datetime.now(UTC).isoformat(),
        metadata=metadata or {},
    )

    logger.info(
        "L13 %s [%s] | verdict=%s timing=%.1f exit=%.1f | tags=%s",
        record.symbol, record.signal_id, reflection_verdict.value,
        timing_quality, exit_quality, lesson_tags,
    )
    return record
