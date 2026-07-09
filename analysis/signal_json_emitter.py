"""Standalone final signal JSON emitter.

Raw throttle and microboost logs are telemetry. ``[SignalJSON]`` is the
final signal product; ``[SignalWatchJSON]`` is a rate-limited lifecycle update
for watch states.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from analysis.microboost_followthrough_role import MICROBOOST_FOLLOWTHROUGH_ROLE_FIELDS
from analysis.signal_thresholds import SIGNAL_MIN_RR

TERMINAL_EXECUTION_READY_STATUSES = {
    "FINAL_EXECUTION_READY",
}

TERMINAL_VALID_SIGNAL_STATUSES = {
    "FINAL_VALID_WAIT_RETEST",
    "FINAL_VALID_WAIT_STRUCTURE_TARGET",
    "FINAL_VALID_MANAGEMENT_ONLY",
    "FINAL_VALID_EXECUTION_DEFERRED",
}

TERMINAL_INACTIVE_SIGNAL_STATUSES = {
    "FINAL_INVALIDATED",
    "FINAL_EXPIRED",
}

TERMINAL_SIGNAL_STATUSES = (
    TERMINAL_EXECUTION_READY_STATUSES | TERMINAL_VALID_SIGNAL_STATUSES | TERMINAL_INACTIVE_SIGNAL_STATUSES
)

TERMINAL_SIGNAL_PUBLIC_FIELDS = {
    "signal_valid",
    "direction_valid",
    "analysis_valid",
    "tradeplan_valid",
    "execution_valid_now",
    "execution_status",
    "execution_grade",
    "terminal_decision_confirmed",
    "terminal_decision_event_type",
    "terminal_status",
    "next_action",
}

EMITTABLE_SIGNAL_STATUSES = TERMINAL_SIGNAL_STATUSES | {
    "PAIR_SIGNAL_CANDIDATE",
    "CLEAN_BLOCK_BUY_WATCH",
    "CLEAN_BLOCK_SELL_WATCH",
    "CLEAN_BLOCK_WATCH_PENDING_CONTEXT",
    "CLEAN_BLOCK_WATCH_PENDING_DIRECTION",
    "CLEAN_BLOCK_WATCH_BLOCKED",
    "MICROBOOST_WATCH",
    "MICROBOOST_COUNTER_ENTRY_WATCH",
    "MICROBOOST_COUNTER_ENTRY_VALID",
    "NANO_ABSORPTION_SELL_WATCH",
    "EARLY_SELL_WATCH",
    "SELL_ABSORPTION_WATCH",
    "SELL_TIMING_WATCH",
    "SELL_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "SELL_TIMING_VALID",
    "NANO_ABSORPTION_BUY_WATCH",
    "EARLY_BUY_WATCH",
    "BUY_ABSORPTION_WATCH",
    "BUY_TIMING_WATCH",
    "BUY_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_ABSORPTION",
    "BUY_TIMING_VALID",
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "BUY_REVERSAL_VALID",
    "SELL_REVERSAL_VALID",
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
    "LATE_MICROBOOST_EXIT_ALERT",
    "PROTECT_PROFIT_ALERT",
    "THEME_SIGNAL_CANDIDATE",
    "WAIT_STRUCTURE_OR_NEXT_M15",
    "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET",
    "WAIT_M15_CLOSE_CONFIRMATION",
    "EXECUTION_READY",
    "PENDING_WATCH_EXPIRED",
    "NO_TRADE_REASONED",
}

VALID_SIGNAL_STATUSES = {
    "SELL_TIMING_VALID",
    "BUY_TIMING_VALID",
    "COUNTER_ENTRY_VALID",
    "MICROBOOST_COUNTER_ENTRY_VALID",
    "PAIR_SIGNAL_VALID",
    "BREAKOUT_RETEST_VALID",
    "PULLBACK_RECLAIM_VALID",
    "LATE_DENSE_EXIT_ALERT",
    "PROTECT_PROFIT_ALERT",
    "SELL_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "BUY_REVERSAL_VALID",
    "SELL_REVERSAL_VALID",
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
}

CONTINUATION_SIGNAL_STATUSES = {
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
}

CONDITIONAL_SIGNAL_STATUSES = {
    "SELL_ABSORPTION_WATCH",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "BUY_ABSORPTION_WATCH",
    "BUY_TIMING_VALID_BY_ABSORPTION",
}

WATCH_SIGNAL_STATUSES = {
    "CLEAN_BLOCK_BUY_WATCH",
    "CLEAN_BLOCK_SELL_WATCH",
    "CLEAN_BLOCK_WATCH_PENDING_CONTEXT",
    "CLEAN_BLOCK_WATCH_PENDING_DIRECTION",
    "CLEAN_BLOCK_WATCH_BLOCKED",
    "MICROBOOST_WATCH",
    "NANO_ABSORPTION_SELL_WATCH",
    "EARLY_SELL_WATCH",
    "SELL_TIMING_WATCH",
    "NANO_ABSORPTION_BUY_WATCH",
    "EARLY_BUY_WATCH",
    "BUY_TIMING_WATCH",
    "MICROBOOST_COUNTER_ENTRY_WATCH",
} | CONDITIONAL_SIGNAL_STATUSES

DECISION_UPDATE_STATUSES = {
    "WAIT_STRUCTURE_OR_NEXT_M15",
    "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET",
    "WAIT_M15_CLOSE_CONFIRMATION",
    "EXECUTION_READY",
    "PENDING_WATCH_EXPIRED",
    "NO_TRADE_REASONED",
}

PROVISIONAL_TARGET_ALLOWED_FINAL_STATUSES = CONTINUATION_SIGNAL_STATUSES | {
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
}

MIN_EXECUTABLE_TP1_RR = SIGNAL_MIN_RR
UNIVERSAL_PATTERN_SCHEMA_VERSION = "2.0-universal-pattern"

PAIR_REFERENCE_COMPAT_FIELDS = {
    "golden_reference",
    "golden_references",
    "pair_specific_calibration",
    "pair_role",
}

V11_OUTPUT_ONLY_FIELDS = {
    "signal_archetype",
    "counter_entry",
    "counter_entry_reason",
    "trend_following",
    "counter_entry_risk_multiplier",
    "theme_transition",
    "direction_valid",
    "source_valid_for_execution",
    "analysis_valid",
    "tradeplan_valid",
    "execution_valid_now",
    "execution_status",
    "execution_reason",
    "selected_sl_mode",
    "selected_sl",
    "risk_pips_safe",
    "selected_risk_pips",
    "target_policy",
    "targets",
    "structure_zones",
    "risk_reward",
    "invalidation_rules",
    "execution_quality",
    "phase_coherence",
    "signal_expiry",
    "signal_watch_source",
    "source_clean_block_confirmed",
    "source_clean_block_valid_since_utc",
    "microboost_validation_status",
    "source_target_mode",
    "parent_event_type",
    "parent_event_exists",
    "parent_watch_id",
    "parent_watch_required",
    "promotion_path",
    "promotion_trigger",
    "bypass_reason",
    "second_m15_confirmation",
    "reversal_confirmed",
    "cooldown_m15_bars_elapsed",
    "execution_grade",
    "audit_valid",
    "audit_block_reasons",
    "source_status",
    "source_final_direction",
    "decision_state",
    "terminal_decision_confirmed",
    "terminal_decision_id",
    "terminal_decision_event_type",
}

PATTERN_DEBUG_FIELDS = {
    "pattern_search_space",
    "pattern_db_candidates_scanned",
    "pattern_db_exact_matches",
    "pattern_db_fuzzy_matches",
    "pattern_match_diagnostics",
}

NESTED_SCHEMA_DUPLICATE_FIELDS = {
    "matched_patterns",
    "selected_pattern_id",
    "pattern_tier",
    "pattern_family",
    "pattern_score",
    "pattern_match_score",
    "execution_readiness_score",
    "pattern_scope",
    "applies_to",
    "entry_permission",
    "management_action",
    "hold_policy",
    "chase_allowed",
    "block_reason",
    "pattern_evidence",
    "pattern_bottlenecks",
    "theme_alignment",
    "jpy_alignment_status",
    "theme_alignment_status",
    "dual_theme_status",
    "alignment_missing_reason",
    "theme_context",
    "target_mode",
    "target_source",
    "tp_status",
    "tp_missing_reason",
    "support_ladder_ready",
    "resistance_ladder_ready",
    "structure_targets_available",
    "tradeplan_context_ready",
    "targets_execution_usable",
    "target_block_reason",
    "min_rr_required",
    "tp_min_rr",
    "tp_min_rr_value",
    "tp1_rr",
    "tp2_rr",
    "tp3_rr",
    "tp4_rr",
    "risk_pips",
    "pending_age_seconds",
    "decision_update_trigger",
    "next_action",
    "decision_watch_type",
}

STRUCTURE_TARGET_MODES = {
    "FINAL_MARKET_STRUCTURE",
    "STRUCTURE_LADDER_TARGET",
    "KEY_LEVEL_STRUCTURE_TARGET",
}


@dataclass(frozen=True)
class SignalJsonEvent:
    event: str
    schema_version: str
    symbol: str
    signal_family: str
    status: str
    raw_direction: str | None
    candidate_direction: str | None
    validated_direction: str | None
    final_direction: str
    action: str
    signal_valid_time_utc: str
    signal_valid_time_wita: str | None
    signal_valid_price: float
    entry_reference_price: float
    entry_zone: list[float]
    price_position: str | None
    m15_phase: str | None
    h1_phase: str | None
    phase_unpriced: str | None
    phase_priced: str | None
    effective_ticks: int | None
    effective_density: float | None
    duration_minutes: float | None
    sl_safe: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    tp4: float | None
    rr_to_tp1_tight: float | None
    rr_to_tp2_tight: float | None
    rr_to_tp3_tight: float | None
    rr_status: str
    market_context_applied: bool
    confidence_bucket: str | None
    reason: str
    invalidation: str | None
    watch_direction: str | None = None
    direction_validation_status: str | None = None
    cluster_id: str | None = None
    is_final_signal: bool = False
    emit_reason: str | None = None
    signal_quality: str | None = None
    lifecycle_version: int = 2
    target_mode: str | None = None
    target_source: str | None = None
    tp_status: str | None = None
    tp_missing_reason: str | None = None
    support_ladder_ready: bool | None = None
    resistance_ladder_ready: bool | None = None
    structure_targets_available: bool | None = None
    tradeplan_context_ready: bool | None = None
    targets_execution_usable: bool | None = None
    target_block_reason: str | None = None
    valid_for_execution: bool = False
    min_rr_required: float | None = None
    tp_min_rr: float | None = None
    tp_min_rr_value: float | None = None
    tp1_rr: float | None = None
    tp2_rr: float | None = None
    tp3_rr: float | None = None
    tp4_rr: float | None = None
    allowed_quorum: bool | None = None
    allowed_quorum_streak: int | None = None
    reclaim_trigger: float | None = None
    risk_pips: float | None = None
    signal_id: str | None = None
    linked_previous_signal: str | None = None
    previous_signal_status: str | None = None
    lifecycle_status: str | None = None
    active_signal: dict[str, Any] | None = None
    active_position_policy: str | None = None
    active_signal_management: dict[str, Any] | None = None
    previous_status: str | None = None
    new_status: str | None = None
    block_end_utc: str | None = None
    block_end_wita: str | None = None
    block_idle_seconds: float | None = None
    pending_age_seconds: float | None = None
    decision_update_trigger: str | None = None
    next_action: str | None = None
    confirmation_policy: str | None = None
    requires_m15_close: bool | None = None
    direct_valid_reason: str | None = None
    pending_decision_id: str | None = None
    price_delta_pips: float | None = None
    theme_alignment: str | None = None
    jpy_alignment_status: str | None = None
    theme_alignment_status: str | None = None
    dual_theme_status: str | None = None
    alignment_missing_reason: str | None = None
    structure_ready: bool | None = None
    rr_to_valid_target: float | None = None
    m15_confirmation_status: str | None = None
    breakout_reclaim_level: float | None = None
    support_reclaim_level: float | None = None
    decision_watch_type: str | None = None
    buy_condition: str | None = None
    sell_condition: str | None = None
    pullback_buy_zone: list[float] | None = None
    breakout_buy_zone: list[float] | None = None
    sell_rejection_zone: list[float] | None = None
    key_resistance: float | None = None
    key_support: float | None = None
    signal_archetype: str | None = None
    counter_entry: bool | None = None
    counter_entry_reason: str | None = None
    trend_following: bool | None = None
    counter_entry_risk_multiplier: float | None = None
    theme_transition: str | None = None
    signal_valid: bool = False
    terminal_status: str | None = None
    direction_valid: bool = False
    source_valid_for_execution: bool | None = None
    analysis_valid: bool = False
    tradeplan_valid: bool = False
    execution_valid_now: bool = False
    execution_status: str | None = None
    execution_reason: str | None = None
    selected_sl_mode: str | None = None
    selected_sl: float | None = None
    risk_pips_safe: float | None = None
    selected_risk_pips: float | None = None
    target_policy: dict[str, Any] | None = None
    targets: list[dict[str, Any]] | None = None
    structure_zones: dict[str, Any] | None = None
    risk_reward: dict[str, Any] | None = None
    invalidation_rules: dict[str, Any] | None = None
    execution_quality: dict[str, Any] | None = None
    phase_coherence: dict[str, Any] | None = None
    signal_expiry: dict[str, Any] | None = None
    signal_watch_source: str | None = None
    source_clean_block_confirmed: bool | None = None
    source_clean_block_valid_since_utc: str | None = None
    source_clean_block_id: str | None = None
    source_pressure_block_id: str | None = None
    clean_block_valid: bool | None = None
    clean_block_start_utc: str | None = None
    clean_block_end_utc: str | None = None
    clean_block_duration_seconds: float | None = None
    clean_block_event_count: int | None = None
    clean_block_direction: str | None = None
    watch_promotion_source: str | None = None
    microboost_validation_status: str | None = None
    microboost_role: str | None = None
    microboost_followthrough_bias: str | None = None
    microboost_room_to_move_pips: float | None = None
    microboost_pre_move_pips: float | None = None
    microboost_late_move_penalty: float | None = None
    microboost_followthrough_context_ready: bool | None = None
    microboost_price_behavior: str | None = None
    microboost_room_to_move_status: str | None = None
    microboost_stall_pips: float | None = None
    microboost_room_to_target_pips: float | None = None
    microboost_expected_horizon: str | None = None
    microboost_outcome_tracking_required: bool | None = None
    microboost_role_source_event: str | None = None
    microboost_role_reason_codes: list[str] | None = None
    microboost_role_valid_for_execution: bool | None = None
    microboost_role_execution_impact: bool | None = None
    microboost_role_advisory_only: bool | None = None
    source_target_mode: str | None = None
    parent_event_type: str | None = None
    parent_event_exists: bool | None = None
    parent_watch_id: str | None = None
    parent_watch_required: bool | None = None
    promotion_path: str | None = None
    promotion_trigger: str | None = None
    bypass_reason: str | None = None
    second_m15_confirmation: bool | None = None
    reversal_confirmed: bool | None = None
    cooldown_m15_bars_elapsed: int | None = None
    execution_grade: str | None = None
    audit_valid: bool | None = None
    audit_block_reasons: list[str] | None = None
    source_status: str | None = None
    source_final_direction: str | None = None
    decision_state: str | None = None
    terminal_decision_confirmed: bool | None = None
    terminal_decision_id: str | None = None
    terminal_decision_event_type: str | None = None
    matched_patterns: list[str] | None = None
    selected_pattern_id: str | None = None
    pattern_tier: str | None = None
    pattern_family: str | None = None
    pattern_score: int | None = None
    pattern_match_score: int | None = None
    execution_readiness_score: int | None = None
    golden_reference: str | None = None
    pattern_scope: str | None = None
    applies_to: str | None = None
    golden_references: list[str] | None = None
    pair_specific_calibration: list[str] | None = None
    pair_role: str | None = None
    entry_permission: str | None = None
    management_action: str | None = None
    hold_policy: str | None = None
    chase_allowed: bool | None = None
    block_reason: str | None = None
    pattern_evidence: list[str] | None = None
    pattern_search_space: list[str] | None = None
    pattern_db_candidates_scanned: int | None = None
    pattern_db_exact_matches: list[str] | None = None
    pattern_db_fuzzy_matches: list[str] | None = None
    pattern_bottlenecks: list[str] | None = None
    pattern_match_diagnostics: dict[str, Any] | None = None
    reference_cases: list[dict[str, Any]] | None = None
    pair_calibration: dict[str, Any] | None = None
    pattern_context: dict[str, Any] | None = None
    theme_context: dict[str, Any] | None = None
    tradeplan_preview: dict[str, Any] | None = None
    market_structure: dict[str, Any] | None = None
    execution_gate: dict[str, Any] | None = None
    lifecycle: dict[str, Any] | None = None
    pressure_priority_context: dict[str, Any] | None = None
    followthrough_context: dict[str, Any] | None = None
    # Family lineage (gated upstream by SIGNAL_FAMILY_LINEAGE_ENABLED). Carried through
    # so the lineage merged onto the pipeline payload actually reaches the emitted log
    # instead of being dropped by the dict->event rebuild. Observability-only.
    source_family: str | None = None
    source_stage: str | None = None
    resolved_family: str | None = None
    family_lineage_reason: str | None = None
    # Explain why a throttle candidate stopped at DecisionUpdate instead of
    # being promoted to SignalWatchJSON or final SignalJSON.
    pressure_seen: bool | None = None
    allowed_quorum_seen: bool | None = None
    pair_eligible_for_analysis: bool | None = None
    pressure_event_count: int | None = None
    pressure_level: str | None = None
    pressure_strength: str | None = None
    pressure_source: str | None = None
    source_verdict: str | None = None
    execution_block_reason: str | None = None
    watch_promotion_blockers: dict[str, Any] | None = None
    microboost_detected: bool | None = None
    allowed_quorum_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalJsonEmitter:
    def __init__(
        self,
        *,
        enabled: bool = True,
        prefix: str = "[SignalJSON]",
        watch_prefix: str = "[SignalWatchJSON]",
        decision_update_prefix: str = "[SignalDecisionUpdateJSON]",
        dedup_ttl_seconds: int = 300,
        emit_watch: bool = False,
        emit_conditional: bool = True,
        emit_valid: bool = True,
        require_market_context: bool = True,
        watch_transition_only: bool = True,
        watch_update_interval_seconds: float = 15.0,
        strict_lifecycle: bool = False,
        require_parent_watch: bool = False,
        allow_direct_bypass: bool = True,
        require_final_market_structure: bool = False,
        require_theme_alignment: bool = True,
        theme_conflict_downgrade: bool = True,
        min_rr_valid: float = SIGNAL_MIN_RR,
        cooldown_m15_bars_after_active_signal: int = 1,
        decision_dedup_enabled: bool = True,
        decision_state_monotonic: bool = True,
        require_terminal_decision_update: bool = True,
        compact_production: bool = True,
        emit_pattern_debug: bool | None = None,
        pattern_debug_prefix: str = "[PatternMatchDebugJSON]",
    ) -> None:
        self.enabled = enabled
        self.prefix = prefix
        self.watch_prefix = watch_prefix
        self.decision_update_prefix = decision_update_prefix
        self.pattern_debug_prefix = pattern_debug_prefix
        self.dedup_ttl_seconds = max(1, int(dedup_ttl_seconds))
        self.emit_watch = emit_watch
        self.emit_conditional = emit_conditional
        self.emit_valid = emit_valid
        self.require_market_context = require_market_context
        self.watch_transition_only = watch_transition_only
        self.watch_update_interval_seconds = max(0.0, float(watch_update_interval_seconds))
        self.strict_lifecycle = strict_lifecycle
        self.require_parent_watch = require_parent_watch
        self.allow_direct_bypass = allow_direct_bypass
        self.require_final_market_structure = require_final_market_structure
        self.require_theme_alignment = require_theme_alignment
        self.theme_conflict_downgrade = theme_conflict_downgrade
        self.min_rr_valid = float(min_rr_valid)
        self.cooldown_m15_bars_after_active_signal = max(0, int(cooldown_m15_bars_after_active_signal))
        self.decision_dedup_enabled = decision_dedup_enabled
        self.decision_state_monotonic = decision_state_monotonic
        self.require_terminal_decision_update = require_terminal_decision_update
        self.compact_production = compact_production
        self.emit_pattern_debug = (
            emit_pattern_debug
            if emit_pattern_debug is not None
            else os.getenv("SIGNAL_JSON_PATTERN_DEBUG_ENABLED", "false").strip().lower() == "true"
        )
        self._emitted: dict[str, float] = {}
        self._cluster_state: dict[str, str] = {}
        self._cluster_watch_event_seconds: dict[str, float] = {}
        self._cluster_watch_wall_seconds: dict[str, float] = {}
        self._cluster_watch_revisions: dict[str, int] = {}
        self._emitted_watch_refs: set[str] = set()
        self._last_watch_content: dict[str, str] = {}
        self._cluster_semantic_watch: dict[str, float] = {}
        self._terminal_decisions: set[str] = set()
        self._decision_states: dict[str, str] = {}
        self._finalized_decisions: set[str] = set()
        self.logger = logging.getLogger("signal_json")

    def emit(self, event: SignalJsonEvent) -> bool:
        if not self.enabled:
            return False
        payload = event.to_dict()
        if _is_terminal_non_execution_status(str(payload.get("status") or "")):
            payload = _terminal_non_execution_as_decision_update(payload)
        is_decision_update = _is_decision_update_payload(payload) or _is_decision_update_event(event)
        is_watch = _is_watch_status(str(payload.get("status") or "")) and not is_decision_update
        watch_revision: str | None = None
        if is_watch and self.watch_transition_only:
            watch_revision = self._mark_watch_transition(event)
            if watch_revision is None:
                return False
        final_block_reasons = _final_execution_block_reasons(payload)
        if final_block_reasons:
            payload = _blocked_final_as_decision_update(payload, final_block_reasons)
        elif self.strict_lifecycle and _is_final_payload(payload):
            if self._ensure_terminal_decision_update(payload):
                payload = self._strict_final_payload(payload)
            else:
                payload = _blocked_final_as_decision_update(payload, ["MISSING_TERMINAL_DECISION_UPDATE"])

        is_decision_update = _is_decision_update_payload(payload)
        is_watch = _is_watch_status(str(payload.get("status") or "")) and not is_decision_update
        if not is_watch:
            _strip_pressure_priority_fields(payload)
            _strip_followthrough_fields(payload)
            _strip_microboost_role_fields(payload)
        else:
            _apply_signal_watch_pressure_tier_fields(payload)
            _apply_signal_watch_followthrough_fields(payload)
            _apply_signal_watch_microboost_role_fields(payload)
        if not should_emit_signal_json(
            payload,
            emit_watch=self.emit_watch,
            emit_conditional=self.emit_conditional,
            emit_valid=self.emit_valid,
            require_market_context=self.require_market_context,
        ):
            return False

        # Increment B (flag default OFF): suppress identical watch re-emits for the
        # same cluster. The transition logic already rate-limits, but it still
        # re-emits an unchanged watch every watch_update_interval; this collapses
        # byte-identical content (symbol|family|status|reason|direction|price) until
        # something materially changes. Enable: SIGNAL_WATCH_SUPPRESS_IDENTICAL=true.
        if is_watch and os.getenv("SIGNAL_WATCH_SUPPRESS_IDENTICAL", "false").strip().lower() == "true":
            content_cluster = str(payload.get("cluster_id") or payload.get("symbol") or "")
            content_key = (
                f"{payload.get('symbol')}|{payload.get('signal_family')}|{payload.get('status')}|"
                f"{payload.get('reason')}|{payload.get('final_direction')}|"
                f"{payload.get('watch_direction')}|{payload.get('entry_reference_price')}"
            )
            if self._last_watch_content.get(content_cluster) == content_key:
                return False
            self._last_watch_content[content_cluster] = content_key

        # Increment E (flag default OFF): collapse repeated watches for the same cluster
        # by their MATERIAL fields only -- ignoring price/timestamp/density noise that
        # Increment B's byte-identical check does NOT ignore (the 28x GBPCHF spam slipped
        # through B because each tick carried a slightly different price). Suppresses only
        # the duplicate EMIT; the first watch + any material change always pass, and
        # finalizer lifecycle tracking is untouched. Enable: SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED=true.
        if (
            is_watch
            and os.getenv("SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED", "false").strip().lower() == "true"
            and self._is_cluster_watch_duplicate(payload)
        ):
            return False

        key = self._payload_key(payload, watch_revision=watch_revision)
        if self._is_duplicate(key):
            return False

        payload["event"] = (
            "signal_decision_update_json"
            if is_decision_update
            else ("signal_watch_json" if is_watch else "signal_json")
        )
        payload["is_final_signal"] = bool(payload.get("is_final_signal") or _is_final_payload(payload))
        payload["emit_reason"] = payload.get("emit_reason") or _emit_reason(event.status)
        payload["signal_quality"] = payload.get("signal_quality") or _signal_quality(payload)
        debug_source_payload = dict(payload)
        payload = _universal_pattern_payload(payload, compact=self.compact_production)
        if self.emit_pattern_debug:
            self._emit_pattern_debug(debug_source_payload, payload)
        prefix = self.decision_update_prefix if is_decision_update else (self.watch_prefix if is_watch else self.prefix)
        self.logger.warning("%s %s", prefix, json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        if is_watch:
            self._emitted_watch_refs.update(_watch_references(payload))
        if is_decision_update:
            self._record_decision_state(payload)
        return True

    def _emit_pattern_debug(self, source_payload: dict[str, Any], production_payload: dict[str, Any]) -> None:
        sidecar = _pattern_debug_payload(source_payload, production_payload)
        if sidecar is None:
            return
        self.logger.warning(
            "%s %s",
            self.pattern_debug_prefix,
            json.dumps(sidecar, separators=(",", ":"), ensure_ascii=False),
        )

    @staticmethod
    def _payload_key(payload: dict[str, Any], *, watch_revision: str | None = None) -> str:
        cluster_key = payload.get("cluster_id") or payload.get("signal_valid_time_utc")
        if _is_decision_update_payload(payload):
            return (
                f"{payload.get('pending_decision_id') or payload.get('symbol')}|decision|{payload.get('status')}|"
                f"{payload.get('m15_confirmation_status') or ''}|{payload.get('action') or ''}|"
                f"{payload.get('next_action') or ''}|{payload.get('lifecycle_status') or ''}|"
                f"{payload.get('terminal_status') or ''}|{payload.get('source_status') or ''}|"
                f"{payload.get('source_final_direction') or ''}|{payload.get('target_mode') or ''}|"
                f"{payload.get('tp_missing_reason') or ''}|{payload.get('target_block_reason') or ''}|"
                f"{payload.get('execution_status') or ''}|{payload.get('execution_reason') or ''}"
            )
        if _is_watch_status(str(payload.get("status") or "")):
            revision_key = watch_revision or _watch_payload_revision(payload)
            return (
                f"{payload.get('symbol')}|{cluster_key}|{payload.get('signal_family')}|"
                f"{payload.get('status')}|{payload.get('target_mode') or ''}|{revision_key}"
            )
        signal_id = _optional_str(payload.get("signal_id"))
        if signal_id is not None:
            return (
                f"{signal_id}|{payload.get('event') or 'signal_json'}|{payload.get('status')}|"
                f"{payload.get('pending_decision_id') or ''}"
            )
        return (
            f"{payload.get('symbol')}|{cluster_key}|{payload.get('signal_family')}|"
            f"{payload.get('final_direction')}|{payload.get('entry_reference_price')}"
        )

    def _strict_final_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        parent_watch_id = _matched_watch_reference(payload, self._emitted_watch_refs)
        has_parent = parent_watch_id is not None
        has_bypass = self._valid_direct_bypass(payload)
        reasons: list[str] = []
        pending_id = _optional_str(payload.get("pending_decision_id"))
        source_target_mode = str(payload.get("source_target_mode") or payload.get("target_mode") or "").upper()

        if self.require_parent_watch and not has_parent and not has_bypass:
            reasons.append("MISSING_PARENT_WATCH_OR_APPROVED_BYPASS")
        if (
            self.require_terminal_decision_update
            and not has_bypass
            and (pending_id is None or f"pending:{pending_id}" not in self._emitted_watch_refs)
        ):
            reasons.append("MISSING_PARENT_WATCH_DECISION_ID_MATCH")
        if pending_id is not None and self._decision_states.get(pending_id) == "EXPIRED":
            reasons.append("PENDING_DECISION_ALREADY_EXPIRED")
        if source_target_mode == "PROVISIONAL_RR_FALLBACK":
            reasons.append("PROVISIONAL_RR_NOT_EXECUTION_GRADE")
        if self.require_final_market_structure and not _is_structure_target_mode(payload.get("target_mode")):
            reasons.append("STRUCTURE_TARGET_MODE_REQUIRED")
        if _active_signal_conflicts(payload):
            if _optional_bool(payload.get("reversal_confirmed")) is not True:
                reasons.append("ACTIVE_SIGNAL_CONFLICT_REQUIRES_REVERSAL_CONFIRMATION")
            elapsed = _optional_int(payload.get("cooldown_m15_bars_elapsed")) or 0
            if elapsed < self.cooldown_m15_bars_after_active_signal:
                reasons.append("ACTIVE_SIGNAL_CONFLICT_COOLDOWN_REQUIRED")
        if not _execution_contract_complete(payload):
            reasons.append("EXECUTION_CONTRACT_INCOMPLETE")
        valid_rr = _optional_float(payload.get("rr_to_valid_target") or payload.get("tp_min_rr_value"))
        if valid_rr is not None and valid_rr < self.min_rr_valid:
            reasons.append("RR_BELOW_MINIMUM")

        payload["parent_event_type"] = "signal_watch_json" if has_parent else None
        payload["parent_event_exists"] = has_parent
        payload["parent_watch_id"] = parent_watch_id
        payload["parent_watch_required"] = False if has_bypass else self.require_parent_watch
        if has_parent:
            payload["promotion_path"] = "WATCH_TO_FINAL"
        elif has_bypass:
            payload["promotion_path"] = "DIRECT_BYPASS"
        if not reasons:
            payload["execution_grade"] = "FINAL_STRUCTURE"
            payload["audit_valid"] = True
            payload["audit_block_reasons"] = []
            return payload
        return _blocked_final_as_decision_update(payload, reasons)

    def _valid_direct_bypass(self, payload: dict[str, Any]) -> bool:
        return bool(
            self.allow_direct_bypass
            and str(payload.get("promotion_path") or "").upper() == "DIRECT_BYPASS"
            and _optional_str(payload.get("bypass_reason"))
            and _optional_bool(payload.get("parent_watch_required")) is False
        )

    def _ensure_terminal_decision_update(self, payload: dict[str, Any]) -> bool:
        if (
            not self.require_terminal_decision_update
            or str(payload.get("promotion_path") or "").upper() == "DIRECT_BYPASS"
        ):
            return True
        pending_id = _optional_str(payload.get("pending_decision_id"))
        if pending_id is None:
            return False
        if self._decision_states.get(pending_id) == "EXECUTION_READY":
            payload["decision_state"] = "EXECUTION_READY"
            payload["terminal_decision_confirmed"] = True
            payload["terminal_decision_id"] = pending_id
            payload["terminal_decision_event_type"] = "signal_decision_update_json"
            return True

        update = _execution_ready_decision_update(payload)
        self.logger.warning(
            "%s %s",
            self.decision_update_prefix,
            json.dumps(update, separators=(",", ":"), ensure_ascii=False),
        )
        self._record_decision_state(update)
        payload["decision_state"] = "EXECUTION_READY"
        payload["terminal_decision_confirmed"] = True
        payload["terminal_decision_id"] = pending_id
        payload["terminal_decision_event_type"] = "signal_decision_update_json"
        return True

    def _record_decision_state(self, payload: dict[str, Any]) -> None:
        pending_id = _optional_str(payload.get("pending_decision_id"))
        if pending_id is None:
            return
        status = str(payload.get("status") or "").upper()
        state = str(payload.get("decision_state") or "").upper()
        if status == "EXECUTION_READY" or state == "EXECUTION_READY":
            self._decision_states[pending_id] = "EXECUTION_READY"
            self._terminal_decisions.add(pending_id)
        elif status == "PENDING_WATCH_EXPIRED":
            self._decision_states[pending_id] = "EXPIRED"
            self._terminal_decisions.add(pending_id)
        elif pending_id not in self._terminal_decisions:
            self._decision_states[pending_id] = "WAITING"

    def _decision_transition_allowed(self, payload: dict[str, Any]) -> bool:
        if not self.decision_dedup_enabled and not self.decision_state_monotonic:
            return True
        pending_id = _optional_str(payload.get("pending_decision_id"))
        if pending_id is None:
            return True
        return not (self.decision_state_monotonic and pending_id in self._terminal_decisions)

    def _mark_watch_transition(self, event: SignalJsonEvent) -> str | None:
        cluster_key = event.cluster_id or f"{event.symbol}|{event.signal_family}|{event.entry_reference_price}"
        state = _watch_transition_state(event)
        now = time.time()
        event_seconds = _signal_time_epoch_seconds(event.signal_valid_time_utc)
        previous = self._cluster_state.get(cluster_key)
        if previous == state:
            previous_event_seconds = self._cluster_watch_event_seconds.get(cluster_key)
            previous_wall_seconds = self._cluster_watch_wall_seconds.get(cluster_key)
            event_elapsed = (
                event_seconds - previous_event_seconds
                if event_seconds is not None and previous_event_seconds is not None
                else 0.0
            )
            wall_elapsed = now - previous_wall_seconds if previous_wall_seconds is not None else 0.0
            if max(event_elapsed, wall_elapsed) < self.watch_update_interval_seconds:
                return None

        revision = self._cluster_watch_revisions.get(cluster_key, 0) + 1
        self._cluster_state[cluster_key] = state
        if event_seconds is not None:
            self._cluster_watch_event_seconds[cluster_key] = event_seconds
        self._cluster_watch_wall_seconds[cluster_key] = now
        self._cluster_watch_revisions[cluster_key] = revision
        return f"{revision}|{state}"

    def _is_duplicate(self, key: str) -> bool:
        now = time.time()
        expired_keys = [old_key for old_key, ts in self._emitted.items() if now - ts > self.dedup_ttl_seconds]
        for old_key in expired_keys:
            self._emitted.pop(old_key, None)

        if key in self._emitted:
            return True
        self._emitted[key] = now
        return False

    def _cluster_semantic_watch_key(self, payload: dict[str, Any]) -> str:
        """Material-only identity for a cluster watch (Increment E). Deliberately omits
        price / timestamp / density so identical scenarios collapse, while any change to
        status, direction, price_position or valid_for_execution yields a new key.
        """
        return "|".join(
            str(payload.get(field) or "")
            for field in (
                "symbol",
                "cluster_id",
                "signal_family",
                "resolved_family",
                "status",
                "raw_direction",
                "candidate_direction",
                "watch_direction",
                "price_position",
                "valid_for_execution",
                "reason",
            )
        )

    def _is_cluster_watch_duplicate(self, payload: dict[str, Any]) -> bool:
        """Return True when this cluster watch is a material-duplicate of one already
        emitted within ``dedup_ttl_seconds``. The first watch and any material change
        always return False (emit); the timestamp is NOT refreshed on a hit, so once the
        TTL window lapses a fresh watch is allowed again.
        """
        now = time.time()
        expired = [k for k, ts in self._cluster_semantic_watch.items() if now - ts > self.dedup_ttl_seconds]
        for k in expired:
            self._cluster_semantic_watch.pop(k, None)
        key = self._cluster_semantic_watch_key(payload)
        if key in self._cluster_semantic_watch:
            return True
        self._cluster_semantic_watch[key] = now
        return False


def build_signal_json_event(counter_entry: dict[str, Any] | None) -> SignalJsonEvent | None:
    if not isinstance(counter_entry, dict):
        return None
    signal_valid_time = _optional_str(
        counter_entry.get("signal_valid_time_utc") or counter_entry.get("signal_valid_time")
    )
    signal_valid_price = _optional_float(counter_entry.get("signal_valid_price"))
    entry_reference_price = _optional_float(counter_entry.get("entry_reference_price"))
    entry_zone = _float_list(counter_entry.get("entry_zone"))
    symbol = str(counter_entry.get("symbol") or "").upper()
    status = str(counter_entry.get("status") or "")
    if (
        not signal_valid_time
        or signal_valid_price is None
        or entry_reference_price is None
        or not entry_zone
        or not symbol
    ):
        return None
    is_decision_update = _is_decision_update_payload(counter_entry)
    is_watch = _is_watch_status(status) and not is_decision_update
    allowed_quorum_raw = counter_entry.get("allowed_quorum")
    allowed_quorum_context = _dict_value(allowed_quorum_raw)
    validated_direction = _validated_direction(counter_entry)
    watch_direction = _watch_direction(counter_entry, status=status, validated_direction=validated_direction)
    return SignalJsonEvent(
        event="signal_decision_update_json"
        if is_decision_update
        else ("signal_watch_json" if is_watch else "signal_json"),
        schema_version=UNIVERSAL_PATTERN_SCHEMA_VERSION,
        symbol=symbol,
        signal_family=str(
            counter_entry.get("signal_family") or counter_entry.get("signal_type") or "MICROBOOST_COUNTER_ENTRY"
        ),
        source_family=_optional_str(counter_entry.get("source_family")),
        source_stage=_optional_str(counter_entry.get("source_stage")),
        resolved_family=_optional_str(counter_entry.get("resolved_family")),
        family_lineage_reason=_optional_str(counter_entry.get("family_lineage_reason")),
        pressure_seen=_optional_bool(counter_entry.get("pressure_seen")),
        allowed_quorum_seen=_optional_bool(counter_entry.get("allowed_quorum_seen")),
        pair_eligible_for_analysis=_optional_bool(counter_entry.get("pair_eligible_for_analysis")),
        pressure_event_count=_optional_int(counter_entry.get("pressure_event_count")),
        pressure_level=_optional_str(counter_entry.get("pressure_level")),
        pressure_strength=_optional_str(counter_entry.get("pressure_strength")),
        pressure_source=_optional_str(counter_entry.get("pressure_source")),
        source_verdict=_optional_str(counter_entry.get("source_verdict")),
        execution_block_reason=_optional_str(counter_entry.get("execution_block_reason")),
        watch_promotion_blockers=_dict_value(counter_entry.get("watch_promotion_blockers")),
        microboost_detected=_optional_bool(counter_entry.get("microboost_detected")),
        allowed_quorum_context=allowed_quorum_context,
        status=status,
        cluster_id=_optional_str(counter_entry.get("cluster_id")),
        is_final_signal=bool(counter_entry.get("is_final_signal", False)) or _is_final_payload(counter_entry),
        emit_reason=_optional_str(counter_entry.get("emit_reason")) or _emit_reason(status),
        signal_quality=_optional_str(counter_entry.get("signal_quality")) or _signal_quality(counter_entry),
        raw_direction=_optional_str(counter_entry.get("raw_direction")),
        candidate_direction=_optional_str(counter_entry.get("candidate_direction")),
        validated_direction=validated_direction,
        watch_direction=watch_direction,
        direction_validation_status=_optional_str(counter_entry.get("direction_validation_status"))
        or _direction_validation_status(counter_entry, status=status, validated_direction=validated_direction),
        final_direction=str(counter_entry.get("final_direction") or "WAIT"),
        action=str(counter_entry.get("action") or "WAIT"),
        signal_valid_time_utc=signal_valid_time,
        signal_valid_time_wita=_optional_str(counter_entry.get("signal_valid_time_wita")),
        signal_valid_price=signal_valid_price,
        entry_reference_price=entry_reference_price,
        entry_zone=entry_zone,
        price_position=_optional_str(counter_entry.get("price_position")),
        m15_phase=_optional_str(counter_entry.get("m15_phase")),
        h1_phase=_optional_str(counter_entry.get("h1_phase")),
        phase_unpriced=_optional_str(counter_entry.get("phase_unpriced")),
        phase_priced=_optional_str(counter_entry.get("phase_priced")),
        effective_ticks=_optional_int(counter_entry.get("effective_ticks")),
        effective_density=_optional_float(counter_entry.get("effective_density")),
        duration_minutes=_optional_float(counter_entry.get("duration_minutes")),
        sl_safe=_optional_float(counter_entry.get("sl_safe")),
        tp1=_optional_float(counter_entry.get("tp1")),
        tp2=_optional_float(counter_entry.get("tp2")),
        tp3=_optional_float(counter_entry.get("tp3")),
        tp4=_optional_float(counter_entry.get("tp4")),
        rr_to_tp1_tight=_optional_float(counter_entry.get("rr_to_tp1_tight")),
        rr_to_tp2_tight=_optional_float(counter_entry.get("rr_to_tp2_tight")),
        rr_to_tp3_tight=_optional_float(counter_entry.get("rr_to_tp3_tight")),
        rr_status=str(counter_entry.get("rr_status") or "UNVALIDATED"),
        market_context_applied=bool(counter_entry.get("market_context_applied", False)),
        confidence_bucket=_optional_str(counter_entry.get("confidence_bucket")),
        reason=str(counter_entry.get("reason") or "signal_json_candidate"),
        invalidation=_optional_str(counter_entry.get("invalidation")),
        target_mode=_optional_str(counter_entry.get("target_mode")),
        target_source=_optional_str(counter_entry.get("target_source")),
        tp_status=_optional_str(counter_entry.get("tp_status")),
        tp_missing_reason=_optional_str(counter_entry.get("tp_missing_reason")),
        support_ladder_ready=_optional_bool(counter_entry.get("support_ladder_ready")),
        resistance_ladder_ready=_optional_bool(counter_entry.get("resistance_ladder_ready")),
        structure_targets_available=_optional_bool(counter_entry.get("structure_targets_available")),
        tradeplan_context_ready=_optional_bool(counter_entry.get("tradeplan_context_ready")),
        targets_execution_usable=_optional_bool(counter_entry.get("targets_execution_usable")),
        target_block_reason=_optional_str(counter_entry.get("target_block_reason")),
        valid_for_execution=bool(counter_entry.get("valid_for_execution", False)),
        min_rr_required=_optional_float(counter_entry.get("min_rr_required")),
        tp_min_rr=_optional_float(counter_entry.get("tp_min_rr")),
        tp_min_rr_value=_optional_float(counter_entry.get("tp_min_rr_value")),
        tp1_rr=_optional_float(counter_entry.get("tp1_rr")),
        tp2_rr=_optional_float(counter_entry.get("tp2_rr")),
        tp3_rr=_optional_float(counter_entry.get("tp3_rr")),
        tp4_rr=_optional_float(counter_entry.get("tp4_rr")),
        allowed_quorum=(
            _optional_bool(allowed_quorum_context.get("quorum_reached"))
            if allowed_quorum_context is not None
            else _optional_bool(allowed_quorum_raw)
        ),
        allowed_quorum_streak=_optional_int(
            counter_entry.get("allowed_quorum_streak")
            or (allowed_quorum_context or {}).get("streak")
        ),
        reclaim_trigger=_optional_float(counter_entry.get("reclaim_trigger")),
        risk_pips=_optional_float(counter_entry.get("risk_pips")),
        signal_id=_optional_str(counter_entry.get("signal_id"))
        or _generated_signal_id(
            symbol=symbol,
            direction=validated_direction or watch_direction or _optional_str(counter_entry.get("candidate_direction")),
            status=status,
            signal_time=signal_valid_time,
            is_watch=is_watch,
            is_decision_update=is_decision_update,
        ),
        linked_previous_signal=_optional_str(counter_entry.get("linked_previous_signal")),
        previous_signal_status=_optional_str(counter_entry.get("previous_signal_status")),
        lifecycle_status=_optional_str(counter_entry.get("lifecycle_status")),
        active_signal=counter_entry.get("active_signal")
        if isinstance(counter_entry.get("active_signal"), dict)
        else None,
        active_position_policy=_optional_str(counter_entry.get("active_position_policy")),
        active_signal_management=_dict_value(counter_entry.get("active_signal_management")),
        previous_status=_optional_str(counter_entry.get("previous_status")),
        new_status=_optional_str(counter_entry.get("new_status")),
        block_end_utc=_optional_str(counter_entry.get("block_end_utc")),
        block_end_wita=_optional_str(counter_entry.get("block_end_wita")),
        block_idle_seconds=_optional_float(counter_entry.get("block_idle_seconds")),
        pending_age_seconds=_optional_float(counter_entry.get("pending_age_seconds")),
        decision_update_trigger=_optional_str(counter_entry.get("decision_update_trigger")),
        next_action=_optional_str(counter_entry.get("next_action")),
        confirmation_policy=_optional_str(counter_entry.get("confirmation_policy")),
        requires_m15_close=_optional_bool(counter_entry.get("requires_m15_close")),
        direct_valid_reason=_optional_str(counter_entry.get("direct_valid_reason")),
        pending_decision_id=_optional_str(counter_entry.get("pending_decision_id")),
        price_delta_pips=_optional_float(counter_entry.get("price_delta_pips")),
        theme_alignment=_optional_str(counter_entry.get("theme_alignment")),
        jpy_alignment_status=_optional_str(counter_entry.get("jpy_alignment_status")),
        theme_alignment_status=_theme_alignment_status(counter_entry),
        dual_theme_status=_optional_str(counter_entry.get("dual_theme_status")),
        alignment_missing_reason=_alignment_missing_reason(counter_entry),
        structure_ready=_optional_bool(counter_entry.get("structure_ready")),
        rr_to_valid_target=_optional_float(counter_entry.get("rr_to_valid_target")),
        m15_confirmation_status=_optional_str(counter_entry.get("m15_confirmation_status")),
        breakout_reclaim_level=_optional_float(counter_entry.get("breakout_reclaim_level")),
        support_reclaim_level=_optional_float(counter_entry.get("support_reclaim_level")),
        decision_watch_type=_optional_str(counter_entry.get("decision_watch_type")),
        buy_condition=_optional_str(counter_entry.get("buy_condition")),
        sell_condition=_optional_str(counter_entry.get("sell_condition")),
        pullback_buy_zone=_float_list(counter_entry.get("pullback_buy_zone")) or None,
        breakout_buy_zone=_float_list(counter_entry.get("breakout_buy_zone")) or None,
        sell_rejection_zone=_float_list(counter_entry.get("sell_rejection_zone")) or None,
        key_resistance=_optional_float(counter_entry.get("key_resistance")),
        key_support=_optional_float(counter_entry.get("key_support")),
        signal_archetype=_optional_str(counter_entry.get("signal_archetype")),
        counter_entry=_optional_bool(counter_entry.get("counter_entry")),
        counter_entry_reason=_optional_str(counter_entry.get("counter_entry_reason")),
        trend_following=_optional_bool(counter_entry.get("trend_following")),
        counter_entry_risk_multiplier=_optional_float(counter_entry.get("counter_entry_risk_multiplier")),
        theme_transition=_optional_str(counter_entry.get("theme_transition")),
        signal_valid=bool(counter_entry.get("signal_valid", False)),
        terminal_status=_optional_str(counter_entry.get("terminal_status")),
        direction_valid=bool(counter_entry.get("direction_valid", False)),
        source_valid_for_execution=_optional_bool(counter_entry.get("source_valid_for_execution")),
        analysis_valid=bool(counter_entry.get("analysis_valid", False)),
        tradeplan_valid=bool(counter_entry.get("tradeplan_valid", False)),
        execution_valid_now=bool(counter_entry.get("execution_valid_now", False)),
        execution_status=_optional_str(counter_entry.get("execution_status")),
        execution_reason=_optional_str(counter_entry.get("execution_reason")),
        selected_sl_mode=_optional_str(counter_entry.get("selected_sl_mode")),
        selected_sl=_optional_float(counter_entry.get("selected_sl")),
        risk_pips_safe=_optional_float(counter_entry.get("risk_pips_safe")),
        selected_risk_pips=_optional_float(counter_entry.get("selected_risk_pips")),
        target_policy=_dict_value(counter_entry.get("target_policy")),
        targets=_dict_list(counter_entry.get("targets")),
        structure_zones=_dict_value(counter_entry.get("structure_zones")),
        risk_reward=_dict_value(counter_entry.get("risk_reward")),
        invalidation_rules=_dict_value(counter_entry.get("invalidation_rules")),
        execution_quality=_dict_value(counter_entry.get("execution_quality")),
        phase_coherence=_dict_value(counter_entry.get("phase_coherence")),
        signal_expiry=_dict_value(counter_entry.get("signal_expiry")),
        signal_watch_source=_optional_str(counter_entry.get("signal_watch_source")),
        source_clean_block_confirmed=_optional_bool(counter_entry.get("source_clean_block_confirmed")),
        source_clean_block_valid_since_utc=_optional_str(counter_entry.get("source_clean_block_valid_since_utc")),
        source_clean_block_id=_optional_str(counter_entry.get("source_clean_block_id")),
        source_pressure_block_id=_optional_str(counter_entry.get("source_pressure_block_id")),
        clean_block_valid=_optional_bool(counter_entry.get("clean_block_valid")),
        clean_block_start_utc=_optional_str(counter_entry.get("clean_block_start_utc")),
        clean_block_end_utc=_optional_str(counter_entry.get("clean_block_end_utc")),
        clean_block_duration_seconds=_optional_float(counter_entry.get("clean_block_duration_seconds")),
        clean_block_event_count=_optional_int(counter_entry.get("clean_block_event_count")),
        clean_block_direction=_optional_str(counter_entry.get("clean_block_direction")),
        watch_promotion_source=_optional_str(counter_entry.get("watch_promotion_source")),
        microboost_validation_status=_optional_str(counter_entry.get("microboost_validation_status")),
        microboost_role=_optional_str(counter_entry.get("microboost_role")),
        microboost_followthrough_bias=_optional_str(counter_entry.get("microboost_followthrough_bias")),
        microboost_room_to_move_pips=_optional_float(counter_entry.get("microboost_room_to_move_pips")),
        microboost_pre_move_pips=_optional_float(counter_entry.get("microboost_pre_move_pips")),
        microboost_late_move_penalty=_optional_float(counter_entry.get("microboost_late_move_penalty")),
        microboost_followthrough_context_ready=_optional_bool(
            counter_entry.get("microboost_followthrough_context_ready")
        ),
        microboost_price_behavior=_optional_str(counter_entry.get("microboost_price_behavior")),
        microboost_room_to_move_status=_optional_str(counter_entry.get("microboost_room_to_move_status")),
        microboost_stall_pips=_optional_float(counter_entry.get("microboost_stall_pips")),
        microboost_room_to_target_pips=_optional_float(counter_entry.get("microboost_room_to_target_pips")),
        microboost_expected_horizon=_optional_str(counter_entry.get("microboost_expected_horizon")),
        microboost_outcome_tracking_required=_optional_bool(counter_entry.get("microboost_outcome_tracking_required")),
        microboost_role_source_event=_optional_str(counter_entry.get("microboost_role_source_event")),
        microboost_role_reason_codes=_string_list(counter_entry.get("microboost_role_reason_codes")),
        microboost_role_valid_for_execution=_optional_bool(counter_entry.get("microboost_role_valid_for_execution")),
        microboost_role_execution_impact=_optional_bool(counter_entry.get("microboost_role_execution_impact")),
        microboost_role_advisory_only=_optional_bool(counter_entry.get("microboost_role_advisory_only")),
        source_target_mode=_optional_str(counter_entry.get("source_target_mode")),
        parent_event_type=_optional_str(counter_entry.get("parent_event_type")),
        parent_event_exists=_optional_bool(counter_entry.get("parent_event_exists")),
        parent_watch_id=_optional_str(counter_entry.get("parent_watch_id")),
        parent_watch_required=_optional_bool(counter_entry.get("parent_watch_required")),
        promotion_path=_optional_str(counter_entry.get("promotion_path")),
        promotion_trigger=_optional_str(counter_entry.get("promotion_trigger")),
        bypass_reason=_optional_str(counter_entry.get("bypass_reason")),
        second_m15_confirmation=_optional_bool(counter_entry.get("second_m15_confirmation")),
        reversal_confirmed=_optional_bool(counter_entry.get("reversal_confirmed")),
        cooldown_m15_bars_elapsed=_optional_int(counter_entry.get("cooldown_m15_bars_elapsed")),
        execution_grade=_optional_str(counter_entry.get("execution_grade")),
        audit_valid=_optional_bool(counter_entry.get("audit_valid")),
        audit_block_reasons=_string_list(counter_entry.get("audit_block_reasons")),
        source_status=_optional_str(counter_entry.get("source_status")),
        source_final_direction=_optional_str(counter_entry.get("source_final_direction")),
        decision_state=_optional_str(counter_entry.get("decision_state")),
        terminal_decision_confirmed=_optional_bool(counter_entry.get("terminal_decision_confirmed")),
        terminal_decision_id=_optional_str(counter_entry.get("terminal_decision_id")),
        terminal_decision_event_type=_optional_str(counter_entry.get("terminal_decision_event_type")),
        matched_patterns=_string_list(counter_entry.get("matched_patterns")),
        selected_pattern_id=_optional_str(counter_entry.get("selected_pattern_id")),
        pattern_tier=_optional_str(counter_entry.get("pattern_tier")),
        pattern_family=_optional_str(counter_entry.get("pattern_family")),
        pattern_score=_optional_int(counter_entry.get("pattern_score")),
        pattern_match_score=_optional_int(counter_entry.get("pattern_match_score")),
        execution_readiness_score=_optional_int(counter_entry.get("execution_readiness_score")),
        golden_reference=_optional_str(counter_entry.get("golden_reference")),
        pattern_scope=_optional_str(counter_entry.get("pattern_scope")),
        applies_to=_optional_str(counter_entry.get("applies_to")),
        golden_references=_string_list(counter_entry.get("golden_references")),
        pair_specific_calibration=_string_list(counter_entry.get("pair_specific_calibration")),
        pair_role=_optional_str(counter_entry.get("pair_role")),
        entry_permission=_optional_str(counter_entry.get("entry_permission")),
        management_action=_optional_str(counter_entry.get("management_action")),
        hold_policy=_optional_str(counter_entry.get("hold_policy")),
        chase_allowed=_optional_bool(counter_entry.get("chase_allowed")),
        block_reason=_optional_str(counter_entry.get("block_reason")),
        pattern_evidence=_string_list(counter_entry.get("pattern_evidence")),
        pattern_search_space=_string_list(counter_entry.get("pattern_search_space")),
        pattern_db_candidates_scanned=_optional_int(counter_entry.get("pattern_db_candidates_scanned")),
        pattern_db_exact_matches=_string_list(counter_entry.get("pattern_db_exact_matches")),
        pattern_db_fuzzy_matches=_string_list(counter_entry.get("pattern_db_fuzzy_matches")),
        pattern_bottlenecks=_string_list(counter_entry.get("pattern_bottlenecks")),
        pattern_match_diagnostics=_dict_value(counter_entry.get("pattern_match_diagnostics")),
        reference_cases=_reference_cases(counter_entry),
        pair_calibration=_pair_calibration(counter_entry, symbol=symbol),
        pattern_context=_pattern_context(counter_entry),
        theme_context=_theme_context(counter_entry),
        tradeplan_preview=_dict_value(counter_entry.get("tradeplan_preview")) or _tradeplan_preview(counter_entry),
        market_structure=_dict_value(counter_entry.get("market_structure")),
        execution_gate=_dict_value(counter_entry.get("execution_gate")) or _execution_gate_context(counter_entry),
        lifecycle=_dict_value(counter_entry.get("lifecycle")) or _lifecycle_context(counter_entry),
        pressure_priority_context=(
            _dict_value(counter_entry.get("pressure_priority_context")) if is_watch else None
        ),
        followthrough_context=(
            _dict_value(counter_entry.get("followthrough_context")) if is_watch else None
        ),
    )


def should_emit_signal_json(
    event_or_payload: SignalJsonEvent | dict[str, Any],
    *,
    emit_watch: bool = True,
    emit_conditional: bool = True,
    emit_valid: bool = True,
    require_market_context: bool = True,
) -> bool:
    payload = event_or_payload.to_dict() if isinstance(event_or_payload, SignalJsonEvent) else event_or_payload
    status = str(payload.get("status") or "")
    if status not in EMITTABLE_SIGNAL_STATUSES:
        return False
    if _is_decision_update_payload(payload):
        return (
            _optional_float(payload.get("signal_valid_price")) is not None
            and _optional_float(payload.get("entry_reference_price")) is not None
        )
    is_conditional = status in CONDITIONAL_SIGNAL_STATUSES
    if is_conditional and not emit_conditional:
        return False
    if status in WATCH_SIGNAL_STATUSES and not is_conditional and not emit_watch:
        return False
    if status in VALID_SIGNAL_STATUSES and not emit_valid:
        return False
    if require_market_context and not bool(payload.get("market_context_applied", False)):
        return False
    if _optional_float(payload.get("signal_valid_price")) is None:
        return False
    if _optional_float(payload.get("entry_reference_price")) is None:
        return False
    if status in TERMINAL_VALID_SIGNAL_STATUSES:
        if not _is_decision_update_payload(payload):
            return False
        terminal_direction = str(payload.get("final_direction") or payload.get("validated_direction") or "").upper()
        if terminal_direction not in {"BUY", "SELL"}:
            return False
        if not bool(payload.get("signal_valid") or payload.get("direction_valid")):
            return False
        return not bool(payload.get("valid_for_execution", False))
    if status in TERMINAL_EXECUTION_READY_STATUSES:
        if not _is_final_payload(payload):
            return False
        return _optional_bool(payload.get("execution_valid_now")) is True
    if status in TERMINAL_INACTIVE_SIGNAL_STATUSES:
        return _is_decision_update_payload(payload)
    if status in VALID_SIGNAL_STATUSES or str(status).endswith("_VALID"):
        rr_status = str(payload.get("rr_status") or "").upper()
        if rr_status not in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}:
            return False
        if str(payload.get("final_direction") or "").upper() not in {"BUY", "SELL"}:
            return False
        if not _target_contract_ok(payload, status=status):
            return False
        if not bool(payload.get("valid_for_execution", False)):
            return False
    return True


def _is_watch_status(status: str) -> bool:
    return status in WATCH_SIGNAL_STATUSES or status.endswith("_WATCH")


def _is_decision_update_status(status: str) -> bool:
    return status in DECISION_UPDATE_STATUSES


def _is_decision_update_event(event: SignalJsonEvent) -> bool:
    return event.event == "signal_decision_update_json" or _is_decision_update_status(event.status)


def _is_decision_update_payload(payload: dict[str, Any]) -> bool:
    return str(payload.get("event") or "") == "signal_decision_update_json" or _is_decision_update_status(
        str(payload.get("status") or "")
    )


def _is_terminal_signal_status(status: str) -> bool:
    return status in TERMINAL_SIGNAL_STATUSES


def _is_terminal_non_execution_status(status: str) -> bool:
    return status in TERMINAL_VALID_SIGNAL_STATUSES or status in TERMINAL_INACTIVE_SIGNAL_STATUSES


def _is_structure_target_mode(value: Any) -> bool:
    return str(value or "").upper() in STRUCTURE_TARGET_MODES


def _emit_reason(status: str) -> str:
    if status in TERMINAL_EXECUTION_READY_STATUSES:
        return "TERMINAL_EXECUTION_READY"
    if status in TERMINAL_VALID_SIGNAL_STATUSES:
        return "TERMINAL_VALID_SIGNAL"
    if status == "FINAL_INVALIDATED":
        return "TERMINAL_SIGNAL_INVALIDATED"
    if status == "FINAL_EXPIRED":
        return "TERMINAL_SIGNAL_EXPIRED"
    if _is_decision_update_status(status):
        return "BLOCK_FINALIZER_DECISION_UPDATE"
    if status in CONTINUATION_SIGNAL_STATUSES:
        return "QUORUM_CONTINUATION_VALID"
    if status.endswith("_BY_DIRECT_ABSORPTION"):
        return "DIRECT_ABSORPTION_VALID"
    if status in {"SELL_ABSORPTION_WATCH", "BUY_ABSORPTION_WATCH"}:
        return "ABSORPTION_WATCH"
    if status in CONDITIONAL_SIGNAL_STATUSES:
        return "TIMING_VALID_CONDITIONAL"
    if status in WATCH_SIGNAL_STATUSES:
        return "STATE_TRANSITION"
    return "FINAL_SIGNAL_VALID"


def _is_final_payload(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    if status in TERMINAL_EXECUTION_READY_STATUSES:
        target_mode = _effective_target_mode(payload)
        return (
            str(payload.get("final_direction") or "").upper() in {"BUY", "SELL"}
            and str(payload.get("rr_status") or "").upper() in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}
            and target_mode in STRUCTURE_TARGET_MODES
            and _optional_bool(payload.get("analysis_valid")) is True
            and _optional_bool(payload.get("direction_valid")) is True
            and _optional_bool(payload.get("signal_valid")) is True
            and _effective_tradeplan_valid(payload) is True
            and _effective_valid_for_execution(payload) is True
            and _effective_execution_valid_now(payload) is True
        )
    return (
        (status in VALID_SIGNAL_STATUSES or status.endswith("_VALID"))
        and str(payload.get("final_direction") or "").upper() in {"BUY", "SELL"}
        and str(payload.get("rr_status") or "").upper() in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}
        and _target_contract_ok(payload, status=status)
        and _optional_bool(payload.get("analysis_valid")) is True
        and _optional_bool(payload.get("direction_valid")) is True
        and _optional_bool(payload.get("signal_valid")) is True
        and _effective_tradeplan_valid(payload) is True
        and _effective_valid_for_execution(payload) is True
        and _effective_execution_valid_now(payload) is True
    )


def _uses_provisional_rr_fallback(payload: dict[str, Any]) -> bool:
    tradeplan = _dict_value(payload.get("tradeplan_preview")) or {}
    target_mode = str(
        tradeplan.get("source_target_mode")
        or tradeplan.get("target_mode")
        or payload.get("source_target_mode")
        or payload.get("target_mode")
        or ""
    ).upper()
    return target_mode == "PROVISIONAL_RR_FALLBACK"


def _final_execution_block_reasons(payload: dict[str, Any]) -> list[str]:
    if not _is_directional_final_candidate(payload):
        return []
    tradeplan = _dict_value(payload.get("tradeplan_preview")) or {}
    execution_gate = _dict_value(payload.get("execution_gate")) or {}
    reasons: list[str] = []

    if _uses_provisional_rr_fallback(payload):
        reasons.append("PROVISIONAL_RR_NOT_EXECUTION_GRADE")
    elif not _target_contract_ok(payload, status=str(payload.get("status") or "")):
        reasons.append("STRUCTURE_TARGET_MODE_REQUIRED")
    if _optional_bool(payload.get("analysis_valid")) is not True:
        reasons.append("ANALYSIS_CONTRACT_NOT_READY")
    if _optional_bool(payload.get("direction_valid")) is not True:
        reasons.append("DIRECTION_CONTRACT_NOT_READY")
    if _optional_bool(payload.get("signal_valid")) is not True:
        reasons.append("SIGNAL_CONTRACT_NOT_READY")
    if _effective_tradeplan_valid(payload) is not True:
        reasons.append("TRADEPLAN_CONTRACT_NOT_READY")
    if _effective_execution_valid_now(payload) is not True:
        reasons.append("EXECUTION_VALID_NOW_FALSE")
    if _effective_valid_for_execution(payload) is not True:
        reasons.append("VALID_FOR_EXECUTION_FALSE")
    if _optional_bool(tradeplan.get("structure_targets_available")) is False:
        reasons.append("STRUCTURE_TARGET_MODE_REQUIRED")
    if _optional_bool(tradeplan.get("tradeplan_context_ready")) is False:
        reasons.append("TRADEPLAN_CONTRACT_NOT_READY")
    if _optional_bool(tradeplan.get("targets_execution_usable")) is False:
        reasons.append("TARGETS_EXECUTION_NOT_USABLE")

    entry_permission = str(payload.get("entry_permission") or execution_gate.get("entry_permission") or "").upper()
    if entry_permission == "RETEST_ONLY":
        reasons.append("RETEST_ENTRY_REQUIRED")
    chase_allowed = _optional_bool(payload.get("chase_allowed"))
    if chase_allowed is None:
        chase_allowed = _optional_bool(execution_gate.get("chase_allowed"))
    if chase_allowed is False:
        reasons.append("NO_CHASE_ENTRY_PERMISSION")

    return list(dict.fromkeys(reasons))


def _is_directional_final_candidate(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return bool(
        (status in TERMINAL_EXECUTION_READY_STATUSES or status in VALID_SIGNAL_STATUSES or status.endswith("_VALID"))
        and str(payload.get("final_direction") or payload.get("validated_direction") or "").upper()
        in {"BUY", "SELL"}
    )


def _target_contract_ok(payload: dict[str, Any], *, status: str) -> bool:
    target_mode = _effective_target_mode(payload)
    if target_mode in STRUCTURE_TARGET_MODES:
        return True
    return status in PROVISIONAL_TARGET_ALLOWED_FINAL_STATUSES and _legacy_structure_target_contract_complete(payload)


def _effective_target_mode(payload: dict[str, Any]) -> str:
    tradeplan = _dict_value(payload.get("tradeplan_preview")) or {}
    return str(tradeplan.get("target_mode") or payload.get("target_mode") or "").upper()


def _effective_tradeplan_valid(payload: dict[str, Any]) -> bool | None:
    tradeplan = _dict_value(payload.get("tradeplan_preview")) or {}
    nested = _optional_bool(tradeplan.get("tradeplan_valid"))
    return nested if nested is not None else _optional_bool(payload.get("tradeplan_valid"))


def _effective_execution_valid_now(payload: dict[str, Any]) -> bool | None:
    execution_gate = _dict_value(payload.get("execution_gate")) or {}
    nested = _optional_bool(execution_gate.get("execution_valid_now"))
    return nested if nested is not None else _optional_bool(payload.get("execution_valid_now"))


def _effective_valid_for_execution(payload: dict[str, Any]) -> bool | None:
    execution_gate = _dict_value(payload.get("execution_gate")) or {}
    nested = _optional_bool(execution_gate.get("valid_for_execution"))
    return nested if nested is not None else _optional_bool(payload.get("valid_for_execution"))


def _legacy_structure_target_contract_complete(payload: dict[str, Any]) -> bool:
    """Accept legacy final continuation payloads that predate explicit target_mode."""
    if str(payload.get("target_mode") or "").strip():
        return False
    if _optional_float(payload.get("entry_reference_price") or payload.get("signal_valid_price")) is None:
        return False
    if _optional_float(payload.get("sl_safe") or payload.get("selected_sl") or payload.get("suggested_sl")) is None:
        return False
    if not any(_optional_float(payload.get(key)) is not None for key in ("tp1", "tp2", "tp3", "tp4")):
        targets = payload.get("targets")
        if not isinstance(targets, list) or not targets:
            return False
    return any(
        _optional_float(payload.get(key)) is not None
        for key in ("rr_to_tp1_tight", "tp1_rr", "tp_min_rr_value", "rr_to_valid_target")
    )


def _signal_quality(payload: dict[str, Any]) -> str:
    if _is_decision_update_payload(payload):
        return "DECISION_UPDATE"
    status = str(payload.get("status") or "")
    if status in TERMINAL_EXECUTION_READY_STATUSES:
        return "FINAL_EXECUTION_READY"
    if status == "FINAL_VALID_MANAGEMENT_ONLY":
        return "TERMINAL_VALID_MANAGEMENT_ONLY"
    if status == "FINAL_VALID_WAIT_RETEST":
        return "TERMINAL_VALID_WAIT_RETEST"
    if status in TERMINAL_VALID_SIGNAL_STATUSES:
        return "TERMINAL_VALID_EXECUTION_DEFERRED"
    if status in TERMINAL_INACTIVE_SIGNAL_STATUSES:
        return status
    if _is_final_payload(payload):
        if str(payload.get("status") or "").endswith("_BY_DIRECT_ABSORPTION"):
            return "DIRECT_ABSORPTION_VALID"
        if str(payload.get("status") or "") in CONTINUATION_SIGNAL_STATUSES:
            return "TREND_CONTINUATION_VALID"
        return "TRADEPLAN_VALID"
    if status in {"SELL_ABSORPTION_WATCH", "BUY_ABSORPTION_WATCH"}:
        return "ABSORPTION_WATCH"
    if status.endswith("_BY_ABSORPTION"):
        return "TIMING_VALID_CONDITIONAL"
    if _is_watch_status(status):
        return "WATCH_ONLY"
    return "CANDIDATE"


def _terminal_non_execution_as_decision_update(payload: dict[str, Any]) -> dict[str, Any]:
    update = dict(payload)
    terminal_status = str(payload.get("terminal_status") or payload.get("status") or "")
    source_direction = str(
        payload.get("validated_direction")
        or payload.get("final_direction")
        or payload.get("candidate_direction")
        or "WAIT"
    ).upper()
    direction_valid = source_direction in {"BUY", "SELL"} and terminal_status in TERMINAL_VALID_SIGNAL_STATUSES
    update.update(
        {
            "event": "signal_decision_update_json",
            "source_status": payload.get("source_status") or payload.get("status"),
            "source_final_direction": payload.get("source_final_direction") or payload.get("final_direction"),
            "status": terminal_status,
            "new_status": terminal_status,
            "terminal_status": terminal_status,
            "final_direction": "WAIT",
            "validated_direction": source_direction if direction_valid else None,
            "watch_direction": source_direction if source_direction in {"BUY", "SELL"} else payload.get("watch_direction"),
            "is_final_signal": False,
            "signal_valid": direction_valid,
            "direction_valid": direction_valid,
            "analysis_valid": direction_valid or bool(payload.get("analysis_valid")),
            "valid_for_execution": False,
            "execution_valid_now": False,
            "terminal_decision_confirmed": True,
            "terminal_decision_event_type": "signal_decision_update_json",
            "emit_reason": "TERMINAL_LIFECYCLE_DECISION_UPDATE",
            "signal_quality": "DECISION_UPDATE",
        }
    )
    return update


def _blocked_final_as_decision_update(payload: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    blocked = dict(payload)
    source_status = str(payload.get("status") or "")
    source_direction = str(payload.get("final_direction") or "WAIT")
    terminal_status = _blocked_final_terminal_status(reasons)
    blocked.update(
        {
            "event": "signal_decision_update_json",
            "source_status": source_status,
            "source_final_direction": source_direction,
            "source_valid_for_execution": bool(payload.get("valid_for_execution", False)),
            "status": "WAIT_STRUCTURE_OR_NEXT_M15",
            "new_status": "WAIT_STRUCTURE_OR_NEXT_M15",
            "terminal_status": terminal_status,
            "final_direction": "WAIT",
            "validated_direction": None,
            "watch_direction": source_direction
            if source_direction in {"BUY", "SELL"}
            else payload.get("watch_direction"),
            "direction_validation_status": "FINAL_DIRECTION_VALID_EXECUTION_DEFERRED"
            if source_direction in {"BUY", "SELL"}
            else "FINAL_CANDIDATE_BLOCKED_BY_STRICT_GATE",
            "action": _blocked_final_action(terminal_status),
            "next_action": _blocked_final_next_action(terminal_status),
            "is_final_signal": False,
            "emit_reason": "STRICT_LIFECYCLE_DECISION_UPDATE",
            "signal_quality": "DECISION_UPDATE",
            "signal_valid": source_direction in {"BUY", "SELL"},
            "direction_valid": source_direction in {"BUY", "SELL"},
            "analysis_valid": bool(payload.get("analysis_valid") or source_direction in {"BUY", "SELL"}),
            "tradeplan_valid": False,
            "valid_for_execution": False,
            "execution_valid_now": False,
            "execution_status": _blocked_final_execution_status(terminal_status),
            "execution_reason": ", ".join(reasons),
            "execution_grade": "CONDITIONAL",
            "audit_valid": False,
            "audit_block_reasons": list(dict.fromkeys(reasons)),
            "reason": f"{payload.get('reason') or 'signal_candidate'} Output final blocked: {', '.join(reasons)}.",
        }
    )
    return blocked


def _blocked_final_terminal_status(reasons: list[str]) -> str:
    reason_set = set(reasons)
    if reason_set & {
        "PROVISIONAL_RR_NOT_EXECUTION_GRADE",
        "PROVISIONAL_RR_FALLBACK_NOT_EXECUTION_GRADE",
        "STRUCTURE_TARGET_MODE_REQUIRED",
        "TRADEPLAN_CONTRACT_NOT_READY",
        "TARGETS_EXECUTION_NOT_USABLE",
    }:
        return "FINAL_VALID_WAIT_STRUCTURE_TARGET"
    if reason_set & {"RETEST_ENTRY_REQUIRED", "NO_CHASE_ENTRY_PERMISSION"}:
        return "FINAL_VALID_WAIT_RETEST"
    return "FINAL_VALID_EXECUTION_DEFERRED"


def _blocked_final_action(terminal_status: str) -> str:
    if terminal_status == "FINAL_VALID_WAIT_RETEST":
        return "WAIT_RETEST_OR_CONFIRMATION"
    if terminal_status == "FINAL_VALID_WAIT_STRUCTURE_TARGET":
        return "WAIT_STRUCTURE_TARGET_OR_RETEST"
    return "WAIT_EXECUTION_CONTRACT"


def _blocked_final_next_action(terminal_status: str) -> str:
    return _blocked_final_action(terminal_status)


def _blocked_final_execution_status(terminal_status: str) -> str:
    if terminal_status == "FINAL_VALID_WAIT_RETEST":
        return "WAIT_RETEST_CONFIRMATION"
    if terminal_status == "FINAL_VALID_WAIT_STRUCTURE_TARGET":
        return "WAIT_STRUCTURE_TARGET"
    return "WAIT_EXECUTION_CONTRACT"


def _execution_ready_decision_update(payload: dict[str, Any]) -> dict[str, Any]:
    update = dict(payload)
    source_status = str(payload.get("status") or "")
    source_direction = str(payload.get("final_direction") or "WAIT")
    update.update(
        {
            "event": "signal_decision_update_json",
            "source_status": source_status,
            "source_final_direction": source_direction,
            "status": "EXECUTION_READY",
            "new_status": "EXECUTION_READY",
            "decision_state": "EXECUTION_READY",
            "terminal_decision_confirmed": True,
            "terminal_decision_id": payload.get("pending_decision_id"),
            "terminal_decision_event_type": "signal_decision_update_json",
            "action": "EMIT_SIGNAL_JSON",
            "next_action": "EMIT_SIGNAL_JSON",
            "is_final_signal": False,
            "emit_reason": "TERMINAL_EXECUTION_DECISION",
            "signal_quality": "DECISION_UPDATE_EXECUTION_READY",
            "execution_status": "EXECUTION_READY",
            "execution_grade": "FINAL_STRUCTURE",
            "audit_valid": True,
            "audit_block_reasons": [],
            "reason": (
                f"{payload.get('reason') or 'signal_candidate'} "
                "Terminal DecisionUpdate confirmed the execution contract before SignalJSON emission."
            ),
        }
    )
    return update


def _watch_references(payload: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    pending_id = _optional_str(payload.get("pending_decision_id"))
    if pending_id:
        references.add(f"pending:{pending_id}")
    cluster_id = _optional_str(payload.get("cluster_id"))
    symbol = _optional_str(payload.get("symbol"))
    if cluster_id and symbol:
        references.add(f"cluster:{symbol.upper()}:{cluster_id}")
    return references


def _watch_payload_revision(payload: dict[str, Any]) -> str:
    fields = (
        "signal_valid_time_utc",
        "signal_valid_price",
        "effective_ticks",
        "effective_density",
        "duration_minutes",
        "rr_status",
        "tp_status",
        "target_mode",
        "direction_validation_status",
        "execution_status",
        "action",
    )
    return "|".join(str(payload.get(field) or "") for field in fields)


def _watch_transition_state(event: SignalJsonEvent) -> str:
    fields = (
        event.status,
        event.target_mode,
        event.tp_status,
        event.watch_direction,
        event.direction_validation_status,
        event.phase_priced,
        event.price_position,
        event.action,
    )
    return "|".join(str(field or "") for field in fields)


def _signal_time_epoch_seconds(value: str | None) -> float | None:
    raw = _optional_str(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _apply_signal_watch_pressure_tier_fields(payload: dict[str, Any]) -> None:
    context = _dict_value(payload.get("pressure_priority_context"))
    if not context:
        return
    tier = _optional_str(context.get("effective_pressure_tier"))
    if tier is None:
        return
    payload["effective_pressure_tier"] = tier
    payload["signal_watch_pressure_tier"] = tier
    payload["signal_watch_priority_bucket"] = _signal_watch_priority_bucket(tier)
    payload["signal_watch_tier_action"] = _optional_str(context.get("tier_action"))
    payload["signal_watch_tier_score"] = _optional_float(context.get("tier_score"))
    payload["signal_watch_tier_scope"] = _optional_str(context.get("tier_scope"))
    payload["signal_watch_tier_source_event"] = _optional_str(context.get("tier_source_event"))
    payload["signal_watch_tier_reason_codes"] = _string_list(context.get("tier_reason_codes"))
    payload["signal_watch_tier_execution_impact"] = _optional_bool(context.get("tier_execution_impact"))
    payload["signal_watch_tier_is_execution_signal"] = _optional_bool(context.get("tier_is_execution_signal"))


def _apply_signal_watch_followthrough_fields(payload: dict[str, Any]) -> None:
    context = _dict_value(payload.get("followthrough_context"))
    if not context:
        return
    score = _optional_int(context.get("followthrough_score"))
    if score is None:
        return
    payload["signal_watch_followthrough_score"] = score
    payload["signal_watch_followthrough_bucket"] = _optional_str(context.get("followthrough_bucket"))
    payload["signal_watch_pressure_quality_bucket"] = _optional_str(context.get("pressure_quality_bucket"))
    payload["signal_watch_microboost_role"] = _optional_str(context.get("microboost_role"))
    payload["signal_watch_room_to_move_score"] = _optional_float(context.get("room_to_move_score"))
    payload["signal_watch_directional_room_pips"] = _optional_float(context.get("directional_room_pips"))
    payload["signal_watch_gap_health"] = _optional_str(context.get("gap_health"))
    payload["signal_watch_late_move_penalty"] = _optional_float(context.get("late_move_penalty"))
    payload["signal_watch_gap_degradation_penalty"] = _optional_float(context.get("gap_degradation_penalty"))
    payload["signal_watch_followthrough_risk_flags"] = _string_list(context.get("risk_flags"))
    payload["signal_watch_followthrough_source_event"] = _optional_str(context.get("source_event"))
    payload["signal_watch_followthrough_execution_impact"] = _optional_bool(context.get("execution_impact"))
    payload["signal_watch_followthrough_is_execution_signal"] = _optional_bool(context.get("valid_for_execution"))


def _apply_signal_watch_microboost_role_fields(payload: dict[str, Any]) -> None:
    role = _optional_str(payload.get("microboost_role"))
    if role is None:
        return
    payload["signal_watch_microboost_role"] = role
    payload["signal_watch_microboost_followthrough_bias"] = _optional_str(payload.get("microboost_followthrough_bias"))
    payload["signal_watch_microboost_room_to_move_pips"] = _optional_float(payload.get("microboost_room_to_move_pips"))
    payload["signal_watch_microboost_pre_move_pips"] = _optional_float(payload.get("microboost_pre_move_pips"))
    payload["signal_watch_microboost_late_move_penalty"] = _optional_float(payload.get("microboost_late_move_penalty"))
    payload["signal_watch_microboost_followthrough_context_ready"] = _optional_bool(
        payload.get("microboost_followthrough_context_ready")
    )
    payload["signal_watch_microboost_price_behavior"] = _optional_str(payload.get("microboost_price_behavior"))
    payload["signal_watch_microboost_room_to_move_status"] = _optional_str(payload.get("microboost_room_to_move_status"))
    payload["signal_watch_microboost_stall_pips"] = _optional_float(payload.get("microboost_stall_pips"))
    payload["signal_watch_microboost_room_to_target_pips"] = _optional_float(payload.get("microboost_room_to_target_pips"))
    payload["signal_watch_microboost_expected_horizon"] = _optional_str(payload.get("microboost_expected_horizon"))
    payload["signal_watch_microboost_outcome_tracking_required"] = _optional_bool(
        payload.get("microboost_outcome_tracking_required")
    )
    payload["signal_watch_microboost_role_source_event"] = _optional_str(payload.get("microboost_role_source_event"))
    payload["signal_watch_microboost_role_reason_codes"] = _string_list(payload.get("microboost_role_reason_codes"))
    payload["signal_watch_microboost_role_execution_impact"] = _optional_bool(
        payload.get("microboost_role_execution_impact")
    )
    payload["signal_watch_microboost_role_is_execution_signal"] = _optional_bool(
        payload.get("microboost_role_valid_for_execution")
    )


def _strip_pressure_priority_fields(payload: dict[str, Any]) -> None:
    for key in (
        "pressure_priority_context",
        "effective_pressure_tier",
        "signal_watch_pressure_tier",
        "signal_watch_priority_bucket",
        "signal_watch_tier_action",
        "signal_watch_tier_score",
        "signal_watch_tier_scope",
        "signal_watch_tier_source_event",
        "signal_watch_tier_reason_codes",
        "signal_watch_tier_execution_impact",
        "signal_watch_tier_is_execution_signal",
    ):
        payload.pop(key, None)


def _strip_followthrough_fields(payload: dict[str, Any]) -> None:
    for key in (
        "followthrough_context",
        "signal_watch_followthrough_score",
        "signal_watch_followthrough_bucket",
        "signal_watch_pressure_quality_bucket",
        "signal_watch_microboost_role",
        "signal_watch_room_to_move_score",
        "signal_watch_directional_room_pips",
        "signal_watch_gap_health",
        "signal_watch_late_move_penalty",
        "signal_watch_gap_degradation_penalty",
        "signal_watch_followthrough_risk_flags",
        "signal_watch_followthrough_source_event",
        "signal_watch_followthrough_execution_impact",
        "signal_watch_followthrough_is_execution_signal",
    ):
        payload.pop(key, None)


def _strip_microboost_role_fields(payload: dict[str, Any]) -> None:
    for key in (
        *MICROBOOST_FOLLOWTHROUGH_ROLE_FIELDS,
        "signal_watch_microboost_followthrough_bias",
        "signal_watch_microboost_room_to_move_pips",
        "signal_watch_microboost_pre_move_pips",
        "signal_watch_microboost_late_move_penalty",
        "signal_watch_microboost_followthrough_context_ready",
        "signal_watch_microboost_price_behavior",
        "signal_watch_microboost_room_to_move_status",
        "signal_watch_microboost_stall_pips",
        "signal_watch_microboost_room_to_target_pips",
        "signal_watch_microboost_expected_horizon",
        "signal_watch_microboost_outcome_tracking_required",
        "signal_watch_microboost_role_source_event",
        "signal_watch_microboost_role_reason_codes",
        "signal_watch_microboost_role_execution_impact",
        "signal_watch_microboost_role_is_execution_signal",
    ):
        payload.pop(key, None)


def _signal_watch_priority_bucket(tier: str) -> str:
    tier_key = str(tier or "").upper()
    return {
        "TIER_1_PRIMARY_ANALYSIS": "PRIMARY_ANALYSIS",
        "TIER_2_CONFIRMATION_SUPPORT": "CONFIRMATION_SUPPORT",
        "TIER_3_KEY_LEVEL_RADAR_EXCEPTION": "KEY_LEVEL_RADAR_EXCEPTION",
        "TIER_3_THEME_RADAR": "RADAR_ONLY",
        "FRAGMENTED_PRESSURE_RADAR": "RADAR_ONLY",
        "PRESSURE_MEMORY_RADAR": "RADAR_ONLY",
        "THEME_ROTATION_RADAR": "RADAR_ONLY",
        "TIER_STALE_ARCHIVE": "AUDIT_ONLY",
        "TIER_UNSAFE_MIXED_DEPLOYMENT": "UNSAFE_MIXED_DEPLOYMENT",
    }.get(tier_key, "UNCLASSIFIED")


def _matched_watch_reference(payload: dict[str, Any], emitted_refs: set[str]) -> str | None:
    matches = _watch_references(payload) & emitted_refs
    if not matches:
        return None
    pending_matches = sorted(reference for reference in matches if reference.startswith("pending:"))
    selected = pending_matches[0] if pending_matches else sorted(matches)[0]
    return selected.split(":", 1)[1]


def _theme_conflicts(payload: dict[str, Any]) -> bool:
    direction = str(payload.get("final_direction") or "").upper()
    alignment = str(payload.get("theme_alignment") or "").upper()
    if direction == "BUY":
        return "SELL" in alignment
    if direction == "SELL":
        return "BUY" in alignment
    return False


def _active_signal_conflicts(payload: dict[str, Any]) -> bool:
    active = payload.get("active_signal")
    if not isinstance(active, dict):
        return False
    current = str(payload.get("final_direction") or "").upper()
    active_direction = str(active.get("direction") or "").upper()
    return current in {"BUY", "SELL"} and active_direction in {"BUY", "SELL"} and current != active_direction


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    values: list[float] = []
    for item in value:
        number = _optional_float(item)
        if number is not None:
            values.append(number)
    return values


def _reference_cases_enabled() -> bool:
    """Reference/golden cases are pattern-debug, not main-payload. Default OFF.

    When disabled they are stripped from the production SignalWatch/Decision/JSON
    payload (and survive only on the ``[PatternMatchDebugJSON]`` sidecar). Enable
    with ``SIGNAL_WATCH_INCLUDE_REFERENCE_CASES=true`` for debugging.
    """
    return os.getenv("SIGNAL_WATCH_INCLUDE_REFERENCE_CASES", "false").strip().lower() == "true"


def _universal_pattern_payload(payload: dict[str, Any], *, compact: bool = True) -> dict[str, Any]:
    universal = dict(payload)
    universal["schema_version"] = UNIVERSAL_PATTERN_SCHEMA_VERSION
    universal["theme_alignment_status"] = _theme_alignment_status(universal)
    universal["alignment_missing_reason"] = _alignment_missing_reason(universal)
    universal["reference_cases"] = _reference_cases(universal) if _reference_cases_enabled() else None
    universal["pair_calibration"] = _pair_calibration(universal)
    universal["pattern_context"] = _pattern_context(universal, include_debug=not compact)
    universal["theme_context"] = (
        None if compact else _clean_context(_dict_value(universal.get("theme_context")) or _theme_context(universal))
    )
    universal["tradeplan_preview"] = _clean_context(
        _dict_value(universal.get("tradeplan_preview")) or _tradeplan_preview(universal)
    )
    universal["execution_gate"] = _clean_context(
        _dict_value(universal.get("execution_gate")) or _execution_gate_context(universal)
    )
    universal["lifecycle"] = _clean_context(_dict_value(universal.get("lifecycle")) or _lifecycle_context(universal))
    return _schema_v2_payload(universal, compact=compact)


def _schema_v1_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in V11_OUTPUT_ONLY_FIELDS}


def _schema_v2_payload(payload: dict[str, Any], *, compact: bool = True) -> dict[str, Any]:
    hidden = V11_OUTPUT_ONLY_FIELDS | PAIR_REFERENCE_COMPAT_FIELDS
    if compact:
        hidden |= PATTERN_DEBUG_FIELDS | NESTED_SCHEMA_DUPLICATE_FIELDS
    if _is_terminal_signal_status(str(payload.get("status") or "")) or _is_decision_update_payload(payload):
        hidden -= TERMINAL_SIGNAL_PUBLIC_FIELDS
    cleaned = {key: value for key, value in payload.items() if key not in hidden}
    return (_clean_context(cleaned) if compact else cleaned) or {}


def _pattern_context(payload: dict[str, Any], *, include_debug: bool = False) -> dict[str, Any] | None:
    existing = _dict_value(payload.get("pattern_context")) or {}
    selected_pattern_id = _optional_str(payload.get("selected_pattern_id") or existing.get("selected_pattern_id"))
    matched_patterns = _string_list_any(payload.get("matched_patterns")) or _string_list_any(
        existing.get("matched_patterns")
    )
    reference_cases = _reference_cases(payload)
    pattern_evidence = _string_list_any(payload.get("pattern_evidence")) or _string_list_any(
        existing.get("pattern_evidence")
    )
    diagnostics = _dict_value(payload.get("pattern_match_diagnostics")) or _dict_value(
        existing.get("pattern_match_diagnostics")
    )
    pattern_bottlenecks = _clean_pattern_bottlenecks(
        _string_list(payload.get("pattern_bottlenecks")) or _string_list(existing.get("pattern_bottlenecks")),
        payload=payload,
    )
    top_supporting_patterns = [pattern for pattern in matched_patterns or [] if pattern != selected_pattern_id][:3]
    # Increment C: distinguish evidence-backed (confirmed) patterns from the full
    # candidate scan. Additive -- matched_patterns is kept unchanged for dashboards
    # that still read it; new fields let consumers stop treating the scan list as
    # "all confirmed".
    evidence_text = " ".join(pattern_evidence or [])
    confirmed_patterns = [pattern for pattern in (matched_patterns or []) if pattern and pattern in evidence_text]
    if selected_pattern_id and selected_pattern_id not in confirmed_patterns:
        confirmed_patterns.insert(0, selected_pattern_id)
    if not any(
        (
            selected_pattern_id,
            matched_patterns,
            _optional_str(payload.get("pattern_family") or existing.get("pattern_family")),
            _optional_str(payload.get("pattern_tier") or existing.get("pattern_tier")),
            _optional_int(payload.get("pattern_score") or existing.get("pattern_score")),
            _optional_int(payload.get("pattern_match_score") or existing.get("pattern_match_score")),
            _optional_int(payload.get("execution_readiness_score") or existing.get("execution_readiness_score")),
            reference_cases,
            pattern_evidence,
            pattern_bottlenecks,
            diagnostics if include_debug else None,
        )
    ):
        return None
    context = {
        "selected_pattern_id": selected_pattern_id,
        "matched_patterns": matched_patterns,
        "confirmed_patterns": confirmed_patterns or None,
        "candidate_patterns_count": len(matched_patterns) if matched_patterns else 0,
        "top_supporting_patterns": top_supporting_patterns,
        "pattern_family": _optional_str(payload.get("pattern_family") or existing.get("pattern_family")),
        "pattern_scope": _optional_str(payload.get("pattern_scope") or existing.get("pattern_scope")) or "UNIVERSAL",
        "applies_to": _optional_str(payload.get("applies_to") or existing.get("applies_to"))
        or "ALL_PAIRS_IF_CONDITIONS_MATCH",
        "pattern_tier": _optional_str(payload.get("pattern_tier") or existing.get("pattern_tier")),
        "pattern_score": _optional_int(payload.get("pattern_score") or existing.get("pattern_score")),
        "pattern_match_score": _optional_int(payload.get("pattern_match_score") or existing.get("pattern_match_score")),
        "execution_readiness_score": _optional_int(
            payload.get("execution_readiness_score") or existing.get("execution_readiness_score")
        ),
        "reference_cases": reference_cases if _reference_cases_enabled() else None,
        "pattern_evidence": pattern_evidence[:5] if pattern_evidence else None,
        "pattern_bottlenecks": pattern_bottlenecks,
    }
    if include_debug:
        context.update(
            {
                "pattern_search_space": _string_list(payload.get("pattern_search_space"))
                or _string_list(existing.get("pattern_search_space")),
                "pattern_db_candidates_scanned": _optional_int(
                    payload.get("pattern_db_candidates_scanned") or existing.get("pattern_db_candidates_scanned")
                ),
                "pattern_db_exact_matches": _string_list(payload.get("pattern_db_exact_matches"))
                or _string_list(existing.get("pattern_db_exact_matches")),
                "pattern_db_fuzzy_matches": _string_list(payload.get("pattern_db_fuzzy_matches"))
                or _string_list(existing.get("pattern_db_fuzzy_matches")),
                "pattern_match_diagnostics": diagnostics,
            }
        )
    return _clean_context(context)


def _clean_pattern_bottlenecks(values: list[str] | None, *, payload: dict[str, Any]) -> list[str] | None:
    if not values:
        return None
    final_direction = str(payload.get("final_direction") or payload.get("source_final_direction") or "").upper()
    if final_direction == "WAIT":
        final_direction = str(payload.get("source_final_direction") or "").upper()
    cleaned = list(dict.fromkeys(values))
    if final_direction in {"BUY", "SELL"}:
        cleaned = [value for value in cleaned if str(value).upper() != "FINAL_DIRECTION_WAIT"]
    return cleaned or None


def _reference_cases(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw_cases = payload.get("reference_cases")
    if isinstance(raw_cases, list):
        cases = []
        for item in raw_cases:
            case = _reference_case_from_item(item, payload)
            if case is not None:
                cases.append(case)
        if cases:
            return _dedup_reference_cases(cases)

    refs = _string_list_any(payload.get("golden_references")) or _string_list_any(payload.get("golden_reference"))
    cases = []
    for ref in refs or []:
        for symbol in _split_reference_symbols(ref):
            case = _reference_case_from_item({"symbol": symbol}, payload)
            if case is not None:
                cases.append(case)
    return _dedup_reference_cases(cases) or None


def _reference_case_from_item(item: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(item, dict):
        symbol = _optional_str(item.get("symbol") or item.get("pair"))
        if symbol is None:
            return None
        case = dict(item)
    else:
        symbol = _optional_str(item)
        if symbol is None:
            return None
        case = {"symbol": symbol}
    pattern_id = _optional_str(payload.get("selected_pattern_id"))
    case["symbol"] = str(symbol).upper()
    case.setdefault("role", "GOLDEN_REFERENCE_CASE")
    case.setdefault("note", "Reference only; pattern is universal, not pair-locked.")
    if pattern_id:
        case.setdefault("reason", f"historical validation source for {pattern_id}")
    return _clean_context(case)


def _dedup_reference_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for case in cases:
        symbol = _optional_str(case.get("symbol"))
        if symbol is None or symbol in seen:
            continue
        seen.add(symbol)
        deduped.append(case)
    return deduped


def _pair_calibration(payload: dict[str, Any], *, symbol: str | None = None) -> dict[str, Any] | None:
    existing = _dict_value(payload.get("pair_calibration")) or {}
    pair_symbol = str(symbol or payload.get("symbol") or existing.get("symbol") or "").upper()
    if not pair_symbol and not existing:
        return None

    theme_groups = _theme_groups_for_symbol(pair_symbol)
    calibration = {
        "symbol": pair_symbol or None,
        "asset_class": _asset_class_for_symbol(pair_symbol),
        "calibration_role": "CURRENT_PAIR_CONTEXT_ONLY",
        "pip_size": _optional_float(payload.get("pip_size")) or _pip_size_for_symbol(pair_symbol),
        "theme_groups": theme_groups,
        "basket_alignment_required": bool(theme_groups) or None,
        "pair_specific_logic_locked": False,
    }
    calibration.update(existing)

    pair_role = _optional_str(payload.get("pair_role"))
    if pair_role is not None:
        calibration.setdefault("role_hint", pair_role)
    pair_specific = _string_list_any(payload.get("pair_specific_calibration"))
    if pair_specific:
        calibration.setdefault("pair_specific_calibration", pair_specific)
    return _clean_context(calibration)


def _theme_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    context = {
        "theme_alignment": _optional_str(payload.get("theme_alignment")),
        "theme_alignment_status": _theme_alignment_status(payload),
        "alignment_missing_reason": _alignment_missing_reason(payload),
        "jpy_alignment_status": _optional_str(payload.get("jpy_alignment_status")),
        "dual_theme_status": _optional_str(payload.get("dual_theme_status")),
    }
    return _clean_context(context)


def _tradeplan_preview(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not any(
        payload.get(key) is not None
        for key in (
            "target_mode",
            "tp_status",
            "support_ladder_ready",
            "structure_targets_available",
            "tradeplan_context_ready",
            "targets_execution_usable",
            "risk_pips",
        )
    ):
        return None

    levels = {
        "entry_zone": _float_list(payload.get("entry_zone")) or None,
        "sl_safe": _optional_float(payload.get("sl_safe")),
        "tp1": _optional_float(payload.get("tp1")),
        "tp2": _optional_float(payload.get("tp2")),
        "tp3": _optional_float(payload.get("tp3")),
        "tp4": _optional_float(payload.get("tp4")),
    }
    target_mode = _optional_str(payload.get("target_mode"))
    context = {
        "target_mode": target_mode,
        "target_source": _optional_str(payload.get("target_source")),
        "tp_status": _optional_str(payload.get("tp_status")),
        "support_ladder_ready": _optional_bool(payload.get("support_ladder_ready")),
        "resistance_ladder_ready": _optional_bool(payload.get("resistance_ladder_ready")),
        "structure_targets_available": _optional_bool(payload.get("structure_targets_available")),
        "tradeplan_context_ready": _optional_bool(payload.get("tradeplan_context_ready")),
        "targets_execution_usable": _optional_bool(payload.get("targets_execution_usable")),
        "target_block_reason": _optional_str(payload.get("target_block_reason")),
        "risk_pips": _optional_float(payload.get("risk_pips")),
        "min_rr_required": _optional_float(payload.get("min_rr_required")),
        "tp_min_rr": _optional_float(payload.get("tp_min_rr")),
        "provisional_levels": _clean_context(levels)
        if str(target_mode or "").upper() == "PROVISIONAL_RR_FALLBACK"
        else None,
        "structure_levels": _clean_context(levels)
        if str(target_mode or "").upper() in STRUCTURE_TARGET_MODES
        else None,
    }
    return _clean_context(context)


def _execution_gate_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    target_mode = str(payload.get("target_mode") or "").upper()
    target_usable = _optional_bool(payload.get("targets_execution_usable"))
    block_reason = _optional_str(payload.get("block_reason") or payload.get("target_block_reason"))
    if block_reason is None and target_mode == "PROVISIONAL_RR_FALLBACK" and target_usable is False:
        block_reason = "WATCH_ONLY_PENDING_M15_OR_STRUCTURE_TARGET_MISSING"
    context = {
        "entry_permission": _optional_str(payload.get("entry_permission")),
        "chase_allowed": _optional_bool(payload.get("chase_allowed")),
        "management_action": _optional_str(payload.get("management_action")),
        "hold_policy": _optional_str(payload.get("hold_policy")),
        "block_reason": block_reason,
        "valid_for_execution": _optional_bool(payload.get("valid_for_execution")),
        "execution_valid_now": _optional_bool(payload.get("execution_valid_now")),
        "execution_status": _optional_str(payload.get("execution_status")),
        "execution_reason": _optional_str(payload.get("execution_reason")),
    }
    return _clean_context(context)


def _lifecycle_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    context = {
        "cluster_id": _optional_str(payload.get("cluster_id")),
        "signal_id": _optional_str(payload.get("signal_id")),
        "pending_decision_id": _optional_str(payload.get("pending_decision_id")),
        "is_final_signal": _optional_bool(payload.get("is_final_signal")),
        "linked_previous_signal": _optional_str(payload.get("linked_previous_signal")),
        "previous_signal_status": _optional_str(payload.get("previous_signal_status")),
        "lifecycle_status": _optional_str(payload.get("lifecycle_status")),
        "decision_watch_type": _optional_str(payload.get("decision_watch_type")),
        "decision_update_trigger": _optional_str(payload.get("decision_update_trigger")),
        "next_action": _optional_str(payload.get("next_action")),
        "pending_age_seconds": _optional_float(payload.get("pending_age_seconds")),
    }
    return _clean_context(context)


def _pattern_debug_payload(
    source_payload: dict[str, Any],
    production_payload: dict[str, Any],
) -> dict[str, Any] | None:
    pattern_context = _dict_value(source_payload.get("pattern_context")) or {}
    diagnostics = _dict_value(source_payload.get("pattern_match_diagnostics")) or _dict_value(
        pattern_context.get("pattern_match_diagnostics")
    )
    exact_matches = _string_list(source_payload.get("pattern_db_exact_matches")) or _string_list(
        pattern_context.get("pattern_db_exact_matches")
    )
    fuzzy_matches = _string_list(source_payload.get("pattern_db_fuzzy_matches")) or _string_list(
        pattern_context.get("pattern_db_fuzzy_matches")
    )
    patterns_scanned = _optional_int(source_payload.get("pattern_db_candidates_scanned")) or _optional_int(
        pattern_context.get("pattern_db_candidates_scanned")
    )
    semantic_hits = None
    candidate_scores_top = None
    search_mode = None
    if diagnostics:
        exact_matches = exact_matches or _string_list(diagnostics.get("exact_matches"))
        fuzzy_matches = fuzzy_matches or _string_list(diagnostics.get("fuzzy_matches"))
        patterns_scanned = patterns_scanned or _optional_int(diagnostics.get("patterns_scanned"))
        semantic_hits = _dict_value(diagnostics.get("semantic_hits"))
        candidate_scores_top = _dict_value(diagnostics.get("candidate_scores_top"))
        search_mode = _optional_str(diagnostics.get("search_mode"))
    if not any((diagnostics, exact_matches, fuzzy_matches, patterns_scanned, semantic_hits, candidate_scores_top)):
        return None

    sidecar = {
        "event": "pattern_match_debug_json",
        "schema_version": "1.0",
        "symbol": source_payload.get("symbol"),
        "signal_id": production_payload.get("signal_id") or source_payload.get("signal_id"),
        "cluster_id": source_payload.get("cluster_id"),
        "pending_decision_id": source_payload.get("pending_decision_id"),
        "selected_pattern_id": source_payload.get("selected_pattern_id") or pattern_context.get("selected_pattern_id"),
        "search_mode": search_mode,
        "patterns_scanned": patterns_scanned,
        "exact_matches": exact_matches,
        "fuzzy_matches": fuzzy_matches,
        "candidate_scores_top": candidate_scores_top,
        "semantic_hits": semantic_hits,
    }
    return _clean_context(sidecar)


def _theme_alignment_status(payload: dict[str, Any]) -> str | None:
    theme_alignment = _optional_str(payload.get("theme_alignment"))
    status = _optional_str(payload.get("theme_alignment_status"))
    if theme_alignment is None and (status is None or status.upper() in {"ALIGNED", "UNKNOWN"}):
        return "NOT_AVAILABLE"
    return status


def _alignment_missing_reason(payload: dict[str, Any]) -> str | None:
    raw = _optional_str(payload.get("alignment_missing_reason"))
    parts = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    theme_alignment = _optional_str(payload.get("theme_alignment"))
    status = _theme_alignment_status(payload)
    if theme_alignment is None and status == "NOT_AVAILABLE":
        basket_reason = "basket_snapshot_missing_or_not_computed"
        if basket_reason not in parts and "theme_alignment" not in parts:
            parts.insert(0, basket_reason)
    return ",".join(parts) if parts else None


def _string_list_any(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            items.extend(_split_reference_symbols(str(item)))
        return items or None
    return _split_reference_symbols(str(value)) or None


def _split_reference_symbols(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    symbols: list[str] = []
    for chunk in text.replace(",", "/").split("/"):
        symbol = chunk.strip().upper()
        if symbol:
            symbols.append(symbol)
    return symbols


def _theme_groups_for_symbol(symbol: str) -> list[str] | None:
    if len(symbol) < 6:
        return None
    base = symbol[:3]
    quote = symbol[3:6]
    if base in {"XAU", "XAG"}:
        return ["USD_BASKET", "METAL_SESSION"]
    if base.isalpha() and quote.isalpha():
        return [f"{base}_BASKET", f"{quote}_BASKET"]
    return None


def _asset_class_for_symbol(symbol: str) -> str | None:
    if not symbol:
        return None
    if symbol.startswith(("XAU", "XAG")):
        return "METAL"
    if len(symbol) >= 6 and symbol[:6].isalpha():
        return "FX"
    return None


def _pip_size_for_symbol(symbol: str) -> float | None:
    if not symbol:
        return None
    if symbol.startswith(("XAU", "XAG")):
        return 0.01
    quote = symbol[3:6] if len(symbol) >= 6 else ""
    return 0.01 if quote == "JPY" else 0.0001


def _clean_context(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_item = _clean_context(item)
            if cleaned_item is None or cleaned_item == [] or cleaned_item == {}:
                continue
            cleaned[key] = cleaned_item
        return cleaned or None
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            cleaned_item = _clean_context(item)
            if cleaned_item is None or cleaned_item == [] or cleaned_item == {}:
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list or None
    return value


def _dict_value(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _dict_list(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    values = [dict(item) for item in value if isinstance(item, dict)]
    return values


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    values = [str(item) for item in value if str(item or "").strip()]
    return values


def _execution_contract_complete(payload: dict[str, Any]) -> bool:
    zones = payload.get("structure_zones")
    invalidation = payload.get("invalidation_rules")
    targets = payload.get("targets")
    execution_quality = payload.get("execution_quality")
    phase_coherence = payload.get("phase_coherence")
    signal_expiry = payload.get("signal_expiry")
    return bool(
        payload.get("valid_for_execution") is True
        and payload.get("tradeplan_valid") is True
        and payload.get("execution_valid_now") is True
        and _optional_float(payload.get("selected_sl")) is not None
        and _optional_float(payload.get("selected_risk_pips") or payload.get("risk_pips")) is not None
        and _optional_float(payload.get("tp_min_rr")) is not None
        and isinstance(zones, dict)
        and _optional_float(zones.get("key_resistance")) is not None
        and _optional_float(zones.get("key_support")) is not None
        and isinstance(invalidation, dict)
        and _optional_float(invalidation.get("hard_invalid_level")) is not None
        and isinstance(targets, list)
        and bool(targets)
        and isinstance(execution_quality, dict)
        and execution_quality.get("spread_normal") is True
        and isinstance(phase_coherence, dict)
        and phase_coherence.get("status") == "EXECUTION_COMPATIBLE"
        and isinstance(signal_expiry, dict)
        and _optional_str(signal_expiry.get("expires_at_utc")) is not None
    )


def _tp1_rr_meets_minimum(payload: dict[str, Any]) -> bool:
    tp1_rr = _optional_float(payload.get("tp1_rr"))
    return tp1_rr is not None and tp1_rr >= MIN_EXECUTABLE_TP1_RR


def _validated_direction(payload: dict[str, Any]) -> str | None:
    explicit = _optional_str(payload.get("validated_direction"))
    final_direction = str(payload.get("final_direction") or "").upper()
    status = str(payload.get("status") or "")
    direction_contract_valid = bool(
        payload.get("valid_for_execution", False)
        or payload.get("signal_valid", False)
        or payload.get("direction_valid", False)
        or (
            status in TERMINAL_VALID_SIGNAL_STATUSES
            and bool(payload.get("signal_valid") or payload.get("direction_valid"))
        )
    )
    if (
        explicit
        and explicit.upper() in {"BUY", "SELL"}
        and final_direction in {"BUY", "SELL"}
        and direction_contract_valid
    ):
        return explicit.upper()
    if final_direction in {"BUY", "SELL"} and direction_contract_valid:
        return final_direction
    return None


def _watch_direction(
    payload: dict[str, Any],
    *,
    status: str,
    validated_direction: str | None,
) -> str | None:
    explicit = _optional_str(payload.get("watch_direction"))
    if explicit and explicit.upper() in {"BUY", "SELL"}:
        return explicit.upper()
    if validated_direction in {"BUY", "SELL"}:
        return None
    candidate = str(payload.get("candidate_direction") or "").upper()
    if candidate in {"BUY", "SELL"} and (
        _is_watch_status(status)
        or _is_decision_update_status(status)
        or str(payload.get("final_direction") or "").upper() == "WAIT"
    ):
        return candidate
    return None


def _direction_validation_status(
    payload: dict[str, Any],
    *,
    status: str,
    validated_direction: str | None,
) -> str:
    if validated_direction in {"BUY", "SELL"} and bool(payload.get("valid_for_execution", False)):
        return "VALIDATED_EXECUTION"
    if validated_direction in {"BUY", "SELL"} and status in TERMINAL_VALID_SIGNAL_STATUSES:
        return "VALIDATED_DIRECTION_EXECUTION_DEFERRED"
    if status.endswith("_BY_ABSORPTION"):
        return "TIMING_VALID_STRUCTURE_PENDING"
    if _is_watch_status(status) or _is_decision_update_status(status):
        return "WATCH_ONLY_PENDING_CONFIRMATION"
    return "UNVALIDATED_WAIT"


def _generated_signal_id(
    *,
    symbol: str,
    direction: str | None,
    status: str,
    signal_time: str,
    is_watch: bool,
    is_decision_update: bool,
) -> str | None:
    compact_time = _compact_signal_time(signal_time)
    if not symbol or not compact_time:
        return None
    label = str(direction or "WAIT").upper()
    if is_decision_update:
        label = f"{label}_DECISION"
    elif is_watch:
        label = f"{label}_WATCH"
    elif label not in {"BUY", "SELL"}:
        label = str(status or "SIGNAL").upper()
    return f"{symbol}_{label}_{compact_time}"


def _compact_signal_time(value: str) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 14:
        return None
    return f"{digits[:8]}_{digits[8:14]}"


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
