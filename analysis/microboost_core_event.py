"""Compact pure-stage Microboost view.

Translates a (heavy) ``MicroboostBlockIntel`` / ``microboost_summary['latest']``
into a minimal *core* event that honours the Microboost pure-stage contract:

  * Microboost is timing + location **evidence** on a pair that already passed a
    SignalThrottle clean block -- never a final direction, trade plan, RR, or
    execution decision.
  * ``direction`` is ALWAYS ``"UNRESOLVED"``; the raw pressure colour is kept
    separately as ``raw_pressure_direction`` so the hilir layers still receive a
    raw signal without Microboost resolving entry direction.
  * ``valid_for_execution`` is ALWAYS ``False`` and ``next_stage`` is always
    ``"SIGNAL_WATCH"`` -- strategy is delegated downstream.
  * Pattern / family / score / golden-reference fields are validator pass-through
    metadata, NOT Microboost's own logic, so they are excluded from the core
    event entirely (output is built strictly from an allowlist).

This module is additive: it reads the existing detector output and adds no
sequence, direction, or pattern logic of its own. See
``docs/architecture/contracts/microboost-pure-stage-contract.md``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "MICROBOOST_CORE_EVENT_FIELDS",
    "MICROBOOST_DOWNSTREAM_METADATA_FIELDS",
    "to_microboost_core_event",
]

CORE_REASON = "Microboost timing evidence; strategy decision delegated to SignalWatch/SignalDecision."

# The complete, closed set of keys a Microboost core event may carry.
MICROBOOST_CORE_EVENT_FIELDS: frozenset[str] = frozenset(
    {
        "event",
        "schema_version",
        "symbol",
        "direction",
        "raw_pressure_direction",
        "phase_unpriced",
        "phase_priced",
        "price_position",
        "start_utc",
        "end_utc",
        "duration_minutes",
        "effective_tick_count",
        "effective_density_per_minute",
        "requires_market_context",
        "valid_for_execution",
        "next_stage",
        "reason",
    }
)

# Validator pass-through metadata that must NOT appear on the Microboost core
# stream. These belong in ``market_context_validation`` / ``[PatternMatchDebugJSON]``.
MICROBOOST_DOWNSTREAM_METADATA_FIELDS: frozenset[str] = frozenset(
    {
        "strategy_pattern",
        "phase_grade",
        "execution_side",
        "strategy_priority",
        "waiting_for",
        "requires_confirmation",
        "matched_patterns",
        "selected_pattern_id",
        "pattern_tier",
        "pattern_family",
        "pattern_score",
        "pattern_match_score",
        "execution_readiness_score",
        "golden_reference",
        "golden_references",
        "pattern_scope",
        "applies_to",
        "pair_specific_calibration",
        "pair_role",
        "entry_permission",
        "management_action",
        "hold_policy",
        "chase_allowed",
        "block_reason",
        "pattern_evidence",
        "pattern_search_space",
        "pattern_db_candidates_scanned",
        "pattern_db_exact_matches",
        "pattern_db_fuzzy_matches",
        "pattern_bottlenecks",
        "pattern_match_diagnostics",
        "jpy_alignment_status",
        "theme_alignment_status",
        "dual_theme_status",
        "alignment_missing_reason",
        "market_context_validation",
        "market_context_snapshot",
        "microboost_role",
        "microboost_followthrough_bias",
        "microboost_room_to_move_pips",
        "microboost_pre_move_pips",
        "microboost_late_move_penalty",
        "microboost_followthrough_context_ready",
        "microboost_price_behavior",
        "microboost_room_to_move_status",
        "microboost_stall_pips",
        "microboost_room_to_target_pips",
        "microboost_expected_horizon",
        "microboost_outcome_tracking_required",
        "microboost_role_source_event",
        "microboost_role_reason_codes",
        "microboost_role_valid_for_execution",
        "microboost_role_execution_impact",
        "microboost_role_advisory_only",
        "room_to_move_pips",
        "pre_move_pips",
        "late_move_penalty",
        "followthrough_context_ready",
        "score",
        "score_components",
    }
)


def to_microboost_core_event(block: Any) -> dict[str, Any]:
    """Render one microboost block as a compact pure-stage core event.

    ``block`` is the dict from ``microboost_summary['latest']`` /
    ``['blocks'][i]`` or a ``MicroboostBlockIntel`` (attribute access). Only the
    timing/location fields are read; every strategy/pattern field is ignored.
    """
    return {
        "event": "microboost_qualified",
        "schema_version": "1.0",
        "symbol": _get(block, "symbol", None),
        # Pure-stage: Microboost never resolves a trade direction.
        "direction": "UNRESOLVED",
        "raw_pressure_direction": _raw_pressure_direction(block),
        "phase_unpriced": _get(block, "phase_unpriced", None),
        "phase_priced": _get(block, "phase_priced", None),
        "price_position": _get(block, "price_position", None),
        "start_utc": _get(block, "start_utc", None),
        "end_utc": _get(block, "end_utc", None),
        "duration_minutes": _get(block, "duration_minutes", None),
        "effective_tick_count": _get(block, "effective_tick_count", None),
        "effective_density_per_minute": _get(block, "effective_density_per_minute", None),
        "requires_market_context": bool(_get(block, "requires_market_context", True)),
        "valid_for_execution": False,
        "next_stage": "SIGNAL_WATCH",
        "reason": CORE_REASON,
    }


def _raw_pressure_direction(block: Any) -> str:
    raw = str(_get(block, "direction", "") or "").upper()
    return raw if raw in {"BUY", "SELL"} else "NONE"


def _get(source: Any, key: str, default: Any) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)
