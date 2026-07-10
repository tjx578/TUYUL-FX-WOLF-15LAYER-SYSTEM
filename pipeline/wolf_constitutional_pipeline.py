"""
Wolf Constitutional Pipeline v8.0 -- UNIFIED SUPER PIPELINE

Merged from:
  - pipeline/wolf_constitutional_pipeline.py  (Constitutional v7.4r∞)
  - analysis/orchestrators/wolf_sovereign_pipeline.py (Sovereign -- deleted)

This is the SOLE pipeline orchestrator for the Wolf 15-Layer System.
No other pipeline exists. All analysis flows through this single entry point.

══════════════════════════════════════════════════════════════════════
4 Core Unified Modules × 15 Analytical Layers × Complete Pipeline
══════════════════════════════════════════════════════════════════════

Core Modules:
    1. core_cognitive_unified.py    -> Emotion, Regime, Risk, TWMS, SMC
    2. core_fusion_unified.py       -> Fusion, MTF, Confluence, WLWCI, MC
    3. core_quantum_unified.py      -> TRQ3D, Decision Engine, Scenario Matrix
    4. core_reflective_unified.py   -> TII, FRPC, Wolf Discipline, Evolution

15-Layer Architecture:
    ZONA 1 - Perception & Context   : L1, L2, L3
    ZONA 2 - Confluence & Scoring   : L4, L5, L6
    ZONA 3 - Probability & Validation: L7, L8, L9
    ZONA 4 - Execution & Decision   : L10, L11, L12 (SOLE AUTHORITY)
    ZONA 5 - Meta & Reflective      : L13, L14, L15

Execution order (CRITICAL -- 8 phases):
    Phase 1: L1, L2, L3 (Perception -- always-forward, degradation recorded)
    Phase 2: L4, L5 (Confluence & Psychology -- always-forward, depend on L1-L3)
    Phase 3: L7, L8, L9 (Probability & Validation -- depend on L4/L5)
    Phase 4: L11 -> L6 -> L10 (Execution + Risk -- L11 BEFORE L6!)
    Phase 5: Build synthesis -> 9-Gate Check -> L12 verdict (SOLE AUTHORITY)
    Phase 6: Two-pass L13 governance (baseline -> meta -> refined)
    Phase 7: Sovereignty enforcement (drift detection + verdict downgrade)
    Phase 8: L14 JSON export + final result assembly

Runtime model (capital-protection first):
    SEMI-PARALLEL ALWAYS-FORWARD DAG
    batch_1 -> sync barrier -> batch_2 -> sync barrier -> ...
    Layers are scoring systems, not decision gates.
    Degradation is recorded and forwarded; L12 is sole verdict authority.

Merged improvements over v7.4r∞:
    ✓ Two-pass L13 governance (from Sovereign pipeline)
    ✓ Drift-based sovereignty enforcement with verdict downgrade
    ✓ Extracted L13ReflectiveEngine + L15MetaSovereigntyEngine
    ✓ system_metrics / safe_mode support for verdict engine
    ✓ build_l12_synthesis() as standalone importable function
    ✓ PipelineResult dataclass with dict backward compatibility

Authority: Layer-12 is the SOLE CONSTITUTIONAL AUTHORITY.
Discipline: Wolf 30-Point + F-T-P Trias.
Integrity: TIIₛᵧₘ ≥ 0.93 | FRPC ≥ 0.96 | RR ≥ 1:2.0
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
import time

# stdlib imports
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from types import SimpleNamespace
from typing import Any, TypedDict, cast

from analysis.basket_direction_validator import validate_basket_direction
from analysis.clean_block_watch_router import emit_signal_watch_promotion_diagnostic
from analysis.htf_structure_snapshot import (
    HTFStructureSnapshotResolver,
    emit_htf_structure_snapshot,
)
from analysis.market_context_validator import MarketContext, validate_market_context
from analysis.microboost_event_log import (
    build_microboost_intel_event,
    build_microboost_table_events,
    emit_microboost_intel,
    emit_microboost_table_event,
)
from analysis.reflex_emc import EMCFilter
from analysis.reflex_gate import ReflexGateController
from analysis.reflex_multitf import compute_multitf_rqi
from analysis.reflex_rqi import compute_rqi, latency_decay
from analysis.signal_block_finalizer import SignalBlockFinalizer
from analysis.signal_decision_source_guard import convert_to_signal_pressure_state, route_decision_or_pressure
from analysis.signal_json_emitter import SignalJsonEmitter, build_signal_json_event
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter
from analysis.signal_lifecycle_manager import (
    SignalLifecycleManager,
    record_active_if_execution_grade,
    shadow_preview_event,
)
from analysis.signal_pressure_state_emitter import emit_signal_pressure_state
from analysis.signal_throttle_followthrough_score import (
    followthrough_context_for_symbol,
    signal_throttle_followthrough_score_log_payload,
)
from analysis.signal_throttle_fusion_router import emit_signal_throttle_fusion_v3_diagnostic
from analysis.signal_throttle_intelligence import (
    classify_allowed_signal,
    emit_signal_throttle_intel,
)
from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer
from analysis.signal_throttle_pressure_tier import (
    pressure_priority_context_for_symbol,
    pressure_tier_snapshot_log_payload,
)
from analysis.source_lineage_guard import (
    DEFAULT_MICROBOOST_SOURCE_DIAGNOSTIC_PREFIX,
    DEFAULT_MICROBOOST_STALE_DIAGNOSTIC_PREFIX,
    DEFAULT_SIGNAL_THROTTLE_FRESHNESS_PREFIX,
    DEFAULT_SIGNAL_THROTTLE_OBSERVABILITY_LOGGER,
    DEFAULT_SIGNAL_THROTTLE_STATE_SNAPSHOT_PREFIX,
    DEFAULT_SOURCE_FRESHNESS_SECONDS,
    diagnostic_prefix,
    emit_signal_throttle_state_snapshot,
    emit_source_guard_diagnostic,
    guard_microboost_source,
    signal_throttle_state_snapshot_payload,
    signal_watch_source_diagnostic,
)
from analysis.universe_ranking import UniverseRankingEngine
from config_loader import CONFIG

# third-party imports
# import ...
# local imports
from constitution.l12_router_evaluator import L12Input, L12RouterEvaluator
from constitution.verdict_engine import generate_l12_verdict
from contracts.shadow_hook import begin_shadow_session, finalize_shadow_session
from core.dag_engine import DagEngine
from core.metrics import (
    LAYER_LATENCY,
    SIGNAL_THROTTLED,
    TICK_TO_VERDICT_LATENCY,
    UNIVERSE_RANKING_POSITION,
    UNIVERSE_RANKING_SCORE,
    VERDICT_PATH_EVENT_TOTAL,
)
from core.tracing import layer_span
from pipeline.engines import L13ReflectiveEngine, L15MetaSovereigntyEngine
from pipeline.execution_map import build_execution_map
from pipeline.phases.assembly import build_l14_json
from pipeline.phases.gates import evaluate_9_gates
from pipeline.phases.metrics_recorder import record_pipeline_metrics
from pipeline.phases.synthesis import build_l12_synthesis, resolve_trade_direction
from pipeline.phases.vault import compute_vault_sync
from pipeline.result import PipelineResult
from pipeline.warmup_utils import normalize_warmup  # noqa: E402  # delayed import to avoid circular dependency


class _SpreadQuality(TypedDict):
    spread_normal: bool | None
    spread_pips: float | None
    max_allowed_spread_pips: float | None


try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


# ─── GMT+8 timezone for timestamps ───
_TZ_GMT8 = timezone(timedelta(hours=8))

# Per-layer execution timeout (seconds).  Layers that exceed this are
# aborted and recorded as FATAL_ERROR so the pipeline can fail fast.
_LAYER_TIMEOUT_SEC: float = 30.0

# Confidence-band → numeric [0, 1] mapping for L12 router synthesis_score.
# generate_l12_verdict() returns "confidence" as a band string
# ("LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH"), so a naked float() would
# raise ValueError. Thresholds mirror _wolf30_to_confidence midpoints.
_CONFIDENCE_BAND_TO_SCORE: dict[str, float] = {
    "LOW": 0.25,
    "MEDIUM": 0.50,
    "HIGH": 0.75,
    "VERY_HIGH": 0.95,
}


def _emit_canary_event(message: str) -> None:
    """Promote canary sentinel logs in production so Railway captures them."""
    app_env = os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower()
    if app_env == "production":
        logger.warning(message)
        return
    logger.info(message)


def _coerce_confidence_to_score(value: Any) -> tuple[float, str | None]:
    """Coerce a verdict-engine confidence (band string or numeric) to [0, 1].

    Returns (score, warning_code). warning_code is non-None only when the
    input is not directly coercible and a fallback was used — callers can
    surface it for audit instead of silently defaulting to 0.0.
    """
    if isinstance(value, bool):
        # Treat bools as unmappable to avoid truthy-ambiguity.
        return 0.0, "PHASE5_NON_NUMERIC_CONFIDENCE"
    if isinstance(value, (int, float)):
        # Clamp to valid [0, 1] range.
        return max(0.0, min(1.0, float(value))), None
    if isinstance(value, str):
        key = value.strip().upper()
        if key in _CONFIDENCE_BAND_TO_SCORE:
            return _CONFIDENCE_BAND_TO_SCORE[key], None
        # Tolerate numeric-looking strings defensively.
        try:
            return max(0.0, min(1.0, float(value))), None
        except (TypeError, ValueError):
            return 0.0, "PHASE5_NON_NUMERIC_CONFIDENCE"
    return 0.0, "PHASE5_NON_NUMERIC_CONFIDENCE"


def _module_attr(module_name: str, attr_name: str) -> Any:
    """Load a repo-local attribute lazily to keep editor resolution tolerant."""
    return import_module(module_name).__dict__[attr_name]


def _parse_heartbeat_timestamp(raw: Any) -> float | None:
    """Extract a valid heartbeat timestamp from a Redis JSON payload."""
    if raw is None:
        return None

    import orjson as _orjson  # noqa: PLC0415

    payload: Any = raw
    if isinstance(raw, str | bytes | bytearray):
        with contextlib.suppress(Exception):
            payload = _orjson.loads(raw)

    if isinstance(payload, dict):
        ts = _coerce_timestamp_to_epoch(payload.get("ts"))
        return ts if ts is not None and ts > 0 else None

    ts = _coerce_timestamp_to_epoch(payload)
    return ts if ts is not None and ts > 0 else None


def _coerce_timestamp_to_epoch(value: Any) -> float | None:
    """Convert numeric/ISO timestamp variants to epoch seconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            with contextlib.suppress(ValueError):
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.timestamp()
    return None


# ══════════════════════════════════════════════════════════════
#  STANDALONE SYNTHESIS BUILDER
#  Delegated to pipeline.phases.synthesis.build_l12_synthesis
# ══════════════════════════════════════════════════════════════


def _normalized_watch_pending_decision_id(symbol: str, raw: str, *, cluster_id: str | None = None) -> str:
    symbol_key = str(symbol or "").upper()
    token = str(raw or cluster_id or "WATCH").strip()
    if not symbol_key:
        return f"{token or 'WATCH'}_M15_DECISION"

    if token.upper().endswith("_M15_DECISION"):
        token = token[: -len("_M15_DECISION")]

    duplicate_prefix = f"{symbol_key}_{symbol_key}_"
    if token.upper().startswith(duplicate_prefix):
        token = f"{symbol_key}_{token[len(duplicate_prefix):]}"
    elif not token.upper().startswith(f"{symbol_key}_"):
        token = f"{symbol_key}_{token or 'WATCH'}"
    return f"{token}_M15_DECISION"


class WolfConstitutionalPipeline:
    """
    Wolf 15-Layer Constitutional Pipeline v8.0 -- Unified Super Pipeline.

    Merged from Constitutional v7.4r∞ + Sovereign governance features.
    This is the ONLY entry point for analysis in the entire system.
    Runtime is a semi-parallel always-forward DAG with batch barriers.
    Independent nodes inside the same DAG batch may run concurrently, while
    cross-batch progression is strictly synchronized (batch -> barrier -> batch).
    Layer-12 is the SOLE decision authority (Constitutional Verdict).

    Key features:
        - 9-Gate Constitutional Check
        - Two-pass L13 governance (baseline -> real meta -> refined)
        - Drift-based sovereignty enforcement with verdict downgrade
        - L14 JSON export + L15 meta synthesis
        - VIX regime + macro monthly regime integration
        - system_metrics / safe_mode support
    """

    VERSION = "v8.0"

    # Minimum candle bars per timeframe before analysis is allowed.
    # Prevents garbage indicator outputs during the first minutes
    # after system startup.
    # Note: M15 is excluded — it arrives from WS ticks, not REST warmup.
    # W1/MN are included because L1 regime context depends on them.
    # These are pipeline-gate minimums, intentionally lower than
    # config/finnhub.yaml min_bars (which are fetch targets).
    WARMUP_MIN_BARS: dict[str, int] = {
        "H1": 30,
        "H4": 10,
        "D1": 5,
        "W1": 5,
        "MN": 2,
    }

    # Avoid log storms when a symbol remains degraded for long periods.
    DQ_WARNING_LOG_INTERVAL_SEC: float = 900.0

    # Avoid warmup reject error storms during startup/reconnect windows.
    WARMUP_WARNING_LOG_INTERVAL_SEC: float = 900.0

    # ── Feature flags (env-driven, safe rollout) ──────────────────
    ENABLE_LFS_SOFTENER: bool = os.getenv("ENABLE_LFS_SOFTENER", "0") == "1"

    def __init__(self) -> None:
        """Initialize with lazy loading to avoid circular imports."""
        super().__init__()
        from context.live_context_bus import LiveContextBus  # noqa: PLC0415

        # Shared context bus (singleton) for warmup checks & vault health
        self._context_bus = LiveContextBus()

        # Layer analyzers (lazy-loaded)
        self._l1 = None
        self._l2 = None
        self._l3 = None
        self._l4 = None
        self._l5 = None
        self._l6 = None
        self._l7 = None
        self._l8 = None
        self._l9 = None
        self._l10 = None
        self._l11 = None

        # Signal conditioning (Phase-3 pre-L7)
        from analysis.signal_conditioner import SignalConditioner  # noqa: PLC0415

        _cond_cfg = cast(
            dict[str, Any],
            CONFIG.get("finnhub", {}).get("signal_conditioning", {}),
        )
        self._signal_conditioner = SignalConditioner.from_config(_cond_cfg)

        # Macro analyzers
        self._macro = None
        self._macro_vol = None

        # Governance engines (lazy-loaded for consistency with L1-L11)
        self._l13_engine: L13ReflectiveEngine | None = None
        self._l15_engine: L15MetaSovereigntyEngine | None = None

        # Signal rate throttle (default: max 3 EXECUTE per symbol in 5 minutes)
        try:
            throttle_max_signals = max(1, int(os.getenv("SIGNAL_THROTTLE_MAX_SIGNALS", "3")))
        except (TypeError, ValueError):
            throttle_max_signals = 3
        throttle_window_seconds = self._parse_env_float("SIGNAL_THROTTLE_WINDOW_SECONDS", 300.0)
        intel_direction_bridge_window_seconds = self._parse_env_float(
            "SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", 600.0
        )
        signal_throttle_cls = _module_attr("constitution.signal_throttle", "SignalThrottle")
        self._signal_throttle = signal_throttle_cls(
            max_signals=throttle_max_signals,
            window_seconds=throttle_window_seconds,
        )
        try:
            fragmented_min_unique_pairs = max(
                1,
                int(os.getenv("SIGNAL_THROTTLE_INTEL_FRAGMENTED_MIN_UNIQUE_PAIRS", "5")),
            )
        except (TypeError, ValueError):
            fragmented_min_unique_pairs = 5
        try:
            throttle_intel_max_events = max(100, int(os.getenv("SIGNAL_THROTTLE_INTEL_MAX_EVENTS", "20000")))
        except (TypeError, ValueError):
            throttle_intel_max_events = 20000
        self._signal_throttle_live_analyzer = SignalThrottleLiveAnalyzer(
            latest_window_minutes=int(self._parse_env_float("SIGNAL_THROTTLE_INTEL_LATEST_WINDOW_MINUTES", 60.0)),
            retention_seconds=int(self._parse_env_float("SIGNAL_THROTTLE_INTEL_RETENTION_SECONDS", 7200.0)),
            max_events=throttle_intel_max_events,
            active_block_ttl_seconds=int(
                self._parse_env_float("SIGNAL_THROTTLE_INTEL_ACTIVE_BLOCK_TTL_SECONDS", 300.0)
            ),
            min_clean_block_minutes=self._parse_env_float("SIGNAL_THROTTLE_INTEL_MIN_CLEAN_BLOCK_MINUTES", 5.0),
            microboost_window_minutes=int(
                self._parse_env_float("SIGNAL_THROTTLE_INTEL_MICROBOOST_WINDOW_MINUTES", 15.0)
            ),
            allowed_quorum_window_seconds=int(
                self._parse_env_float("SIGNAL_THROTTLE_INTEL_ALLOWED_QUORUM_WINDOW_SECONDS", 120.0)
            ),
            fragmented_min_unique_pairs=fragmented_min_unique_pairs,
            fragmented_max_clean_block_minutes=self._parse_env_float(
                "SIGNAL_THROTTLE_INTEL_FRAGMENTED_MAX_CLEAN_BLOCK_MINUTES",
                1.0,
            ),
        )
        self._last_microboost_log_key: tuple[Any, ...] | None = None
        self._last_microboost_role_key_by_symbol: dict[str, tuple[Any, ...]] = {}
        self._last_microboost_table_emit_at: float | None = None
        self._emitted_microboost_table_keys: set[tuple[Any, ...]] = set()
        # Root#1/case-c bridge: latest allowed SignalThrottleIntel direction per
        # symbol. Read only by the flag-guarded non-execute pressure canary path.
        self._signal_throttle_intel_direction_cache: dict[str, tuple[str, datetime]] = {}
        # P1B shadow-only active-signal tracker (symbol -> last execution-grade direction).
        # Populated and read ONLY when SIGNAL_LIFECYCLE_MANAGER_SHADOW_ENABLED=true.
        self._shadow_active_directions: dict[str, str] = {}
        # Increment H1 — HTF Structure Snapshot (flag-guarded, default OFF).
        # Bound to the same candle store the pipeline populates so the snapshot
        # reads exactly the bars analysis sees. Non-executable observability only.
        self._htf_snapshot_resolver = HTFStructureSnapshotResolver(candle_source=self._context_bus)
        self._last_htf_snapshot_key: dict[str, tuple[Any, ...]] = {}
        self._last_htf_snapshot_emit_at: dict[str, float] = {}
        self._last_signal_pressure_state_emit: dict[str, tuple[str, float]] = {}
        self._last_no_trade_pressure_decision_at: dict[str, float] = {}
        self._last_allowed_quorum_decision_at: dict[str, float] = {}
        self._signal_lifecycle_manager = SignalLifecycleManager()
        self._signal_block_finalizer = SignalBlockFinalizer(
            enabled=os.getenv("SIGNAL_BLOCK_FINALIZER_ENABLED", "true").strip().lower() == "true",
            idle_finalize_seconds=self._parse_env_float("SIGNAL_BLOCK_IDLE_FINALIZE_SECONDS", 75.0),
            hard_finalize_seconds=self._parse_env_float("SIGNAL_BLOCK_HARD_FINALIZE_SECONDS", 300.0),
            expires_after_m15_bars=int(self._parse_env_float("SIGNAL_BLOCK_PENDING_EXPIRES_AFTER_M15_BARS", 3.0)),
            min_rr_valid=self._parse_env_float("SIGNAL_JSON_MIN_RR_VALID", 1.5),
            tp1_rr_required=self._parse_env_float("SIGNAL_JSON_TP1_RR_REQUIRED", 1.5),
            counter_entry_risk_multiplier=self._parse_env_float("SIGNAL_JSON_COUNTER_ENTRY_RISK_MULTIPLIER", 0.5),
            counter_entry_expiry_minutes=int(self._parse_env_float("SIGNAL_JSON_COUNTER_ENTRY_EXPIRY_MINUTES", 30.0)),
            allow_rr_fallback=os.getenv("SIGNAL_JSON_ALLOW_RR_FALLBACK", "true").strip().lower() == "true",
        )
        log_compact_mode = self._signal_log_compact_mode_enabled()
        self._signal_json_emitter = SignalJsonEmitter(
            enabled=os.getenv("SIGNAL_JSON_LOG_ENABLED", "true").strip().lower() == "true",
            prefix=os.getenv("SIGNAL_JSON_LOG_PREFIX", "[SignalJSON]"),
            watch_prefix=os.getenv("SIGNAL_WATCH_JSON_LOG_PREFIX", "[SignalWatchJSON]"),
            decision_update_prefix=os.getenv(
                "SIGNAL_DECISION_UPDATE_JSON_LOG_PREFIX",
                "[SignalDecisionUpdateJSON]",
            ),
            dedup_ttl_seconds=int(self._parse_env_float("SIGNAL_JSON_DEDUP_TTL_SECONDS", 300.0)),
            emit_watch=os.getenv("SIGNAL_JSON_EMIT_WATCH", "true").strip().lower() == "true",
            emit_conditional=os.getenv("SIGNAL_JSON_EMIT_CONDITIONAL", "true").strip().lower() == "true",
            emit_valid=os.getenv("SIGNAL_JSON_EMIT_VALID", "true").strip().lower() == "true",
            require_market_context=(
                os.getenv("SIGNAL_JSON_EMIT_ONLY_WITH_MARKET_CONTEXT", "true").strip().lower() == "true"
            ),
            watch_transition_only=(os.getenv("SIGNAL_WATCH_EMIT_ON_TRANSITION_ONLY", "true").strip().lower() == "true"),
            watch_update_interval_seconds=self._parse_env_float("SIGNAL_WATCH_UPDATE_INTERVAL_SECONDS", 15.0),
            watch_emit_on_change_only=self._parse_env_bool(
                "SIGNAL_WATCH_EMIT_ON_CHANGE_ONLY",
                log_compact_mode,
            ),
            watch_suppress_identical=self._parse_env_bool("SIGNAL_WATCH_SUPPRESS_IDENTICAL", log_compact_mode),
            watch_cluster_dedup_enabled=self._parse_env_bool(
                "SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED",
                log_compact_mode,
            ),
            watch_bucket_minutes=self._parse_env_float_list(
                "SIGNAL_WATCH_BUCKET_EMIT_MINUTES",
                (5.0, 10.0, 15.0, 20.0, 30.0),
            ),
            strict_lifecycle=os.getenv("SIGNAL_JSON_STRICT_LIFECYCLE", "true").strip().lower() == "true",
            require_parent_watch=os.getenv("SIGNAL_JSON_REQUIRE_PARENT_WATCH", "false").strip().lower() == "true",
            allow_direct_bypass=os.getenv("SIGNAL_JSON_ALLOW_DIRECT_BYPASS", "true").strip().lower() == "true",
            require_final_market_structure=(
                os.getenv("SIGNAL_JSON_REQUIRE_FINAL_MARKET_STRUCTURE", "false").strip().lower() == "true"
            ),
            require_theme_alignment=os.getenv("SIGNAL_JSON_REQUIRE_THEME_ALIGNMENT", "false").strip().lower() == "true",
            theme_conflict_downgrade=os.getenv("SIGNAL_JSON_THEME_CONFLICT_DOWNGRADE", "false").strip().lower()
            == "true",
            min_rr_valid=self._parse_env_float("SIGNAL_JSON_MIN_RR_VALID", 1.5),
            cooldown_m15_bars_after_active_signal=int(
                self._parse_env_float("SIGNAL_JSON_COOLDOWN_M15_BARS_AFTER_ACTIVE_SIGNAL", 1.0)
            ),
            decision_dedup_enabled=os.getenv("SIGNAL_DECISION_DEDUP_ENABLED", "true").strip().lower() == "true",
            decision_state_monotonic=os.getenv("SIGNAL_DECISION_STATE_MONOTONIC", "true").strip().lower() == "true",
            require_terminal_decision_update=(
                os.getenv("SIGNAL_JSON_REQUIRE_TERMINAL_DECISION_UPDATE", "true").strip().lower() == "true"
            ),
            compact_production=self._parse_env_bool(
                "SIGNAL_JSON_COMPACT_PRODUCTION",
                not self._parse_env_bool("SIGNAL_JSON_VERBOSE_OBSERVABILITY", False),
            ),
            emit_pattern_debug=os.getenv("SIGNAL_JSON_PATTERN_DEBUG_ENABLED", "false").strip().lower() == "true",
            pattern_debug_prefix=os.getenv("SIGNAL_PATTERN_DEBUG_JSON_LOG_PREFIX", "[PatternMatchDebugJSON]"),
        )
        self._signal_json_gate_adapter = SignalJsonGateAdapter.from_env()
        self._governance_now_ts: float | None = None
        _emit_canary_event(
            "event=signal_throttle_config symbol=* authority=SIGNAL_THROTTLE "
            f"max_signals={throttle_max_signals} window_seconds={throttle_window_seconds:.0f} "
            f"signal_throttle_window_seconds={throttle_window_seconds:.0f} "
            f"intel_direction_bridge_window_seconds={intel_direction_bridge_window_seconds:.0f} "
            f"error_log_min_interval_seconds={self._signal_throttle.throttle_error_log_min_interval_seconds:.0f}"
        )
        self._market_context_guard_enabled = os.getenv("MARKET_CONTEXT_EXECUTE_GUARD_ENABLED", "1") != "0"
        guard_mode = os.getenv("MARKET_CONTEXT_EXECUTE_GUARD_MODE", "audit").strip().lower()
        self._market_context_guard_mode = guard_mode if guard_mode in {"audit", "block"} else "audit"
        try:
            self._market_context_spread_multiplier = max(
                1.0,
                float(os.getenv("MARKET_CONTEXT_MAX_SPREAD_MULTIPLIER", "2.5")),
            )
        except (TypeError, ValueError):
            self._market_context_spread_multiplier = 2.5
        _emit_canary_event(
            "event=market_context_guard_config symbol=* authority=MARKET_CONTEXT "
            f"enabled={self._market_context_guard_enabled} mode={self._market_context_guard_mode} "
            f"spread_multiplier={self._market_context_spread_multiplier:.2f}"
        )

        settings = CONFIG.get("settings", {})
        self._rqi_sigma_sec = float(settings.get("rqi_sigma_sec", settings.get("loop_interval_sec", 60)))

        # ── RQI Enhancement: EMC filter + Gate controller ─────────
        self._emc_filter = EMCFilter(
            decay=float(settings.get("rqi_emc_decay", 0.8)),
            sigma_base=self._rqi_sigma_sec,
        )
        self._reflex_gate = ReflexGateController(
            open_threshold=float(settings.get("rqi_gate_open", 0.85)),
            caution_threshold=float(settings.get("rqi_gate_caution", 0.70)),
            caution_lot_scale=float(settings.get("rqi_gate_caution_lot", 0.5)),
        )

        # Engine Enrichment Layer (Phase 2.5 — 9 facade engines)
        self._enrichment: Any = None  # lazy-loaded

        # Universe ranking / conditional watchlist (advisory before L12)
        self._universe_ranking = UniverseRankingEngine()

        # Legacy FTA Enricher — WOLF ARSENAL v4.0 advisory adapter (pre-L10)
        self._legacy_fta: Any = None  # lazy-loaded

        # Lorentzian Field Stabilizer — advisory enricher (Phase 2.5)
        self._lorentzian: Any = None  # lazy-loaded
        self._lfs_history: dict[str, dict[str, float]] = {}  # per-symbol α–β–γ snapshots

        # Vault health checker (lazy-initialized on first use)
        self._vault_checker: Any = None  # type: VaultHealthChecker | None

        # Per-symbol data quality warning state for log throttling.
        self._dq_warning_state: dict[str, dict[str, Any]] = {}

        # Per-symbol warmup warning state for log throttling.
        self._warmup_warning_state: dict[str, dict[str, Any]] = {}

        # Allow operational tuning without code edits.
        self._dq_warning_log_interval_sec = self._parse_env_float(
            "DQ_WARNING_LOG_INTERVAL_SEC",
            self.DQ_WARNING_LOG_INTERVAL_SEC,
        )
        self._warmup_warning_log_interval_sec = self._parse_env_float(
            "WARMUP_WARNING_LOG_INTERVAL_SEC",
            self.WARMUP_WARNING_LOG_INTERVAL_SEC,
        )
        logger.info(
            "[Pipeline v8.0] startup config | warmup_warning_log_interval_sec={} dq_warning_log_interval_sec={}",
            self._warmup_warning_log_interval_sec,
            self._dq_warning_log_interval_sec,
        )
        with contextlib.suppress(Exception):
            self._emit_signal_intelligence_flag_snapshot()

    @staticmethod
    def _parse_env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        with contextlib.suppress(ValueError, TypeError):
            return max(1.0, float(raw))
        return default

    @staticmethod
    def _parse_env_float_allow_zero(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        with contextlib.suppress(ValueError, TypeError):
            return max(0.0, float(raw))
        return default

    @staticmethod
    def _parse_env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_env_float_list(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
        raw = os.environ.get(name)
        if raw is None:
            return default
        values: list[float] = []
        for part in raw.replace(",", " ").split():
            with contextlib.suppress(ValueError, TypeError):
                value = float(part.strip())
                if value > 0.0:
                    values.append(value)
        return tuple(sorted(set(values))) or default

    @classmethod
    def _signal_log_compact_mode_enabled(cls) -> bool:
        return cls._parse_env_bool("SIGNAL_LOG_COMPACT_MODE_ENABLED", True)

    # ──────────────────────────────────────────────────────
    #  Lazy-load all layer analyzers
    # ──────────────────────────────────────────────────────

    def skip_analyzers(self) -> None:
        """Replace _ensure_analyzers with a no-op (for tests)."""
        self._ensure_analyzers = lambda: None

    def _ensure_analyzers(self) -> None:
        """Lazy load analyzers to avoid circular imports."""
        if self._l1 is not None:
            return

        import analysis.layers.L10_position_sizing  # noqa: PLC0415
        import analysis.macro.macro_volatility_engine  # noqa: PLC0415
        from analysis.layers.L1_context import (  # noqa: PLC0415
            L1ContextAnalyzer,
        )
        from analysis.layers.L2_mta import L2MTAAnalyzer  # noqa: PLC0415
        from analysis.layers.L3_technical import L3TechnicalAnalyzer  # noqa: PLC0415
        from analysis.layers.L4_session_scoring import (  # noqa: PLC0415
            L4ScoringEngine,
        )
        from analysis.layers.L5_psychology_fundamental import (  # noqa: PLC0415
            L5PsychologyAnalyzer,
        )
        from analysis.layers.L6_risk import L6RiskAnalyzer  # noqa: PLC0415
        from analysis.layers.L9_smc import L9SMCAnalyzer  # noqa: PLC0415
        from analysis.layers.L11_rr import L11RRAnalyzer  # noqa: PLC0415
        from analysis.macro.monthly_regime import MonthlyRegimeAnalyzer  # noqa: PLC0415
        from core.L7_L8_minimal import get_l7_analyzer, get_l8_adapter  # noqa: PLC0415

        self._l1 = L1ContextAnalyzer()
        self._l2 = L2MTAAnalyzer()
        self._l2.bus = self._context_bus  # L2 needs bus injection for candle access
        self._l3 = L3TechnicalAnalyzer()
        self._l4 = L4ScoringEngine()
        self._l5 = L5PsychologyAnalyzer()
        self._l6 = L6RiskAnalyzer()
        self._l7 = get_l7_analyzer()
        self._l8 = get_l8_adapter()
        self._l9 = L9SMCAnalyzer()
        self._l10 = analysis.layers.L10_position_sizing.L10PositionAnalyzer()
        self._l11 = L11RRAnalyzer()
        self._macro = MonthlyRegimeAnalyzer()
        self._macro_vol = analysis.macro.macro_volatility_engine.MacroVolatilityEngine()
        self._validate_analyzers()

    def _validate_analyzers(self) -> None:
        """Fail fast if any lazy-loaded analyzer failed to initialize."""
        required = {
            "L1": self._l1,
            "L2": self._l2,
            "L3": self._l3,
            "L4": self._l4,
            "L5": self._l5,
            "L6": self._l6,
            "L7": self._l7,
            "L8": self._l8,
            "L9": self._l9,
            "L10": self._l10,
            "L11": self._l11,
            "MACRO": self._macro,
            "MACRO_VOL": self._macro_vol,
        }
        missing = [name for name, analyzer in required.items() if analyzer is None]
        if missing:
            raise RuntimeError(f"Analyzer initialization incomplete: {', '.join(missing)}")

    def _ensure_governance_engines(self) -> None:
        """Lazy load L13/L15 governance engines."""
        if self._l13_engine is None:
            self._l13_engine = L13ReflectiveEngine()
        if self._l15_engine is None:
            self._l15_engine = L15MetaSovereigntyEngine()

    @staticmethod
    def _build_pipeline_dag() -> DagEngine:
        """Build canonical layer DAG for execution planning and UI introspection."""
        dag = DagEngine()
        for lid in [
            "L1",
            "L2",
            "L3",
            "L4",
            "L5",
            "SC",
            "L7",
            "L8",
            "L9",
            "L11",
            "L6",
            "L10",
            "macro",
            "L12",
            "L13",
            "L14",
            "L15",
        ]:
            dag.add_node(lid)

        dag.add_edge("L1", "L4")
        dag.add_edge("L2", "L4")
        dag.add_edge("L3", "L4")
        dag.add_edge("L2", "L5")
        dag.add_edge("L4", "L7")
        dag.add_edge("L5", "L7")
        dag.add_edge("L4", "SC")
        dag.add_edge("L5", "SC")
        dag.add_edge("SC", "L7")
        dag.add_edge("L4", "L8")
        dag.add_edge("L4", "L9")
        dag.add_edge("L3", "L11")
        dag.add_edge("L11", "L6")
        dag.add_edge("L6", "L10")
        dag.add_edge("L1", "macro")
        dag.add_edge("L2", "macro")
        dag.add_edge("L3", "macro")
        dag.add_edge("L10", "L12")
        dag.add_edge("L7", "L12")
        dag.add_edge("L8", "L12")
        dag.add_edge("L9", "L12")
        dag.add_edge("L6", "L12")
        dag.add_edge("macro", "L12")
        dag.add_edge("L12", "L13")
        dag.add_edge("L13", "L15")
        dag.add_edge("L15", "L14")
        return dag

    def _get_l13_engine(self) -> L13ReflectiveEngine:
        """Return the L13 engine, raising if not initialized."""
        assert self._l13_engine is not None, "L13 engine not initialized"
        return self._l13_engine

    def _get_l15_engine(self) -> L15MetaSovereigntyEngine:
        """Return the L15 engine, raising if not initialized."""
        assert self._l15_engine is not None, "L15 engine not initialized"
        return self._l15_engine

    # ══════════════════════════════════════════════════════════════
    #  Per-layer latency helper
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _timed_call(
        func: Callable[..., Any],
        layer_name: str,
        symbol: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call *func* with a per-layer timeout and observe wall-clock latency.

        Infrastructure safety only — this has no effect on Layer-12 verdict
        authority.  If a layer exceeds ``_LAYER_TIMEOUT_SEC`` the raised
        ``TimeoutError`` is caught by the outer ``except Exception`` block in
        ``execute()`` and recorded as ``FATAL_ERROR``, returning an early exit
        before Layer-12 can render judgment.

        A new ``ThreadPoolExecutor`` is created per call (max_workers=1).  The
        overhead is negligible (~microseconds) relative to actual layer work,
        and it avoids shared-executor lifecycle concerns across concurrent
        pipeline instances.
        """
        t0 = time.time()
        with layer_span(layer_name, symbol=symbol), concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                result: Any = future.result(timeout=_LAYER_TIMEOUT_SEC)
            except concurrent.futures.TimeoutError:
                logger.error(
                    "[Pipeline] Layer {} TIMEOUT (>{:.0f}s) for {} — aborting layer",
                    layer_name,
                    _LAYER_TIMEOUT_SEC,
                    symbol,
                )
                raise TimeoutError(  # noqa: B904
                    f"Layer {layer_name} exceeded {_LAYER_TIMEOUT_SEC}s timeout"
                )
        LAYER_LATENCY.labels(layer=layer_name, symbol=symbol).observe(
            time.time() - t0,
        )
        return result

    @staticmethod
    def _run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
        """Run coroutine from sync code, even if caller already has an event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as loop_pool:
            return loop_pool.submit(asyncio.run, coro).result()

    @classmethod
    def _run_dag_batch_calls(
        cls,
        dag_batches: list[list[str]],
        batch_calls: dict[str, Callable[[], dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        """Execute callable layers in an always-forward DAG batch pipeline.

        Semantics:
        - Within a batch: runnable layers execute concurrently.
        - Between batches: strict synchronization barrier.
        - Failure mode: record degradation and continue; L12 is sole
          verdict authority.
        """

        async def _run_single(layer_id: str) -> tuple[str, dict[str, Any]]:
            result = await asyncio.to_thread(batch_calls[layer_id])
            return layer_id, result

        async def _run_batches() -> dict[str, dict[str, Any]]:
            output: dict[str, dict[str, Any]] = {}
            for batch_idx, batch in enumerate(dag_batches, start=1):
                runnable = [layer_id for layer_id in batch if layer_id in batch_calls]
                if not runnable:
                    continue
                try:
                    completed = await asyncio.gather(
                        *(_run_single(layer_id) for layer_id in runnable),
                    )
                except Exception as exc:
                    logger.error(
                        "DAG_BATCH_FAILED: batch={}, runnable={}, root_cause={}: {}",
                        batch_idx,
                        ",".join(runnable),
                        type(exc).__name__,
                        exc,
                        exc_info=True,
                    )
                    raise RuntimeError(
                        f"DAG_BATCH_FAILED: batch={batch_idx}, "
                        f"runnable={','.join(runnable)}, "
                        f"cause={type(exc).__name__}: {exc}"
                    ) from exc
                for layer_id, layer_result in completed:
                    output[layer_id] = layer_result
            return output

        return cast(dict[str, dict[str, Any]], cls._run_coro_sync(_run_batches()))

    # ══════════════════════════════════════════════════════════════
    #  EXTRACTED HELPERS — reduce execute() branch complexity
    # ══════════════════════════════════════════════════════════════

    def _assess_data_quality(
        self,
        symbol: str,
        redis_client: Any,
    ) -> tuple[float, list[dict[str, Any]]]:
        """Pre-analysis: assess candle data quality across timeframes.

        Returns ``(confidence_penalty, dq_report_dicts)``.
        """
        import contextlib  # noqa: PLC0415

        from analysis.data_quality_gate import DataQualityGate  # noqa: PLC0415
        from core.redis_keys import latest_candle as _latest_candle_key  # noqa: PLC0415

        dq_gate = DataQualityGate()
        penalty: float = 0.0
        reports: list[dict[str, Any]] = []

        for tf in self.WARMUP_MIN_BARS:
            candles = self._context_bus.get_candles(symbol, tf)
            last_ts_candidates: list[float] = []
            if redis_client is not None:
                with contextlib.suppress(Exception):
                    raw_ts = redis_client.hget(_latest_candle_key(symbol, tf), "last_seen_ts")
                    if raw_ts is not None:
                        last_ts_candidates.append(float(str(raw_ts)))
            if candles:
                last_c = candles[-1]
                candle_last_ts = _coerce_timestamp_to_epoch(
                    last_c.get("timestamp_close")
                    or last_c.get("close_time")
                    or last_c.get("timestamp")
                    or last_c.get("time")
                    or last_c.get("open_time")
                )
                if candle_last_ts is not None:
                    last_ts_candidates.append(candle_last_ts)
            last_ts = max(last_ts_candidates) if last_ts_candidates else None
            report = dq_gate.assess(symbol, tf, candles, last_update_ts=last_ts)
            reports.append(report.to_dict())
            if report.confidence_penalty > penalty:
                penalty = report.confidence_penalty

        degraded = [r for r in reports if r["degraded"]]
        if penalty > 0:
            now_ts = time.time()
            reason_key = tuple(sorted(";".join(r.get("reasons", [])) for r in degraded))
            state = self._dq_warning_state.get(symbol, {})
            should_log = (
                not state.get("degraded", False)
                or state.get("reason_key") != reason_key
                or (now_ts - float(state.get("last_log_ts", 0.0))) >= self._dq_warning_log_interval_sec
            )
            if should_log:
                logger.warning(
                    "[Pipeline v8.0] {} DATA QUALITY degraded - penalty={:.2f}, reports={}",
                    symbol,
                    penalty,
                    degraded,
                )
                self._dq_warning_state[symbol] = {
                    "degraded": True,
                    "reason_key": reason_key,
                    "last_log_ts": now_ts,
                }
        else:
            state = self._dq_warning_state.get(symbol)
            if state and state.get("degraded", False):
                logger.info("[Pipeline v8.0] {} DATA QUALITY recovered", symbol)
            self._dq_warning_state[symbol] = {
                "degraded": False,
                "reason_key": (),
                "last_log_ts": 0.0,
            }

        return penalty, reports

    def _assess_governance(
        self,
        symbol: str,
        *,
        redis_client: Any,
        warmup_ready: bool,
        dq_penalty: float,
        dq_degraded: bool,
        now_ts: float | None = None,
    ) -> Any:
        """Run governance gate assessment.

        Returns the governance result object (has ``.action``, ``.reasons``,
        ``.confidence_penalty``, ``.to_dict()``).
        """
        import contextlib  # noqa: PLC0415

        from state.governance_gate import assess_governance  # noqa: PLC0415

        feed_age_ts: float | None = None
        if redis_client is not None:
            with contextlib.suppress(Exception):
                from state.data_freshness import read_authoritative_last_seen_ts  # noqa: PLC0415

                feed_age_ts = read_authoritative_last_seen_ts(symbol, redis_client=redis_client)
        if feed_age_ts is None:
            feed_age_ts = (
                self._context_bus.get_feed_timestamp(symbol)
                if hasattr(self._context_bus, "get_feed_timestamp")
                else None
            )

        heartbeat_ts: float | None = None
        kill_switch_val: str | None = None
        ws_connected_at: float | None = None
        try:
            from state.redis_keys import HEARTBEAT_INGEST, KILL_SWITCH, WS_CONNECTED_AT  # noqa: PLC0415

            if redis_client is not None:
                with contextlib.suppress(Exception):
                    hb_raw = redis_client.get(HEARTBEAT_INGEST)
                    if hb_raw is not None:
                        heartbeat_ts = _parse_heartbeat_timestamp(hb_raw)
                with contextlib.suppress(Exception):
                    ks_raw = redis_client.get(KILL_SWITCH)
                    if ks_raw is not None:
                        kill_switch_val = str(ks_raw)
                with contextlib.suppress(Exception):
                    ws_raw = redis_client.get(WS_CONNECTED_AT)
                    if ws_raw is not None:
                        ws_connected_at = float(str(ws_raw))
        except Exception:
            pass

        return assess_governance(
            symbol=symbol,
            last_seen_ts=feed_age_ts,
            transport_ok=True,
            heartbeat_ts=heartbeat_ts,
            warmup_ready=warmup_ready,
            dq_penalty=dq_penalty,
            dq_degraded=dq_degraded,
            kill_switch_value=kill_switch_val,
            ws_connected_at=ws_connected_at,
            now_ts=now_ts,
        )

    def _resolve_trade_returns(
        self,
        symbol: str,
        system_metrics: dict[str, Any] | None,
    ) -> tuple[list[float] | None, bool, dict[str, Any] | None]:
        """Resolve trade returns from context bus / metrics / candles.

        Returns ``(trade_returns, preconditioned, conditioning_diagnostics)``.
        """
        trade_returns: list[float] | None = None
        preconditioned = False
        diag: dict[str, Any] | None = None

        # Primary: context bus trade history
        bus_returns: list[float] | None = cast(
            list[float] | None,
            self._context_bus.get_trade_history(symbol=symbol, lookback=200),
        )
        if bus_returns:
            trade_returns = bus_returns
            logger.info(
                "[Phase-3] {} Loaded {} historical returns via context bus",
                symbol,
                len(bus_returns),
            )

        # Fallback 1: system_metrics pass-through
        if not trade_returns and system_metrics:
            raw = system_metrics.get("trade_returns", None)
            if isinstance(raw, list | tuple) and len(cast(list[Any], raw)) > 0:
                trade_returns = [float(r) for r in cast(list[Any], raw)]

        # Fallback 2: conditioned returns from realtime tick ingest
        if not trade_returns:
            cond = cast(
                list[float],
                self._context_bus.get_conditioned_returns(symbol, count=200),
            )
            if cond:
                trade_returns = cond
                preconditioned = True
                diag = cast(
                    dict[str, Any] | None,
                    self._context_bus.get_conditioning_meta(symbol),
                )
                logger.info(
                    "[Phase-3] {} Loaded {} conditioned returns via realtime tick path",
                    symbol,
                    len(cond),
                )

        # Fallback 3: derive from candle closes
        if not trade_returns:
            h1 = cast(list[dict[str, Any]], self._context_bus.get_candles(symbol, "H1"))
            m15 = cast(list[dict[str, Any]], self._context_bus.get_candles(symbol, "M15"))
            source = "H1" if len(h1) >= len(m15) else "M15"
            candles = h1 if source == "H1" else m15
            prices: list[float] = []
            for c in candles:
                cv = c.get("close")
                if isinstance(cv, int | float | str):
                    with contextlib.suppress(TypeError, ValueError):
                        prices.append(float(cv))
            if len(prices) >= 2:
                conditioned = self._signal_conditioner.condition_prices(prices[-300:])
                trade_returns = conditioned.conditioned_returns
                preconditioned = True
                diag = conditioned.diagnostics()
                diag["source"] = f"candle_{source}"
                logger.info(
                    "[Phase-3] {} Derived {} conditioned returns from {} candle closes",
                    symbol,
                    len(trade_returns),
                    source,
                )

        return trade_returns, preconditioned, diag

    def _resolve_l7_cluster_pool(self, system_metrics: dict[str, Any] | None) -> dict[str, list[float]] | None:
        """Build optional cluster-level return pools for L7 cold-start fallback."""
        pool: dict[str, list[float]] = {}

        for metrics_key in ("cluster_pool", "trade_return_clusters", "l7_cluster_pool"):
            raw_pool = system_metrics.get(metrics_key) if isinstance(system_metrics, dict) else None
            if not isinstance(raw_pool, dict):
                continue
            for cluster_name, raw_values in raw_pool.items():
                if not isinstance(raw_values, list | tuple):
                    continue
                values: list[float] = []
                for value in raw_values:
                    with contextlib.suppress(TypeError, ValueError):
                        values.append(float(value))
                if values:
                    pool[str(cluster_name)] = values

        try:
            from analysis import probability_cluster_fallback as _probability_cluster_fallback  # noqa: PLC0415
        except Exception:
            _symbol_clusters = {}
        else:
            _symbol_clusters = _probability_cluster_fallback.SYMBOL_CLUSTERS

        for cluster_name, members in _symbol_clusters.items():
            if cluster_name in pool and len(pool[cluster_name]) >= 30:
                continue
            values = list(pool.get(cluster_name, []))
            for member in members:
                history: Any = None
                with contextlib.suppress(Exception):
                    history = self._context_bus.get_trade_history(symbol=member, lookback=200)
                if not isinstance(history, list | tuple):
                    continue
                for value in history:
                    with contextlib.suppress(TypeError, ValueError):
                        values.append(float(value))
            if values:
                pool[cluster_name] = values[-500:]

        return pool or None

    def _run_universe_ranking(
        self,
        *,
        symbol: str,
        warmup: dict[str, Any],
        data_quality_reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run advisory universe ranking and emit ranking telemetry."""
        try:
            engine = getattr(self, "_universe_ranking", None)
            if engine is None:
                engine = UniverseRankingEngine()
                self._universe_ranking = engine

            result = engine.analyze(
                self._context_bus,
                target_symbol=symbol,
                warmup=warmup,
                data_quality_reports=data_quality_reports,
                top_n=5,
            )
            ranking = result.to_dict()
            target_rank = ranking.get("target_rank") if isinstance(ranking, dict) else None
            if isinstance(target_rank, dict):
                status = str(target_rank.get("watchlist_status", "UNKNOWN"))
                bias = str(target_rank.get("bias", "NEUTRAL"))
                UNIVERSE_RANKING_SCORE.labels(symbol=symbol, bias=bias, status=status).set(
                    float(target_rank.get("rank_score", 0.0) or 0.0)
                )
                UNIVERSE_RANKING_POSITION.labels(symbol=symbol, bias=bias, status=status).set(
                    float(target_rank.get("rank", 0) or 0)
                )
                _emit_canary_event(
                    "event=universe_ranking "
                    f"symbol={symbol} authority=UNIVERSE_RANKING rank={target_rank.get('rank')} "
                    f"bias={bias} status={status} score={target_rank.get('rank_score')} "
                    f"data_ready={ranking.get('data_ready')}"
                )
            return ranking
        except Exception as exc:
            logger.warning("[Pipeline v8.0] Universe ranking failed (non-fatal): {}", exc)
            return {
                "target_symbol": symbol,
                "data_ready": False,
                "readiness_reasons": [f"universe_ranking_error:{type(exc).__name__}"],
                "error": str(exc),
            }

    @staticmethod
    def _annotate_universe_ranking_with_l12(
        ranking: dict[str, Any],
        l12_result: dict[str, Any],
    ) -> None:
        """Decorate advisory ranking with the later L12 verdict for audit."""
        if not isinstance(ranking, dict) or not isinstance(l12_result, dict):
            return

        target_symbol = str(ranking.get("target_symbol", "")).upper()
        verdict = str(l12_result.get("verdict", "UNKNOWN"))
        execution_allowed = bool(l12_result.get("continuation_allowed", False))

        def _annotate(item: dict[str, Any]) -> None:
            item["l12_verdict"] = verdict
            item["execution_allowed"] = execution_allowed
            if execution_allowed:
                item["watchlist_status"] = "EXECUTABLE"

        target = ranking.get("target_rank")
        if isinstance(target, dict):
            _annotate(target)

        for key in ("top_pairs", "ranked_pairs"):
            pairs = ranking.get(key)
            if not isinstance(pairs, list):
                continue
            for item in pairs:
                if isinstance(item, dict) and str(item.get("symbol", "")).upper() == target_symbol:
                    _annotate(item)

    @staticmethod
    def _log_layer_constitutional(
        symbol: str,
        phase: str,
        layer: str,
        result: dict[str, Any],
        *,
        metric_label: str = "score",
    ) -> tuple[str, bool]:
        """Log constitutional diagnostic for a layer.

        Returns ``(constitutional_status, continuation_allowed)``.
        """
        const = result.get("constitutional", {})
        status = const.get("status", "N/A")
        cont = result.get("continuation_allowed", True)
        evidence_score = const.get("evidence_score")
        confidence_penalty = const.get("confidence_penalty")
        hard_stop = const.get("hard_stop")
        soft_blockers = const.get("soft_blockers", [])

        if status == "FAIL":
            blockers = const.get("blocker_codes", [])
            if layer == "L1" and isinstance(const.get("context_diagnostics"), dict):
                diagnostics = const["context_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} regime={} coherence={} required={} feed_age={} warmup_gap={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    diagnostics.get("regime"),
                    diagnostics.get("coherence_score"),
                    diagnostics.get("required_coherence"),
                    diagnostics.get("feed_age_seconds"),
                    diagnostics.get("missing_warmup_by_tf"),
                )
            elif layer == "L2" and isinstance(const.get("mta_diagnostics"), dict):
                diagnostics = const["mta_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} primary_conflict={} alignment={} consensus={} missing_tfs={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    diagnostics.get("primary_conflict"),
                    diagnostics.get("alignment_score"),
                    diagnostics.get("direction_consensus"),
                    diagnostics.get("missing_timeframes"),
                )
            elif layer == "L3" and isinstance(const.get("trend_diagnostics"), dict):
                diagnostics = const["trend_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} hard_stop={} evidence_score={} penalty={} trend={} confirmation={} conflict={} missing_sources={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    hard_stop,
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("trend"),
                    diagnostics.get("confirmation_score"),
                    diagnostics.get("structure_conflict"),
                    diagnostics.get("missing_sources"),
                    soft_blockers,
                )
            elif layer == "L7" and isinstance(const.get("edge_diagnostics"), dict):
                diagnostics = const["edge_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} hard_stop={} evidence_score={} penalty={} edge_status={} edge_reason={} win_probability={} required={} simulations={} source={} profit_factor={} wf_passed={} gap={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    hard_stop,
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("edge_status"),
                    diagnostics.get("edge_status_reason"),
                    diagnostics.get("win_probability"),
                    diagnostics.get("required_win_probability"),
                    diagnostics.get("simulations"),
                    diagnostics.get("returns_source"),
                    diagnostics.get("profit_factor"),
                    diagnostics.get("wf_passed"),
                    diagnostics.get("primary_edge_gap"),
                    soft_blockers,
                )
            elif layer == "L8" and isinstance(const.get("integrity_diagnostics"), dict):
                diagnostics = const["integrity_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} hard_stop={} evidence_score={} penalty={} integrity={} required={} gate_status={} missing_sources={} component_count={} l2_component={} l7_component={} gap={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    hard_stop,
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("integrity_score"),
                    diagnostics.get("required_integrity"),
                    diagnostics.get("gate_status"),
                    diagnostics.get("missing_sources"),
                    diagnostics.get("component_count"),
                    diagnostics.get("component_attribution", {}).get("l2_alignment_component"),
                    diagnostics.get("component_attribution", {}).get("l7_probability_component"),
                    diagnostics.get("primary_integrity_gap"),
                    soft_blockers,
                )
            elif layer == "L9" and isinstance(const.get("structure_diagnostics"), dict):
                diagnostics = const["structure_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} hard_stop={} evidence_score={} penalty={} missing_sources={} builder_state={} bucket={} bucket_reason={} available_sources={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    hard_stop,
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("missing_sources"),
                    diagnostics.get("source_builder_state"),
                    diagnostics.get("runtime_bucket"),
                    diagnostics.get("runtime_bucket_reason"),
                    diagnostics.get("available_sources"),
                    soft_blockers,
                )
            else:
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} hard_stop={} evidence_score={} penalty={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    hard_stop,
                    evidence_score,
                    confidence_penalty,
                    soft_blockers,
                )
        elif status == "WARN":
            warns = const.get("warning_codes", [])
            if layer == "L1" and isinstance(const.get("context_diagnostics"), dict):
                diagnostics = const["context_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} regime={} coherence={} feed_age={} warmup_gap={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    diagnostics.get("regime"),
                    diagnostics.get("coherence_score"),
                    diagnostics.get("feed_age_seconds"),
                    diagnostics.get("missing_warmup_by_tf"),
                )
            elif layer == "L2" and isinstance(const.get("mta_diagnostics"), dict):
                diagnostics = const["mta_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} primary_conflict={} alignment={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    diagnostics.get("primary_conflict"),
                    diagnostics.get("alignment_score"),
                )
            elif layer == "L3" and isinstance(const.get("trend_diagnostics"), dict):
                diagnostics = const["trend_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} evidence_score={} penalty={} trend={} confirmation={} conflict={} missing_sources={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("trend"),
                    diagnostics.get("confirmation_score"),
                    diagnostics.get("structure_conflict"),
                    diagnostics.get("missing_sources"),
                    soft_blockers,
                )
            elif layer == "L7" and isinstance(const.get("edge_diagnostics"), dict):
                diagnostics = const["edge_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} evidence_score={} penalty={} edge_status={} edge_reason={} win_probability={} simulations={} source={} gap={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("edge_status"),
                    diagnostics.get("edge_status_reason"),
                    diagnostics.get("win_probability"),
                    diagnostics.get("simulations"),
                    diagnostics.get("returns_source"),
                    diagnostics.get("primary_edge_gap"),
                    soft_blockers,
                )
            elif layer == "L8" and isinstance(const.get("integrity_diagnostics"), dict):
                diagnostics = const["integrity_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} evidence_score={} penalty={} integrity={} gate_status={} missing_sources={} l2_component={} l7_component={} gap={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("integrity_score"),
                    diagnostics.get("gate_status"),
                    diagnostics.get("missing_sources"),
                    diagnostics.get("component_attribution", {}).get("l2_alignment_component"),
                    diagnostics.get("component_attribution", {}).get("l7_probability_component"),
                    diagnostics.get("primary_integrity_gap"),
                    soft_blockers,
                )
            elif layer == "L9" and isinstance(const.get("structure_diagnostics"), dict):
                diagnostics = const["structure_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} evidence_score={} penalty={} missing_sources={} builder_state={} bucket={} bucket_reason={} available_sources={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    evidence_score,
                    confidence_penalty,
                    diagnostics.get("missing_sources"),
                    diagnostics.get("source_builder_state"),
                    diagnostics.get("runtime_bucket"),
                    diagnostics.get("runtime_bucket_reason"),
                    diagnostics.get("available_sources"),
                    soft_blockers,
                )
            else:
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} evidence_score={} penalty={} soft_blockers={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    evidence_score,
                    confidence_penalty,
                    soft_blockers,
                )
        else:
            logger.info(
                "[{}] {} {} constitutional {} — band={} {}={:.4f}",
                phase,
                symbol,
                layer,
                status,
                const.get("coherence_band", "N/A"),
                metric_label,
                const.get("score_numeric", 0.0),
            )

        return status, cont

    def _run_enrichment_phase(
        self,
        symbol: str,
        direction: str,
        layer_results: dict[str, dict[str, Any]],
        *,
        raw_sl: float,
        raw_tp: float,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run Phase 2.5 engine enrichment (advisory, non-fatal, isolated).

        Returns ``(enrichment_data, phase25_constitutional)``.
        """
        enrichment_data: dict[str, Any] = {}
        phase25_constitutional: dict[str, Any] = {}

        try:
            if self._enrichment is None:
                from engines.enrichment_orchestrator import (  # noqa: PLC0415
                    EngineEnrichmentLayer,
                )

                self._enrichment = EngineEnrichmentLayer(
                    context_bus=self._context_bus,
                )

            enrichment_result = self._enrichment.run(
                symbol=symbol,
                direction=direction,
                layer_results=layer_results,
                entry_price=layer_results["L11"].get("entry_price", layer_results["L11"].get("entry", 0.0)),
                stop_loss=raw_sl,
                take_profit=raw_tp,
            )

            enrichment_data = enrichment_result.to_dict()

            engines_ok = 9 - len(enrichment_result.errors)
            warnings: list[str] = list(enrichment_result.errors)
            if engines_ok < 5:
                warnings.append("ENRICHMENT_ENGINES_DEGRADED")
            phase_status = "PASS" if not warnings else "WARN"
            phase25_constitutional = {
                "phase": "PHASE_2_5_ENRICHMENT",
                "phase_status": phase_status,
                "continuation_allowed": True,
                "next_legal_targets": ["PHASE_5"],
                "engines_ok": engines_ok,
                "engines_total": 9,
                "enrichment_score": enrichment_result.enrichment_score,
                "warnings": warnings,
                "advisory_only": True,
                "audit": {
                    "non_fatal": True,
                    "parallel_semantic": True,
                    "advisory_after_collection": True,
                },
            }
            enrichment_data["constitutional"] = phase25_constitutional

            logger.info(
                "[Pipeline v8.0] Phase 2.5: Enrichment -- {} score={:.3f} engines_ok={}/9 status={}",
                symbol,
                enrichment_result.enrichment_score,
                engines_ok,
                phase_status,
            )
            if phase_status == "WARN":
                logger.warning(
                    "[Pipeline v8.0] Phase 2.5 WARN | symbol={} warnings={}",
                    symbol,
                    warnings,
                )
        except Exception as exc:
            logger.warning("[Pipeline v8.0] Phase 2.5 enrichment failed (non-fatal): {}", exc)
            enrichment_data = {"error": str(exc)}
            phase25_constitutional = {
                "phase": "PHASE_2_5_ENRICHMENT",
                "phase_status": "WARN",
                "continuation_allowed": True,
                "engines_ok": 0,
                "engines_total": 9,
                "enrichment_score": 0.0,
                "warnings": [f"ENRICHMENT_EXCEPTION:{type(exc).__name__}"],
                "advisory_only": True,
            }

        return enrichment_data, phase25_constitutional

    # ══════════════════════════════════════════════════════════════
    #  MAIN EXECUTE -- the single canonical entry point
    # ══════════════════════════════════════════════════════════════

    def execute(  # noqa: PLR0912
        self,
        symbol: str,
        system_metrics: dict[str, Any] | None = None,
        *,
        tick_ts: float | None = None,
    ) -> dict[str, Any]:
        """
        Execute complete Wolf 15-Layer Constitutional Pipeline.

        Args:
            symbol: Trading pair symbol (e.g., "EURUSD", "XAUUSD")
            system_metrics: Optional system state dict with:
                - safe_mode (bool): bypass macro regime gate
                - latency_ms (float): override latency measurement
            tick_ts: ``time.time()`` epoch of the triggering tick. When
                provided, the tick→verdict end-to-end latency is observed
                on the ``TICK_TO_VERDICT_LATENCY`` histogram.

        Returns:
            Complete v8.0 result dict (backward-compatible with v7.4r∞) with:
            - schema, pair, timestamp
            - synthesis: L12-contract synthesis (all layer data)
            - l12_verdict: Constitutional verdict (SOLE AUTHORITY)
            - reflective: Best available L13 reflective pass
            - reflective_pass1: L13 baseline pass (meta=1.0)
            - reflective_pass2: L13 refined pass (real meta)
            - l14_json: Full L14 JSON export
            - l15_meta: L15 meta synthesis (full unity state)
            - sovereignty: vault sync computation
            - enforcement: sovereignty enforcement + drift detection
            - latency_ms: Pipeline execution time
            - errors: List of any errors encountered
        """
        metrics = system_metrics or {}
        safe_mode = bool(metrics.get("safe_mode", False))

        start_time = time.time()
        logger.info("[VerdictPath] pipeline started | symbol={} safe_mode={}", symbol, safe_mode)
        VERDICT_PATH_EVENT_TOTAL.labels(event="pipeline_started", symbol=symbol, status="ok").inc()
        self._ensure_analyzers()
        self._ensure_governance_engines()
        errors: list[str] = []
        layers_executed: list[str] = []
        engines_invoked: list[str] = []
        layer_timings_ms: dict[str, float] = {}
        now = datetime.now(_TZ_GMT8)
        pipeline_dag = self._build_pipeline_dag()
        dag_topology = pipeline_dag.topological_sort()
        dag_batches = pipeline_dag.execution_batches()
        dag_payload = {
            "topology": dag_topology,
            "batches": dag_batches,
            "edges": [{"from": edge.source, "to": edge.target} for edge in pipeline_dag.to_edge_list()],
        }

        def _timed_layer_call(
            func: Callable[..., Any],
            layer_name: str,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            started = time.time()
            result = self._timed_call(func, layer_name, symbol, *args, **kwargs)
            layer_timings_ms[layer_name] = round((time.time() - started) * 1000.0, 3)
            return result

        def _early_exit_with_map(
            _errors: list[str],
            _latency_ms: float,
        ) -> dict[str, Any]:
            return self._early_exit(
                symbol,
                _errors,
                _latency_ms,
                layers_executed=layers_executed,
                engines_invoked=engines_invoked,
            )

        # ═══════════════════════════════════════════════════════
        # WARMUP GATE -- reject analysis if candle history is
        # too thin.  Prevents garbage verdicts on first few
        # minutes after startup.
        # ═══════════════════════════════════════════════════════
        warmup: dict[str, Any] = {"ready": True, "bars": 0, "required": 0, "missing": 0}
        if not safe_mode:
            _warmup_raw = self._context_bus.check_warmup(symbol, self.WARMUP_MIN_BARS)
            warmup = normalize_warmup(_warmup_raw, required=min(self.WARMUP_MIN_BARS.values())).to_dict()

            if not warmup["ready"]:
                missing = warmup["missing"]
                layers_executed.append("L0")
                engines_invoked.append("WarmupGate")
                VERDICT_PATH_EVENT_TOTAL.labels(event="warmup_rejected", symbol=symbol, status="hold").inc()
                now_ts = time.time()
                state = self._warmup_warning_state.get(symbol, {})
                missing_key = str(missing)
                should_log = (
                    not state.get("blocked", False)
                    or state.get("missing_key") != missing_key
                    or (now_ts - float(state.get("last_log_ts", 0.0))) >= self._warmup_warning_log_interval_sec
                )
                if should_log:
                    logger.warning(
                        "[Pipeline v8.0] warmup rejected | symbol={} bars={} required={} missing={}",
                        symbol,
                        warmup["bars"],
                        warmup["required"],
                        missing,
                    )
                    self._warmup_warning_state[symbol] = {
                        "blocked": True,
                        "missing_key": missing_key,
                        "last_log_ts": now_ts,
                    }
                # Strict enforcement: never proceed to any layer or verdict logic
                result = _early_exit_with_map(
                    [f"WARMUP_INSUFFICIENT:{missing}_bars_missing"],
                    time.time() - start_time,
                )
                result["warmup"] = warmup
                result["verdict"] = None  # Explicitly signal no verdict
                return result
            else:
                state = self._warmup_warning_state.get(symbol)
                if state and state.get("blocked", False):
                    logger.info("[Pipeline v8.0] {} warmup recovered; analysis resumed", symbol)
                self._warmup_warning_state[symbol] = {
                    "blocked": False,
                    "missing_key": "",
                    "last_log_ts": 0.0,
                }

        # After pipeline layers, before persisting verdict:
        # (Find verdict assignment and add TP>0 check before persist)
        # ...existing code...

        # ─── Redis client for authoritative freshness data ────
        # Ingest writes last_seen_ts to Redis candle/tick hashes.
        # Read from Redis first; fall back to LiveContextBus only
        # when Redis is unavailable.
        import contextlib as _rctx  # noqa: PLC0415

        _redis_client: Any = getattr(self, "_redis", None)
        if _redis_client is None:
            from storage.redis_client import RedisClient as _SyncRedisClient  # noqa: PLC0415

            with _rctx.suppress(Exception):
                _redis_client = _SyncRedisClient()

        # ═══════════════════════════════════════════════════════
        # DATA QUALITY GATE
        # ═══════════════════════════════════════════════════════
        _dq_penalty, _dq_reports = self._assess_data_quality(symbol, _redis_client)
        _degraded_reports = [r for r in _dq_reports if r["degraded"]]

        # ═══════════════════════════════════════════════════════
        # GOVERNANCE GATE
        # ═══════════════════════════════════════════════════════
        from state.governance_gate import GovernanceAction  # noqa: PLC0415

        _governance_now_ts: float | None = None
        raw_governance_now = metrics.get("governance_now_ts", metrics.get("now_ts"))
        if raw_governance_now is None:
            raw_governance_now = getattr(self, "_governance_now_ts", None)
        with contextlib.suppress(TypeError, ValueError):
            if raw_governance_now is not None:
                _governance_now_ts = float(raw_governance_now)

        _governance = self._assess_governance(
            symbol,
            redis_client=_redis_client,
            warmup_ready=warmup.get("ready", True),
            dq_penalty=_dq_penalty,
            dq_degraded=len(_degraded_reports) > 0,
            now_ts=_governance_now_ts,
        )

        if _governance.action == GovernanceAction.BLOCK:
            layers_executed.append("GovernanceGate")
            engines_invoked.append("GovernanceGate")
            VERDICT_PATH_EVENT_TOTAL.labels(event="governance_blocked", symbol=symbol, status="block").inc()
            logger.warning(
                "[VerdictPath] governance blocked | symbol={} reasons={} penalty={}",
                symbol,
                list(_governance.reasons),
                round(_governance.confidence_penalty, 4),
            )
            result = _early_exit_with_map(
                [f"GOVERNANCE_BLOCK:{','.join(_governance.reasons)}"],
                time.time() - start_time,
            )
            result["governance"] = _governance.to_dict()
            return result

        if _governance.action == GovernanceAction.HOLD:
            layers_executed.append("GovernanceGate")
            engines_invoked.append("GovernanceGate")
            VERDICT_PATH_EVENT_TOTAL.labels(event="governance_blocked", symbol=symbol, status="hold").inc()
            _gov_log = logger.debug if "market_closed" in _governance.reasons else logger.warning
            _gov_log(
                "[VerdictPath] governance hold | symbol={} reasons={} penalty={}",
                symbol,
                list(_governance.reasons),
                round(_governance.confidence_penalty, 4),
            )
            result = _early_exit_with_map(
                [f"GOVERNANCE_HOLD:{','.join(_governance.reasons)}"],
                time.time() - start_time,
            )
            result["governance"] = _governance.to_dict()
            return result

        # Carry governance penalty forward for L12 confidence adjustment
        if _governance.action == GovernanceAction.ALLOW_REDUCED:
            _dq_penalty = max(_dq_penalty, _governance.confidence_penalty)

        try:
            # ═══════════════════════════════════════════════════════
            # PHASE 1 -- ZONA PERCEPTION & CONTEXT (L1, L2, L3)
            # Sequential always-forward via Phase1ChainAdapter
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 1: Perception & Context -- {symbol}")
            engines_invoked.extend(["L1ContextAnalyzer", "L2MTAAnalyzer", "L3TechnicalAnalyzer"])

            assert self._l1 is not None
            assert self._l2 is not None
            assert self._l3 is not None
            l1_analyzer = self._l1
            l2_analyzer = self._l2
            l3_analyzer = self._l3

            from constitution.phase1_chain_adapter import (  # noqa: PLC0415
                ChainStatus,
                Phase1ChainAdapter,
            )

            _phase1_adapter = Phase1ChainAdapter(
                l1_callable=lambda sym: cast(
                    dict[str, Any],
                    _timed_layer_call(l1_analyzer.analyze, "L1", sym),
                ),
                l2_callable=lambda sym: cast(
                    dict[str, Any],
                    _timed_layer_call(l2_analyzer.analyze, "L2", sym),
                ),
                l3_callable=lambda sym: cast(
                    dict[str, Any],
                    _timed_layer_call(l3_analyzer.analyze, "L3", sym),
                ),
                l3_l2_injector=l3_analyzer.set_l2_output,
            )
            _phase1_result = _phase1_adapter.execute(symbol)

            # ── P1-A.5 live wiring: opt-in shadow capture ───────────────
            # Feature flag: WOLF_SHADOW_CAPTURE_ENABLED. Flag-off is a
            # zero-cost no-op. All exceptions are swallowed inside the
            # hook — the legacy path is never impacted.
            _shadow_session = begin_shadow_session(symbol=symbol)
            if _shadow_session is not None:
                _shadow_session.ingest_chain_result(_phase1_result)
                finalize_shadow_session(_shadow_session)

            l1 = _phase1_result.l1
            l2 = _phase1_result.l2
            l3 = _phase1_result.l3
            layers_executed.extend(["L1", "L2", "L3"])

            # Update layer timings from chain adapter
            for _layer_id, _layer_ms in _phase1_result.timing_ms.items():
                layer_timings_ms[_layer_id] = _layer_ms

            # Phase 1 always forwards — L12 is sole verdict authority.
            # Record errors/warnings for L12 consumption.
            if _phase1_result.status == ChainStatus.FAIL:
                errors.extend(_phase1_result.errors)
                logger.warning(
                    "[Pipeline v8.0] Phase 1 DEGRADED at {} | symbol={} chain_status={} errors={} (forwarding to L12)",
                    _phase1_result.failed_at or "UNKNOWN",
                    symbol,
                    _phase1_result.status.value,
                    _phase1_result.errors,
                )
            elif _phase1_result.status == ChainStatus.WARN:
                logger.warning(
                    "[Pipeline v8.0] Phase 1 WARN | symbol={} warnings={}",
                    symbol,
                    _phase1_result.warnings,
                )

            # ═══════════════════════════════════════════════════════
            # PHASE 2 -- ZONA CONFLUENCE & SCORING (L4, L5)
            # Sequential always-forward: L4 → L5
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 2: Confluence & Scoring -- {symbol}")
            engines_invoked.extend(["L4ScoringEngine", "L5PsychologyAnalyzer"])

            assert self._l4 is not None
            assert self._l5 is not None
            l4_engine = self._l4
            l5_engine = self._l5

            # Inject L3 output for L4 constitutional upstream legality check
            if hasattr(l4_engine, "set_l3_output"):
                l4_engine.set_l3_output(l3)

            # Inject macro narrative for L4 bias-aware scoring (advisory)
            if hasattr(l4_engine, "set_macro_context") and self._context_bus is not None:
                _macro_narrative = self._context_bus.get_macro_narrative()
                if _macro_narrative:
                    l4_engine.set_macro_context(_macro_narrative)

            # ── Step 1: L4 (sequential) ──────────────────────────
            l4 = cast(
                dict[str, Any],
                _timed_layer_call(l4_engine.score, "L4", l1, l2, l3),
            )
            layers_executed.append("L4")

            # L4 constitutional diagnostic
            _l4_const = l4.get("constitutional", {})
            _l4_status = _l4_const.get("status", "PASS")
            if _l4_status in ("WARN", "FAIL"):
                logger.warning(
                    "[Pipeline v8.0] L4 constitutional {} | symbol={} reasons={}",
                    _l4_status,
                    symbol,
                    _l4_const.get("warning_codes", _l4_const.get("warnings", [])),
                )

            # Halt check: L4 must allow continuation before L5 runs
            if _l4_status == "FAIL":
                logger.warning(
                    "[Pipeline v8.0] Phase 2 L4 DEGRADED | symbol={} status={} blockers={} | forwarding to L12",
                    symbol,
                    _l4_status,
                    _l4_const.get("blocker_codes", []),
                )
                errors.append(f"L4_FAIL:status={_l4_status}")
                errors.extend(f"L4_BLOCKER:{b}" for b in _l4_const.get("blocker_codes", []))

            # ── Step 2: L5 (sequential, with L4 upstream) ────────
            # Inject L4 output for L5 upstream legality check
            if hasattr(l5_engine, "set_l4_output"):
                l5_engine.set_l4_output(l4)

            l5 = cast(
                dict[str, Any],
                _timed_layer_call(
                    l5_engine.analyze,
                    "L5",
                    symbol,
                    volatility_profile=l2,
                ),
            )
            layers_executed.append("L5")

            # L5 constitutional diagnostic
            _l5_const = l5.get("constitutional", {})
            _l5_status = _l5_const.get("status", "PASS")
            if _l5_status in ("WARN", "FAIL"):
                logger.warning(
                    "[Pipeline v8.0] L5 constitutional {} | symbol={} reasons={}",
                    _l5_status,
                    symbol,
                    _l5_const.get("warning_codes", _l5_const.get("warnings", [])),
                )

            # Halt check: L5 must allow continuation before Phase 3
            if _l5_status == "FAIL":
                logger.warning(
                    "[Pipeline v8.0] Phase 2 L5 DEGRADED | symbol={} status={} blockers={} | forwarding to L12",
                    symbol,
                    _l5_status,
                    _l5_const.get("blocker_codes", []),
                )
                errors.append(f"L5_FAIL:status={_l5_status}")
                errors.extend(f"L5_BLOCKER:{b}" for b in _l5_const.get("blocker_codes", []))

            # ═══════════════════════════════════════════════════════
            # PHASE 3 -- ZONA PROBABILITY & VALIDATION (L7, L8, L9)
            # ═══════════════════════════════════════════════════════
            #
            # L7 receives:
            #   - technical_score  -> from L4 (upstream technical analysis)
            #   - trade_returns    -> from system_metrics or trade history storage
            #   - prior_wins/losses -> from system_metrics (running Bayesian state)
            #   - coherence        -> from earlier layer agreement (L1-L6)
            #   - volatility_index -> from L5 or market regime data
            #   - base_bias        -> directional lean from L3/L4
            #
            # Authority: ANALYSIS ONLY -- no execution side-effects.
            # Gate result flows to Layer-12 Constitution for final verdict.
            # ═══════════════════════════════════════════════════════════════════

            technical_score: Any = l4.get("technical_score", 0)

            # ── Trade history for Monte Carlo ────────────────────────────────
            trade_returns, trade_returns_preconditioned, preconditioning_diag = self._resolve_trade_returns(
                symbol, system_metrics
            )

            # ── Bayesian prior state ─────────────────────────────────────────
            # Primary: derive from trade archive. Fallback: system_metrics.
            prior_wins: int = 0
            prior_losses: int = 0
            with contextlib.suppress(Exception):
                from storage.trade_archive import get_win_loss_counts as _gwlc  # noqa: PLC0415

                _w, _l = _gwlc(symbol=symbol, lookback=200)
                if _w + _l > 0:
                    prior_wins = _w
                    prior_losses = _l

            if prior_wins == 0 and prior_losses == 0:  # noqa: SIM102
                if system_metrics:
                    prior_wins = int(system_metrics.get("prior_wins", 0))
                    prior_losses = int(system_metrics.get("prior_losses", 0))

            # ── Coherence from upstream layers (L1-L6 agreement) ─────────────
            # If a coherence aggregator ran, use it; otherwise default 50.0.
            _coh = l4.get("coherence")
            if _coh is not None:
                float(_coh)

            # ── Volatility index from L5 or regime detector ──────────────────
            if l5:
                float(l5.get("volatility_index", l5.get("atr_normalized", 20.0)))

            # ── Base directional bias from L3/L4 ─────────────────────────────
            if l4:
                _bias = l4.get("directional_bias", l4.get("bias_score"))
                if _bias is not None:
                    float(max(0.0, min(1.0, _bias)))

            # ── Run L7 Probability Analyzer ──────────────────────────────────
            l7_trade_returns = trade_returns
            conditioning_diag: dict[str, Any] | None = preconditioning_diag
            if trade_returns and not trade_returns_preconditioned:
                conditioned = self._signal_conditioner.condition_returns(trade_returns)
                l7_trade_returns = conditioned.conditioned_returns
                conditioning_diag = conditioned.diagnostics()
                logger.info(
                    "[Phase-3] {} SignalConditioner: in={} out={} noise={:.4f} quality={:.4f} stride={}",
                    symbol,
                    conditioning_diag["samples_in"],
                    conditioning_diag["samples_out"],
                    conditioning_diag["noise_ratio"],
                    conditioning_diag["microstructure_quality_score"],
                    conditioning_diag["sampling_stride"],
                )

            assert self._l7 is not None
            assert self._l8 is not None
            assert self._l9 is not None
            l7_engine = self._l7
            l8_engine = self._l8
            l9_engine = self._l9
            engines_invoked.extend(
                [
                    "L7ProbabilityAnalyzer",
                    "L8TIIIntegrityAnalyzer",
                    "L9SMCAnalyzer",
                ]
            )
            # ── L8 needs raw close prices for TII computation ────────
            # L3 output doesn't include raw closes; fetch from bus.
            _h1_for_l8 = cast(
                list[dict[str, Any]],
                self._context_bus.get_candles(symbol, "H1"),
            )
            _l8_closes: list[float] = []
            for _c in _h1_for_l8:
                _cv = _c.get("close")
                if isinstance(_cv, int | float | str):
                    with contextlib.suppress(TypeError, ValueError):
                        _l8_closes.append(float(_cv))
            _l8_market_data: dict[str, Any] = {"closes": _l8_closes} if _l8_closes else {}

            # ── L9 needs structure dict from L3 output ───────────────
            _l9_structure: dict[str, Any] = {
                "valid": l3.get("valid", False),
                "trend": l3.get("trend", "NEUTRAL"),
                "bos": l3.get("fvg_detected", False),  # proxy from L3 SMC markers
                "choch": False,
            }

            # WF validation is only meaningful for real trade P&L.
            # Candle-derived returns have ~50% win rate by nature -> always
            # fails WF thresholds -> false downgrade.  Flag synthetic source
            # so L7 skips WF enrichment.
            _synthetic_returns = trade_returns_preconditioned
            _l7_cluster_pool = self._resolve_l7_cluster_pool(system_metrics)

            # ── Inject upstream output for L7 constitutional governor ─
            # L7 constitutional needs Phase 2 / enrichment continuation
            # state to check upstream legality.
            _l7_upstream: dict[str, Any] = {}
            if l5:
                _l7_upstream = l5
            elif l4:
                _l7_upstream = l4
            if hasattr(l7_engine, "set_upstream_output"):
                l7_engine.set_upstream_output(_l7_upstream)

            # ── L8/L9 upstream injection will happen after L7 completes ─
            # L8 needs L7 output, L9 needs L8 output for constitutional chain.
            # Since Phase 3 runs L7/L8/L9 in parallel, we set Phase 2 output
            # as upstream for L8/L9. Post-hoc chain verification follows.
            _l8_upstream = dict(_l7_upstream)
            if l2:
                _l8_upstream["l2_context"] = l2
            if hasattr(l8_engine, "set_upstream_output"):
                l8_engine.set_upstream_output(_l8_upstream)
            if hasattr(l9_engine, "set_upstream_output"):
                l9_engine.set_upstream_output(_l7_upstream)

            phase3_calls: dict[str, Callable[[], dict[str, Any]]] = {
                "L7": lambda: cast(
                    dict[str, Any],
                    _timed_layer_call(
                        l7_engine.analyze,
                        "L7",
                        symbol,
                        technical_score=technical_score,
                        trade_returns=l7_trade_returns,
                        prior_wins=prior_wins,
                        prior_losses=prior_losses,
                        synthetic_returns=_synthetic_returns,
                        cluster_pool=_l7_cluster_pool,
                    ),
                ),
                "L8": lambda: cast(
                    dict[str, Any],
                    _timed_layer_call(
                        l8_engine.analyze,
                        "L8",
                        symbol,
                        l1=l1,
                        l3=l3,
                        indicators=l3,
                        market_data=_l8_market_data,
                    ),
                ),
                "L9": lambda: cast(
                    dict[str, Any],
                    _timed_layer_call(l9_engine.analyze, "L9", symbol, structure=_l9_structure),
                ),
            }
            phase3_results = self._run_dag_batch_calls(dag_batches, phase3_calls)
            l7 = phase3_results["L7"]
            if conditioning_diag is not None:
                l7["signal_conditioning"] = conditioning_diag
            l8 = phase3_results["L8"]
            l9 = phase3_results["L9"]
            layers_executed.extend(["L7", "L8", "L9"])

            logger.info(
                "[Phase-3] {} L7 complete: validation={} win={:.1f}% pf={:.2f} bayes={:.4f} ror={:.4f} mc_passed={}",
                symbol,
                l7.get("validation", "N/A"),
                l7.get("win_probability", 0.0),
                l7.get("profit_factor", 0.0),
                l7.get("bayesian_posterior", 0.0),
                l7.get("risk_of_ruin", 1.0),
                l7.get("mc_passed_threshold", False),
            )
            logger.info(
                "[Phase-3] {} L8 complete: tii={:.4f} integrity={:.4f} gate={} twms={:.4f} closes_fed={}",
                symbol,
                l8.get("tii_sym", 0.0),
                l8.get("integrity", 0.0),
                l8.get("gate_status", "N/A"),
                l8.get("twms_score", 0.0),
                len(_l8_closes),
            )
            logger.info(
                "[Phase-3] {} L9 complete: smc={} score={} dvg={:.4f} liq={:.4f} signal={} valid={}",
                symbol,
                l9.get("smc", False),
                l9.get("smc_score", 0),
                l9.get("dvg_confidence", 0.0),
                l9.get("liquidity_score", 0.0),
                l9.get("smart_money_signal", "N/A"),
                l9.get("valid", False),
            )

            # ── L7/L8/L9 Constitutional Diagnostics ─────────────────
            _l7_const_status, _l7_cont_allowed = self._log_layer_constitutional(
                symbol,
                "Phase-3",
                "L7",
                l7,
                metric_label="wp",
            )
            _l8_const_status, _l8_cont_allowed = self._log_layer_constitutional(
                symbol,
                "Phase-3",
                "L8",
                l8,
                metric_label="integrity",
            )
            _l9_const_status, _l9_cont_allowed = self._log_layer_constitutional(
                symbol,
                "Phase-3",
                "L9",
                l9,
                metric_label="structure",
            )

            # ── Phase-3 Chain Integrity Check (post-hoc) ─────────────
            if _l7_const_status == "FAIL" and (_l8_cont_allowed or _l9_cont_allowed):
                logger.warning(
                    "[Phase-3] {} CHAIN WARNING: L7 FAIL but L8/L9 continuation allowed "
                    "(parallel execution — Phase 2 upstream used)",
                    symbol,
                )
            if _l8_const_status == "FAIL" and _l9_cont_allowed:
                logger.warning(
                    "[Phase-3] {} CHAIN WARNING: L8 FAIL but L9 continuation allowed "
                    "(parallel execution — Phase 2 upstream used)",
                    symbol,
                )

            # ── Universe ranking / conditional watchlist (advisory) ───
            # This answers "what deserves attention?" before L12 answers
            # "what is executable now?". It is injected into L9/synthesis for
            # basket confirmation, but never relaxes constitutional gates.
            universe_ranking = self._run_universe_ranking(
                symbol=symbol,
                warmup=warmup,
                data_quality_reports=_dq_reports,
            )
            target_rank = universe_ranking.get("target_rank") if isinstance(universe_ranking, dict) else None
            if isinstance(target_rank, dict):
                l9["basket_confirmation"] = {
                    "source": "universe_ranking",
                    "rank": target_rank.get("rank"),
                    "bias": target_rank.get("bias"),
                    "phase": target_rank.get("phase"),
                    "watchlist_status": target_rank.get("watchlist_status"),
                    "rank_score": target_rank.get("rank_score"),
                    "relative_strength_delta": target_rank.get("relative_strength_delta"),
                    "cross_confirmation_score": target_rank.get("cross_confirmation_score"),
                    "advisory_only": True,
                }
                l9["universe_ranking"] = target_rank

            # ═══════════════════════════════════════════════════════
            # PHASE 4 -- ZONA EXECUTION & DECISION (L11 -> L6 -> L10)
            # CRITICAL: L11 BEFORE L6 (L6 needs RR from L11)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 4: Execution & Decision -- {symbol}")
            engines_invoked.extend(["L11RRAnalyzer", "L6RiskAnalyzer", "L10PositionAnalyzer", "MonthlyRegimeAnalyzer"])

            direction_resolution = resolve_trade_direction({"L1": l1, "L2": l2, "L3": l3, "L9": l9})
            direction = str(direction_resolution["direction"])
            logger.info(
                "[Pipeline v8.0] {} direction_resolution direction={} reason={} sources={} conflicts={}",
                symbol,
                direction,
                direction_resolution.get("reason"),
                direction_resolution.get("sources"),
                direction_resolution.get("conflicts"),
            )

            l11: dict[str, Any] = {"valid": False, "rr": 0.0}
            assert self._macro is not None
            macro_engine = self._macro

            # ── Constitutional: inject Phase 3 upstream into L11 ───────
            if self._l11 is not None and hasattr(self._l11, "set_upstream_output"):
                _l9_upstream = l9 if l9 else {"valid": True, "continuation_allowed": True}
                self._l11.set_upstream_output(_l9_upstream)

            # ── Structural zones: merge L3/L9 zone data for TP1 enrichment ──
            if self._l11 is not None and hasattr(self._l11, "set_structural_zones"):
                _sz: dict[str, Any] = {}
                if l3:
                    _sz["vpc_zones"] = l3.get("vpc_zones", [])
                    _sz["volume_profile_poc"] = l3.get("volume_profile_poc", 0.0)
                if l9:
                    _sz["fvg_zones"] = l9.get("fvg_zones", [])
                    _sz["ob_zones"] = l9.get("ob_zones", [])
                    _sz["liquidity_levels"] = l9.get("liquidity_levels", [])
                    _sz["bos_level"] = l9.get("bos_level", 0.0)
                if any(v for v in _sz.values() if v):
                    self._l11.set_structural_zones(_sz)
                else:
                    self._l11.set_structural_zones(None)

            phase4_batch0_calls: dict[str, Callable[[], dict[str, Any]]] = {
                "macro": lambda: cast(dict[str, Any], _timed_layer_call(macro_engine.analyze, "macro", symbol)),
            }
            if direction in ("BUY", "SELL"):
                assert self._l11 is not None
                l11_engine = self._l11
                phase4_batch0_calls["L11"] = lambda: cast(
                    dict[str, Any],
                    _timed_layer_call(l11_engine.calculate_rr, "L11", symbol, direction),
                )

            phase4_batch0_results = self._run_dag_batch_calls(dag_batches, phase4_batch0_calls)
            macro = phase4_batch0_results["macro"]
            if "L11" in phase4_batch0_results:
                l11 = phase4_batch0_results["L11"]
                layers_executed.append("L11")
            rr_value: float = float(l11.get("rr", 0.0))

            # ── Build account_state snapshot for L6 ────────────────────
            # L6 has 7 checks; all need real account data to fire.
            # Single source of truth: LiveContextBus.get_account_state()
            #   → resolves from dashboard push or RiskManager fallback
            # Layer-local enrichment: L5 drawdown/consec_losses, L1 vol
            # If all sources unavailable, L6 applies safe defaults.

            _bus_account: dict[str, Any] = cast(
                dict[str, Any],
                self._context_bus.get_account_state(symbol),
            )

            # Enrich with layer data that only the pipeline has
            _l5_dd: float = float(l5.get("current_drawdown", 0.0))
            _l5_cl: int = int(l5.get("consecutive_losses", 0))
            _l1_vol: str = str(l1.get("volatility_level", "NORMAL"))

            # system_metrics caller overrides (test harness / manual)
            _sm = system_metrics if isinstance(system_metrics, dict) else {}

            _l6_account_state: dict[str, Any] = {
                # Check 1: Drawdown tier — equity/peak for accurate drawdown calc
                "equity": float(_sm.get("equity", _bus_account.get("equity", 0.0)) or 0.0),
                "peak_equity": float(_sm.get("peak_equity", _bus_account.get("peak_equity", 0.0)) or 0.0),
                "drawdown_pct": _l5_dd,  # L5 psychology-derived fallback
                # Check 2: Volatility cluster (from L1 market perception)
                "vol_cluster": _l1_vol,
                # Check 3: Correlation exposure
                "corr_exposure": float(_sm.get("corr_exposure", _bus_account.get("corr_exposure", 0.0)) or 0.0),
                # Check 6: Prop-firm daily DD
                "daily_loss_pct": float(_sm.get("daily_loss_pct", _bus_account.get("daily_loss_pct", 0.0)) or 0.0),
                # Check 7: Kelly dampener
                "base_kelly": float(_sm.get("base_kelly", _bus_account.get("base_kelly", 0.25)) or 0.25),
                # Shared: consecutive losses (L5 is authoritative)
                "consecutive_losses": _l5_cl,
                # Shared: open positions & max
                "open_positions": int(_sm.get("open_positions", _bus_account.get("open_positions", 0)) or 0),
                "max_open_positions": int(_bus_account.get("max_open_positions", 5) or 5),
                # Shared: circuit breaker flag
                "circuit_breaker_active": bool(_bus_account.get("circuit_breaker_active", False)),
            }

            logger.debug(
                "[Phase-4] L6 account wiring via bus: equity={:.2f} peak={:.2f} daily_dd={:.4f} circuit={} open={}/{}",
                _l6_account_state["equity"],
                _l6_account_state["peak_equity"],
                _l6_account_state["daily_loss_pct"],
                _l6_account_state["circuit_breaker_active"],
                _l6_account_state["open_positions"],
                _l6_account_state["max_open_positions"],
            )

            if self._l6 is None:
                errors.append("L6_ANALYZER_NOT_INITIALIZED")
                return _early_exit_with_map(errors, time.time() - start_time)

            # ── Constitutional: inject L11 upstream into L6 ────────────
            if hasattr(self._l6, "set_upstream_output"):
                self._l6.set_upstream_output(l11)

            l6: dict[str, Any] = _timed_layer_call(
                self._l6.analyze,
                "L6",
                rr=rr_value,
                trade_returns=trade_returns,
                account_state=_l6_account_state,
            )
            layers_executed.append("L6")

            l6.get("risk_ok", False)
            smc_confidence: Any = l9.get("confidence", 0.0)
            assert self._l10 is not None

            # ── Legacy FTA advisory hint (pre-L10, advisory-only) ──────
            legacy_fta: dict[str, Any] = {}
            _legacy_conf_hint: float = 0.0
            try:
                if self._legacy_fta is None:
                    from engines.legacy_fta_enricher import LegacyFTAEnricher  # noqa: PLC0415

                    self._legacy_fta = LegacyFTAEnricher()
                legacy_fta = self._legacy_fta.run(symbol=symbol)
                _legacy_conf_hint = float(legacy_fta.get("confidence_hint", 0.0))
            except Exception as _lfta_exc:
                logger.debug("[Pipeline v8.0] Legacy FTA advisory skipped: {}", _lfta_exc)

            # ── Blend confidence: 85% repo + 15% legacy (advisory) ─────
            _repo_conf = float(smc_confidence)
            if _legacy_conf_hint > 0.0 and legacy_fta.get("legacy_fta_present", False):
                from engines.legacy_fta_enricher import blend_confidence  # noqa: PLC0415

                _effective_confidence = blend_confidence(_repo_conf, _legacy_conf_hint)
                logger.info(
                    "[Pipeline v8.0] Legacy FTA blend: repo={:.4f} legacy={:.4f} → effective={:.4f}",
                    _repo_conf,
                    _legacy_conf_hint,
                    _effective_confidence,
                )
            else:
                _effective_confidence = _repo_conf

            # ── Constitutional: inject L6 upstream into L10 ────────────
            if hasattr(self._l10, "set_upstream_output"):
                self._l10.set_upstream_output(l6)

            # Build trade_params from L11 + account state for L10
            _l10_trade_params: dict[str, Any] = {
                "entry": float(l11.get("entry_price", l11.get("entry", 0.0))),
                "stop_loss": float(l11.get("stop_loss", l11.get("sl", 0.0))),
                "take_profit": float(l11.get("take_profit_1", l11.get("tp1", l11.get("tp", 0.0)))),
                "direction": direction,
            }
            _l10_balance = float(_l6_account_state.get("equity", 10_000.0)) or 10_000.0
            l10: dict[str, Any] = _timed_layer_call(
                self._l10.analyze,
                "L10",
                _l10_trade_params,
                _l10_balance,
                symbol,
                confidence=_effective_confidence,
                trade_returns=trade_returns,
                win_probability=l7.get("win_probability"),
                bayesian_posterior=l7.get("bayesian_posterior"),
            )
            layers_executed.append("L10")

            # ── Phase 4 constitutional diagnostics ─────────────────────
            _p4_l11_status = l11.get("constitutional", {}).get("status", "N/A")
            _p4_l6_status = l6.get("constitutional", {}).get("status", "N/A")
            _p4_l10_status = l10.get("constitutional", {}).get("status", "N/A")
            logger.info(
                "[Pipeline v8.0] Phase 4 constitutional: L11={} L6={} L10={} | L11_cont={} L6_cont={} L10_cont={}",
                _p4_l11_status,
                _p4_l6_status,
                _p4_l10_status,
                l11.get("continuation_allowed", "N/A"),
                l6.get("continuation_allowed", "N/A"),
                l10.get("continuation_allowed", "N/A"),
            )

            # ── Direction guard ────────────────────────────────
            # When L3 trend is NEUTRAL, direction=HOLD and L11 is
            # intentionally skipped.  Exit early with a precise reason
            # instead of falling through to the SL/TP zero guard.
            if direction not in ("BUY", "SELL"):
                direction_reason = str(direction_resolution.get("reason", "no_directional_bias"))
                direction_conflicts = direction_resolution.get("conflicts", [])
                logger.info(
                    "[Pipeline v8.0] {} direction={} → NO_TRADE (reason={} conflicts={})",
                    symbol,
                    direction,
                    direction_reason,
                    direction_conflicts,
                )
                result = _early_exit_with_map(
                    [direction_reason],
                    time.time() - start_time,
                )
                result["verdict"] = "NO_TRADE"
                result["verdict_reason"] = f"No executable direction (reason={direction_reason})"
                result["direction_resolution"] = direction_resolution
                result["universe_ranking"] = universe_ranking
                result["l12_verdict"] = {
                    "verdict": "NO_TRADE",
                    "reason": direction_reason,
                    "direction_resolution": direction_resolution,
                }
                return result

            # ── SL/TP zero guard ─────────────────────────────────
            # When ATR=0 (warmup insufficient), L11 returns SL=0/TP=0.
            # Schema validation rejects these → verdict never set →
            # dashboard shows "verdict: Required" error.
            # Guard: skip enrichment, force NO_TRADE verdict early.
            _raw_sl = l11.get("stop_loss", l11.get("sl", 0.0))
            _raw_tp = l11.get("take_profit_1", l11.get("tp1", l11.get("tp", 0.0)))
            if not _raw_sl or _raw_sl <= 0 or not _raw_tp or _raw_tp <= 0:
                _l11_reason = l11.get("reason", "unknown")
                logger.warning(
                    "[Pipeline v8.0] {} SL/TP=0 → NO_TRADE (reason={} sl={:.5f} tp={:.5f})",
                    symbol,
                    _l11_reason,
                    _raw_sl or 0.0,
                    _raw_tp or 0.0,
                )
                result = _early_exit_with_map(
                    ["sl_tp_zero_guard"],
                    time.time() - start_time,
                )
                result["verdict"] = "NO_TRADE"
                result["verdict_reason"] = "SL/TP zero (ATR warmup insufficient)"
                result["l12_verdict"] = {"verdict": "NO_TRADE", "reason": "sl_tp_zero"}
                return result

            # ═══════════════════════════════════════════════════════
            # PHASE 2.5 -- ENGINE ENRICHMENT LAYER (9 Facade Engines)
            #   ADR-011: cognitive/fusion/quantum enrichment before L12
            #   Constitutional wrapper: advisory-only, non-fatal, isolated
            # ═══════════════════════════════════════════════════════
            _enrich_lr: dict[str, Any] = {
                "L1": l1,
                "L2": l2,
                "L3": l3,
                "L4": l4,
                "L5": l5,
                "L6": l6,
                "L7": l7,
                "L8": l8,
                "L9": l9,
                "L10": l10,
                "L11": l11,
            }
            enrichment_data, _phase25_constitutional = self._run_enrichment_phase(
                symbol,
                direction,
                _enrich_lr,
                raw_sl=_raw_sl,
                raw_tp=_raw_tp,
            )
            if "error" not in enrichment_data:
                engines_invoked.extend(
                    [
                        "EngineEnrichmentLayer",
                        "RegimeClassifier",
                        "FusionIntegrator",
                        "TRQ3DEngine",
                        "QuantumReflectiveBridge",
                    ]
                )

            # ── LRCE patch: feed enrichment into L6 (Check 4) ────────
            # L6 ran before enrichment (needed for L10/L12), but
            # LRCE needs fusion_momentum/quantum_prob from engines.
            # Re-evaluate LRCE with enrichment data; update L6 result
            # if field fracture is detected (hard block escalation).
            if enrichment_data and "error" not in enrichment_data:
                try:
                    _lrce_input = {
                        "fusion_momentum": float(enrichment_data.get("fusion_momentum", 0.0)),
                        "quantum_probability": float(enrichment_data.get("quantum_probability", 0.0)),
                        "bias_strength": float(enrichment_data.get("bias_strength", 0.0)),
                        "posterior": float(enrichment_data.get("posterior", 0.0)),
                    }
                    _lrce = self._l6._compute_lrce(_lrce_input)
                    l6["lrce"] = round(_lrce, 4)

                    if _lrce > self._l6.lrce_block_threshold:
                        l6["risk_status"] = "UNSTABLE_FIELD"
                        l6["risk_ok"] = False
                        l6["propfirm_compliant"] = False
                        l6["max_risk_pct"] = 0.0
                        l6.setdefault("warnings", []).append(f"LRCE_FRACTURE({_lrce:.3f})")
                        logger.warning(
                            "[Phase-4→2.5] L6 LRCE escalation: {:.3f} > threshold → HARD BLOCK",
                            _lrce,
                        )
                    else:
                        logger.debug("[Phase-4→2.5] L6 LRCE updated: {:.3f} (stable)", _lrce)
                except Exception as _lrce_exc:
                    logger.debug("[Phase-4→2.5] LRCE patch skipped: {}", _lrce_exc)
            # ═══════════════════════════════════════════════════════
            # PHASE 5 -- L12 CONSTITUTIONAL VERDICT (SOLE AUTHORITY)
            #   Build synthesis -> 9-Gate Check -> L12 verdict
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 5: Constitutional Verdict -- {symbol}")
            layers_executed.append("L12")
            engines_invoked.extend(["GateEvaluator9", "VerdictEngineL12"])

            current_latency_ms = (time.time() - start_time) * 1000

            layer_results_combined: dict[str, Any] = {
                "L1": l1,
                "L2": l2,
                "L3": l3,
                "L4": l4,
                "L5": l5,
                "L6": l6,
                "L7": l7,
                "L8": l8,
                "L9": l9,
                "L10": l10,
                "L11": l11,
                "universe_ranking": universe_ranking,
                # Legacy FTA advisory (WOLF ARSENAL v4.0 adapter)
                "legacy_fta": legacy_fta if legacy_fta else {},
                "legacy_fta_confidence_blend": {
                    "repo_confidence": _repo_conf,
                    "legacy_hint": _legacy_conf_hint,
                    "effective_confidence": _effective_confidence,
                    "legacy_fta_present": legacy_fta.get("legacy_fta_present", False),
                },
                # MonthlyRegimeAnalyzer — pass full result fields so
                # build_l12_synthesis can populate synthesis["macro"] correctly.
                "macro": macro.get("regime", "UNKNOWN"),
                "phase": macro.get("phase", "NEUTRAL"),
                "macro_vol_ratio": macro.get("macro_vol_ratio", 1.0),
                "alignment": macro.get("alignment", False),
                "liquidity": macro.get("liquidity", {}),
                "bias_override": macro.get("bias_override", {}),
                # MacroVolatilityEngine — prefer live engine state; fall back to
                # caller-supplied system_metrics (test harness / manual override).
                "macro_vix_state": (
                    self._macro_vol.get_state() if self._macro_vol is not None else metrics.get("macro_vix_state", {})
                ),
                # Inference state — ephemeral abstract state TUYUL reasons with.
                "inference": self._context_bus.inference_snapshot(),
            }

            synthesis = build_l12_synthesis(
                layer_results=layer_results_combined,
                symbol=symbol,
            )
            synthesis["system"]["latency_ms"] = current_latency_ms
            synthesis["system"]["safe_mode"] = safe_mode
            synthesis["system"]["layer_timings_ms"] = dict(layer_timings_ms)
            synthesis["system"]["dag"] = dict(dag_payload)
            if conditioning_diag is not None:
                synthesis["system"]["signal_conditioning"] = dict(conditioning_diag)

            reflex_coherence = float(l2.get("reflex_coherence", 0.0) or 0.0)
            emotion_delta = float(l5.get("emotion_delta", 0.0) or 0.0)
            delta_t_sec = max(0.0, time.time() - tick_ts) if tick_ts is not None else 0.0

            # ── Adaptive sigma: widen latency tolerance under stress ──
            adaptive_sigma = self._emc_filter.adaptive_sigma(emotion_delta)

            # ── Legacy single RQI (backward compat) ───────────────────
            rqi_score = compute_rqi(
                delta_t_sec=delta_t_sec,
                coherence=reflex_coherence,
                emotion_delta=emotion_delta,
                sigma_sec=adaptive_sigma,
            )

            # ── Multi-TF RQI from L2 per-TF probabilities ────────────
            per_tf_detail: dict[str, Any] = l2.get("per_tf_bias", {})
            multitf_result = compute_multitf_rqi(
                per_tf_detail=per_tf_detail,
                delta_t_sec=delta_t_sec,
                emotion_delta=emotion_delta,
                sigma_sec=adaptive_sigma,
            )
            rqi_multi = float(multitf_result.get("rqi_multi", 0.0))

            # Use multi-TF RQI if available, else fall back to single
            rqi_effective = rqi_multi if per_tf_detail else rqi_score

            # ── EMC smoothing (stateful per symbol) ───────────────────
            rqi_smoothed = self._emc_filter.smooth(symbol, rqi_effective)

            # ── Reflex gate decision ──────────────────────────────────
            gate_decision = self._reflex_gate.evaluate(rqi_smoothed)

            synthesis["system"]["rqi"] = round(rqi_smoothed, 6)
            synthesis["system"]["rqi_raw"] = round(rqi_effective, 6)
            synthesis["system"]["rqi_components"] = {
                "latency_decay": round(latency_decay(delta_t_sec, adaptive_sigma), 6),
                "reflex_coherence": round(max(0.0, min(1.0, reflex_coherence)), 6),
                "emotion_stability": round(max(0.0, min(1.0, 1.0 - emotion_delta)), 6),
                "delta_t_sec": round(delta_t_sec, 4),
                "sigma_sec": round(self._rqi_sigma_sec, 4),
                "sigma_adaptive": round(adaptive_sigma, 4),
            }
            synthesis["system"]["rqi_multitf"] = multitf_result
            synthesis["system"]["rqi_emc"] = self._emc_filter.get_session(symbol)
            synthesis["system"]["reflex_gate"] = gate_decision.to_dict()

            # ── Data quality penalty injection ────────────────────────
            synthesis["system"]["data_quality"] = {
                "penalty": round(_dq_penalty, 4),
                "reports": _dq_reports,
            }

            # Inject enrichment data into synthesis for L12 visibility
            synthesis["enrichment"] = enrichment_data
            if enrichment_data.get("confidence_adjustment"):
                synthesis["layers"]["enrichment_confidence_adj"] = enrichment_data["confidence_adjustment"]
                synthesis["layers"]["enrichment_score"] = enrichment_data.get("enrichment_score", 0.0)

            # Apply data quality confidence penalty (advisory — does not override L12)
            if _dq_penalty > 0:
                current_adj = synthesis["layers"].get("enrichment_confidence_adj", 0.0)
                synthesis["layers"]["enrichment_confidence_adj"] = current_adj - _dq_penalty
                synthesis["layers"]["data_quality_penalty"] = round(_dq_penalty, 4)

            # ── Lorentzian Field Stabilizer (advisory enrichment) ─────
            # Runs under ENABLE_LFS_SOFTENER feature flag.
            # Injects bounded confidence_adj and diagnostic block into
            # synthesis. Never overrides L12. Guards: data quality, warmup.
            if self.ENABLE_LFS_SOFTENER:
                try:
                    if self._lorentzian is None:
                        from engines.lorentzian_enricher import (  # noqa: PLC0415
                            LorentzianFieldEnricher,
                        )

                        self._lorentzian = LorentzianFieldEnricher()

                    _lfs_prev = self._lfs_history.get(symbol)
                    _lfs_result = self._lorentzian.analyze(synthesis, history=_lfs_prev)

                    # Store α–β–γ snapshot for next cycle delta computation
                    from analysis.reflective.lorentzian_field_adapter import (  # noqa: PLC0415
                        map_layer_results_to_abg,
                    )

                    _a, _b, _g = map_layer_results_to_abg(synthesis)
                    self._lfs_history[symbol] = {"alpha": _a, "beta": _b, "gamma": _g}

                    # Inject into enrichment data
                    enrichment_data["lorentzian"] = {
                        "e_norm": _lfs_result.e_norm,
                        "lrce": _lfs_result.lrce,
                        "gradient_signed": _lfs_result.gradient_signed,
                        "gradient_abs": _lfs_result.gradient_abs,
                        "drift": _lfs_result.drift,
                        "field_phase": _lfs_result.field_phase,
                        "quality_band": _lfs_result.quality_band,
                        "rescue_eligible": _lfs_result.rescue_eligible,
                        "confidence_adj": _lfs_result.confidence_adj,
                        "advisory_only": True,
                    }

                    # Overwrite synthesis placeholder with real values
                    synthesis["lorentzian"] = {
                        "e_norm": round(_lfs_result.e_norm, 4),
                        "lrce": round(_lfs_result.lrce, 4),
                        "gradient_signed": round(_lfs_result.gradient_signed, 4),
                        "gradient_abs": round(_lfs_result.gradient_abs, 4),
                        "drift": round(_lfs_result.drift, 4),
                        "field_phase": _lfs_result.field_phase,
                        "quality_band": _lfs_result.quality_band,
                        "rescue_eligible": _lfs_result.rescue_eligible,
                    }

                    # Guard: disable rescue if data quality degraded or warmup not ready
                    _warmup_ready = warmup.get("ready", True)
                    if _dq_penalty > 0 or not _warmup_ready:
                        synthesis["lorentzian"]["rescue_eligible"] = False

                    # Apply bounded confidence adjustment
                    _lfs_adj = _lfs_result.confidence_adj
                    if _lfs_adj != 0.0:
                        _cur = synthesis["layers"].get("enrichment_confidence_adj", 0.0)
                        synthesis["layers"]["enrichment_confidence_adj"] = _cur + _lfs_adj

                    logger.info(
                        "[Pipeline v8.0] LFS {} | lrce={:.4f} band={} rescue={} adj={:.3f}",
                        symbol,
                        _lfs_result.lrce,
                        _lfs_result.quality_band,
                        synthesis["lorentzian"]["rescue_eligible"],
                        _lfs_adj,
                    )
                except Exception as exc:
                    logger.warning("[Pipeline v8.0] LFS enrichment failed (non-fatal): {}", exc)

            # ── L14-B Adaptive Penalty Injection ─────────────────────
            # Mines J3/J4 journal records for historically underperforming
            # setup patterns and subtracts a bounded penalty from
            # enrichment_confidence_adj BEFORE gates + L12 verdict.
            # Advisory-only: does NOT override L12. Constitutional-compliant.
            #
            # Data source: system_metrics["j3_rows"] / ["j4_rows"]
            # (caller-provided or loaded by the service layer).
            l14b_report_dict: dict[str, Any] = {}
            try:
                j3_rows: list[dict[str, Any]] = list(metrics.get("j3_rows") or [])
                j4_rows: list[dict[str, Any]] = list(metrics.get("j4_rows") or [])

                if j3_rows or j4_rows:
                    from journal.l14_underperform_miner import (  # noqa: PLC0415
                        L14AdaptiveReflection,
                        UnderperformPatternMiner,
                    )

                    _l14b_ctx: dict[str, Any] = {
                        "pair": symbol,
                        "direction": direction,
                        "regime": l1.get("regime"),
                        "session": l4.get("session"),
                    }
                    _l14b_engine = L14AdaptiveReflection(
                        UnderperformPatternMiner(min_trades=8, max_combo_size=3),
                    )
                    _l14b_report = _l14b_engine.analyze(
                        j3_rows,
                        j4_rows,
                        current_context=_l14b_ctx,
                    )
                    adaptive_penalty = _l14b_engine.penalty_for_current_setup(
                        _l14b_report,
                        max_penalty=0.35,
                    )
                    if adaptive_penalty > 0:
                        current_adj = synthesis["layers"].get("enrichment_confidence_adj", 0.0)
                        synthesis["layers"]["enrichment_confidence_adj"] = current_adj - adaptive_penalty
                        logger.info(
                            "[Pipeline v8.0] L14-B adaptive penalty {:.3f} applied for {}",
                            adaptive_penalty,
                            symbol,
                        )
                    l14b_report_dict = _l14b_report.to_dict()
            except Exception as exc:
                logger.warning("[Pipeline v8.0] L14-B adaptive reflection failed (non-fatal): {}", exc)

            synthesis["l14b_adaptive"] = l14b_report_dict

            metrics.get("macro_vix_state", {})

            gates = self._evaluate_9_gates(synthesis)
            l12_verdict = generate_l12_verdict(synthesis, governance_penalty=_dq_penalty)
            l12_verdict["gates_v74"] = gates
            legacy_verdict = l12_verdict.get("verdict")
            self._emit_verdict_stream_event(
                event="l12_legacy_verdict",
                symbol=symbol,
                authority="L12_LEGACY",
                verdict_stream="canonical_pre_enforcement",
                verdict=l12_verdict.get("verdict"),
                direction=l12_verdict.get("direction"),
                extras={
                    "confidence": l12_verdict.get("confidence"),
                    "proceed": l12_verdict.get("proceed_to_L13"),
                },
            )

            # ── Constitutional Phase 5 overlay (L12 router evaluator) ──
            # Runs the new constitutional L12 governor in parallel with the
            # legacy verdict path. Result is injected into synthesis for
            # audit, replay, and downstream governance consumption.
            try:
                _const_l12 = self._run_constitutional_phase5(
                    l12_verdict=l12_verdict,
                    gates=gates,
                    synthesis=synthesis,
                    phase1_status=_phase1_result.status.value,
                    l2_layer=l2,
                    l9_layer=l9,
                )
                synthesis["constitutional_phase5"] = _const_l12
                self._annotate_universe_ranking_with_l12(
                    synthesis.get("universe_ranking", {}),
                    _const_l12,
                )
            except Exception as _cp5_exc:
                logger.warning(
                    "[Pipeline v8.0] Constitutional Phase 5 overlay failed (non-fatal): {}",
                    _cp5_exc,
                )
                synthesis["constitutional_phase5"] = {"error": str(_cp5_exc)}

            # ═══════════════════════════════════════════════════════
            # PHASE 6 -- TWO-PASS L13 GOVERNANCE (from Sovereign)
            #   Pass 1: baseline (meta=1.0) -> L15 meta -> Pass 2: refined
            # ═══════════════════════════════════════════════════════
            reflective_pass1, reflective_pass2, l15_meta, sovereignty, enforcement = (
                self._run_reflective_governance_cycle(
                    symbol=symbol,
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    gates=gates,
                    layers_executed=layers_executed,
                    engines_invoked=engines_invoked,
                )
            )

            # ═══════════════════════════════════════════════════════
            # SIGNAL RATE THROTTLE — prevent over-trading
            # If the final verdict is still EXECUTE_* after enforcement,
            # check whether this symbol has exceeded the emission rate
            # limit. If so, downgrade to HOLD.
            # ═══════════════════════════════════════════════════════
            self._apply_effective_verdict_controls(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                legacy_verdict=legacy_verdict,
                safe_mode=safe_mode,
                errors=errors,
            )

            # ═══════════════════════════════════════════════════════
            # PHASE 8.6 -- GOVERNANCE HOOK (drift + rollout, optional)
            # ═══════════════════════════════════════════════════════
            try:
                from governance.drift_monitor import DriftMonitor  # noqa: PLC0415
                from governance.pipeline_hook import GovernancePipelineHook  # noqa: PLC0415
                from governance.rollout_controller import RolloutController  # noqa: PLC0415

                _gov_hook = GovernancePipelineHook(
                    drift_monitor=DriftMonitor(redis_client=getattr(self, "_redis", None)),
                    rollout_controller=RolloutController(redis_client=getattr(self, "_redis", None)),
                )
                _gov_result = _gov_hook.run(
                    {
                        "pair": symbol,
                        "synthesis": synthesis,
                        "l12_verdict": l12_verdict,
                    }
                )
                synthesis["governance"] = _gov_result.get("governance")
            except ImportError:
                pass  # Governance module optional
            except Exception as gov_exc:
                logger.debug(f"[Pipeline v8.0] Governance hook error for {symbol}: {gov_exc}")

            # ═══════════════════════════════════════════════════════
            # PHASE 8 -- L14 JSON EXPORT + FINAL ASSEMBLY
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 8: L14/Result Assembly -- {symbol}")
            engines_invoked.append("L14Assembler")

            execution_map = build_execution_map(
                pair=symbol,
                timestamp=now.isoformat(),
                layers_executed=layers_executed,
                engines_invoked=engines_invoked,
                halt_reason=None,
                constitutional_verdict=str(l12_verdict.get("verdict", "UNKNOWN")),
                layer_timings_ms=layer_timings_ms,
                dag=dag_payload,
            )

            latency_ms = (time.time() - start_time) * 1000

            # Use best available reflective pass for L14
            best_reflective = reflective_pass2 or reflective_pass1

            l14_json = self._build_l14_json(
                symbol=symbol,
                now=now,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective=best_reflective,
                gates=gates,
                l1=l1,
                l2=l2,
                l3=l3,
                l5=l5,
                l6=l6,
                l8=l8,
                l9=l9,
                l10=l10,
                l11=l11,
                sovereignty=sovereignty,
                enforcement=enforcement,
                latency_ms=latency_ms,
            )

            result = PipelineResult(
                schema=self.VERSION,
                pair=symbol,
                timestamp=now.isoformat(),
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective_pass1=reflective_pass1,
                reflective_pass2=reflective_pass2,
                l15_meta=l15_meta,
                l14_json=l14_json,
                sovereignty=sovereignty,
                enforcement=enforcement,
                execution_map=execution_map,
                latency_ms=latency_ms,
                errors=errors,
            )

            result_dict = result.to_dict()

            # ── Export per-layer constitutional diagnostics (non-invasive) ──
            # L2/L1/L7/L8/L9 already compute diagnostics internally for constitutional
            # logging; surface them on the pipeline result so downstream consumers
            # (verdict cache, API, operator CLI) can read them without re-parsing
            # nested layer payloads. This does NOT alter verdict logic — L12 is
            # still the sole decision authority.
            _diag_exports: tuple[tuple[Any, str], ...] = (
                (l1, "context_diagnostics"),
                (l2, "mta_diagnostics"),
                (l7, "edge_diagnostics"),
                (l8, "integrity_diagnostics"),
                (l9, "structure_diagnostics"),
            )
            for _layer_payload, _diag_key in _diag_exports:
                _const = _layer_payload.get("constitutional") if isinstance(_layer_payload, dict) else None
                if isinstance(_const, dict):
                    _diag = _const.get(_diag_key)
                    if isinstance(_diag, dict):
                        result_dict[_diag_key] = dict(_diag)

            # ── Tick→verdict end-to-end latency ────────────────────
            if tick_ts is not None:
                e2e_latency = time.time() - tick_ts
                TICK_TO_VERDICT_LATENCY.labels(symbol=symbol).observe(e2e_latency)  # noqa: F821
                result_dict["tick_to_verdict_s"] = round(e2e_latency, 4)

            # ── P2-8: freshness–latency correlation ────────────────
            try:
                from monitoring.execution_metrics import (  # noqa: PLC0415
                    flag_freshness_latency_correlation,
                    is_reconnect_storm,
                )

                feed_age = 0.0
                try:
                    from core.metrics import FEED_AGE  # noqa: PLC0415

                    child = FEED_AGE._children.get((("symbol", symbol),))  # noqa: SLF001
                    if child is not None:
                        feed_age = child.value
                except Exception:
                    pass
                stale = feed_age > 15.0
                slow = latency_ms > 2000.0
                storm = is_reconnect_storm()
                flag_freshness_latency_correlation(symbol, stale and (slow or storm))
            except Exception:
                pass

            result_dict["rqi"] = synthesis.get("system", {}).get("rqi", 0.0)

            self._record_metrics(symbol, result_dict)
            return result_dict

        except Exception as exc:
            logger.error(f"[Pipeline v8.0] Fatal error for {symbol}: {exc}", exc_info=True)
            errors.append(f"FATAL_ERROR: {exc}")
            latency_ms = (time.time() - start_time) * 1000
            return _early_exit_with_map(errors, latency_ms)

    # ══════════════════════════════════════════════════════════════
    #  9-GATE CONSTITUTIONAL CHECK
    # ══════════════════════════════════════════════════════════════

    def _evaluate_9_gates(
        self,
        layer_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate the 9 constitutional gates.

        Delegates to pipeline.phases.gates.evaluate_9_gates.
        """
        return evaluate_9_gates(layer_results)

    # ══════════════════════════════════════════════════════════════
    #  L14 -- JSON OUTPUT & DATA EXPORT
    # ══════════════════════════════════════════════════════════════

    def _build_l14_json(  # noqa: PLR0913
        self,
        symbol: str,
        now: datetime,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective: dict[str, Any] | None,
        gates: dict[str, Any],
        l1: dict[str, Any],  # noqa: ARG002
        l2: dict[str, Any],  # noqa: ARG002
        l3: dict[str, Any],  # noqa: ARG002
        l5: dict[str, Any],  # noqa: ARG002
        l6: dict[str, Any],  # noqa: ARG002
        l8: dict[str, Any],  # noqa: ARG002
        l9: dict[str, Any],  # noqa: ARG002
        l10: dict[str, Any],
        l11: dict[str, Any],  # noqa: ARG002
        sovereignty: dict[str, Any],
        enforcement: dict[str, Any] | None,
        latency_ms: float,
    ) -> dict[str, Any]:
        """Build full L14 JSON export matching v8.0 schema.

        Delegates to pipeline.phases.assembly.build_l14_json.
        """
        return build_l14_json(
            schema_version=self.VERSION,
            symbol=symbol,
            now=now,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            reflective=reflective,
            gates=gates,
            l10=l10,
            sovereignty=sovereignty,
            enforcement=enforcement,
            latency_ms=latency_ms,
        )

    # ══════════════════════════════════════════════════════════════
    #  VAULT SYNC COMPUTATION (3-component)
    # ══════════════════════════════════════════════════════════════

    def _compute_vault_sync(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],  # noqa: ARG002
        reflective: dict[str, Any] | None,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Compute vault sync (3-component) + base sovereignty level.

        Delegates to pipeline.phases.vault.compute_vault_sync.
        """
        return compute_vault_sync(synthesis, self._vault_checker)

    # ══════════════════════════════════════════════════════════════
    #  CONSTITUTIONAL PHASE 5 OVERLAY
    # ══════════════════════════════════════════════════════════════

    def _run_constitutional_phase5(
        self,
        l12_verdict: dict[str, Any],
        gates: dict[str, Any],
        synthesis: dict[str, Any],
        *,
        phase1_status: str = "PASS",
        l2_layer: dict[str, Any] | None = None,
        l9_layer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the constitutional L12 router evaluator as a Phase 5 overlay.

        Maps the existing pipeline gate results + verdict into the
        constitutional L12Input contract and evaluates. The result is
        purely diagnostic / audit — it does NOT override the legacy
        verdict. Analysis-only, no execution authority.
        """
        # Map 9-gate results to constitutional gate statuses
        int(gates.get("total_gates", 9))
        total_passed = int(gates.get("total_passed", 0))

        def _gate_to_status(key: str) -> str:
            val = str(gates.get(key, "FAIL")).upper()
            return "PASS" if val == "PASS" else ("WARN" if val == "CONDITIONAL" else "FAIL")

        foundation_status = (
            phase1_status
            if phase1_status == "FAIL"
            else ("PASS" if _gate_to_status("gate_6_integrity") == "PASS" else "WARN")
        )
        scoring_status = "PASS" if _gate_to_status("gate_4_conf12") == "PASS" else "WARN"
        structure_status = _gate_to_status("gate_1_tii")
        probability_status = _gate_to_status("gate_2_montecarlo")
        integrity_status = _gate_to_status("gate_3_frpc")
        firewall_status = _gate_to_status("gate_7_propfirm")
        risk_chain_status = _gate_to_status("gate_5_rr")
        governance_status = _gate_to_status("gate_9_drawdown")
        probability_evidence = synthesis.get("probability_evidence", {})
        l2_layer = l2_layer if isinstance(l2_layer, dict) else {}
        l9_layer = l9_layer if isinstance(l9_layer, dict) else {}
        verdict_direction = l12_verdict.get("direction", synthesis.get("execution", {}).get("direction"))

        _emit_canary_event(
            f"event=l12_synthesis_enter symbol={synthesis.get('symbol') or synthesis.get('pair') or 'UNKNOWN'} "
            f"direction={synthesis.get('execution', {}).get('direction')} "
            f"phase1_status={phase1_status} phase3_status={structure_status}"
        )

        # Synthesis score from verdict engine.
        # verdict_engine.generate_l12_verdict() returns "confidence" as a band
        # string (LOW/MEDIUM/HIGH/VERY_HIGH). Historically this site called
        # float(...) directly, producing 74+ non-fatal ValueErrors/min in the
        # engine log ("could not convert string to float: 'LOW'"). The coercer
        # accepts both numeric and band forms and surfaces a warning on
        # unmappable values instead of silently defaulting.
        synthesis_score, _conf_warning = _coerce_confidence_to_score(l12_verdict.get("confidence"))
        if _conf_warning is not None:
            logger.warning(
                "[Pipeline v8.0] Phase 5 confidence not mappable: value={!r} -> score=0.0 (warning={})",
                l12_verdict.get("confidence"),
                _conf_warning,
            )

        evaluator = L12RouterEvaluator()
        l12_input = L12Input(
            input_ref=str(synthesis.get("symbol") or synthesis.get("pair") or "UNKNOWN"),
            timestamp=str(
                synthesis.get("timestamp")
                or synthesis.get("system", {}).get("timestamp")
                or datetime.now(_TZ_GMT8).isoformat()
            ),
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status=foundation_status,
            scoring_status=scoring_status,
            enrichment_status="PASS" if total_passed >= 7 else "WARN",
            structure_status=structure_status,
            risk_chain_status=risk_chain_status,
            l7_status=str(probability_evidence.get("status", probability_status)).upper(),
            l7_evidence_score=float(probability_evidence.get("evidence_score", 0.0) or 0.0),
            l7_confidence_penalty=float(probability_evidence.get("confidence_penalty", 0.0) or 0.0),
            l7_hard_stop=bool(probability_evidence.get("hard_stop", False)),
            l7_advisory_continuation=bool(probability_evidence.get("advisory_continuation", False)),
            l7_hard_blockers=[str(x) for x in probability_evidence.get("hard_blockers", [])],
            l7_soft_blockers=[str(x) for x in probability_evidence.get("soft_blockers", [])],
            l2_status=str(l2_layer.get("status", "WARN" if phase1_status == "WARN" else "PASS")).upper(),
            l2_evidence_score=float(l2_layer.get("evidence_score", 0.0) or 0.0),
            l2_confidence_penalty=float(l2_layer.get("confidence_penalty", 0.0) or 0.0),
            l2_hard_stop=bool(l2_layer.get("hard_stop", False)),
            l2_advisory_continuation=bool(l2_layer.get("advisory_continuation", False)),
            l2_hard_blockers=[str(x) for x in l2_layer.get("hard_blockers", [])],
            l2_soft_blockers=[str(x) for x in l2_layer.get("soft_blockers", [])],
            l2_primary_conflict=str(l2_layer.get("mta_diagnostics", {}).get("primary_conflict", "")) or None,
            l9_status=str(l9_layer.get("status", structure_status)).upper(),
            l9_evidence_score=float(l9_layer.get("evidence_score", 0.0) or 0.0),
            l9_confidence_penalty=float(l9_layer.get("confidence_penalty", 0.0) or 0.0),
            l9_hard_stop=bool(l9_layer.get("hard_stop", False)),
            l9_advisory_continuation=bool(l9_layer.get("advisory_continuation", False)),
            l9_hard_blockers=[str(x) for x in l9_layer.get("hard_blockers", [])],
            l9_soft_blockers=[str(x) for x in l9_layer.get("soft_blockers", [])],
            l9_source_builder_state=str(l9_layer.get("structure_diagnostics", {}).get("source_builder_state", ""))
            or None,
            phase1_available=True,
            phase2_available=True,
            phase3_available=True,
            phase4_available=True,
            synthesis_score=synthesis_score,
            integrity_status=integrity_status,
            probability_status=probability_status,
            firewall_status=firewall_status,
            governance_status=governance_status,
        )
        result = evaluator.evaluate(l12_input)
        result_dict = result.to_dict()
        self._emit_verdict_stream_event(
            event="l12_final_verdict",
            symbol=l12_input.input_ref,
            authority="L12",
            verdict_stream="phase5_overlay",
            verdict=result_dict.get("verdict"),
            direction=verdict_direction,
            extras={
                "verdict_status": result_dict.get("verdict_status"),
                "hard_blockers": result_dict.get("blocker_codes", []),
                "soft_warnings": result_dict.get("warning_codes", []),
                "evidence_score": result_dict.get("score_numeric"),
                "execution_allowed": result_dict.get("continuation_allowed"),
                "l2_status": result_dict.get("audit", {}).get("l2_evidence", {}).get("status"),
                "l7_status": result_dict.get("audit", {}).get("l7_evidence", {}).get("status"),
                "l9_status": result_dict.get("audit", {}).get("l9_evidence", {}).get("status"),
            },
        )
        return result_dict

    @staticmethod
    def _emit_verdict_stream_event(
        *,
        event: str,
        symbol: str,
        authority: str,
        verdict_stream: str,
        verdict: Any,
        direction: Any,
        extras: dict[str, Any] | None = None,
    ) -> None:
        parts = [
            f"event={event}",
            f"symbol={symbol}",
            f"authority={authority}",
            f"verdict_stream={verdict_stream}",
            f"verdict={verdict}",
            f"direction={direction}",
        ]
        for key, value in (extras or {}).items():
            parts.append(f"{key}={value}")
        _emit_canary_event(" ".join(parts))

    def _run_reflective_governance_cycle(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        gates: dict[str, Any],
        layers_executed: list[str],
        engines_invoked: list[str],
    ) -> tuple[Any, Any, Any, dict[str, Any], Any]:
        reflective_pass1 = None
        reflective_pass2 = None
        l15_meta = None

        proceed = l12_verdict.get("proceed_to_L13", False) or l12_verdict.get("verdict", "").startswith("EXECUTE")
        l13_engine = self._get_l13_engine()
        l15_engine = self._get_l15_engine()

        if proceed:
            logger.info(f"[Pipeline v8.0] Phase 6: Two-Pass L13 Governance -- {symbol}")
            layers_executed.append("L13")
            engines_invoked.append("L13ReflectiveEngine")

            synthesis["_meta_integrity"] = 1.0
            reflective_pass1 = l13_engine.reflect(symbol, [l12_verdict], synthesis)

            sovereignty = self._compute_vault_sync(synthesis, l12_verdict, reflective_pass1)
            l15_meta = l15_engine.compute_meta(
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective_pass1=reflective_pass1,
                sovereignty=sovereignty,
                gates=gates,
            )
            layers_executed.append("L14")
            engines_invoked.append("L15MetaSovereigntyEngine")

            synthesis["_meta_integrity"] = l15_meta.get("meta_integrity", 1.0)
            reflective_pass2 = l13_engine.reflect(symbol, [l12_verdict], synthesis)
        else:
            sovereignty = self._compute_vault_sync(synthesis, l12_verdict, None)
            l15_meta = l15_engine.compute_meta(
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective_pass1=None,
                sovereignty=sovereignty,
                gates=gates,
            )
            layers_executed.append("L14")
            engines_invoked.append("L15MetaSovereigntyEngine")

        logger.info(f"[Pipeline v8.0] Phase 7: Sovereignty Enforcement -- {symbol}")
        engines_invoked.append("SovereigntyEnforcer")
        enforcement = l15_engine.enforce_sovereignty(
            l12_verdict=l12_verdict,
            reflective_pass1=reflective_pass1,
            reflective_pass2=reflective_pass2,
            meta=l15_meta,
            sovereignty=sovereignty,
        )
        return reflective_pass1, reflective_pass2, l15_meta, sovereignty, enforcement

    def _apply_market_context_guard(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        errors: list[str],
    ) -> None:
        if not self._market_context_guard_enabled:
            return

        source_verdict = str(l12_verdict.get("verdict", ""))
        if not source_verdict.startswith("EXECUTE"):
            return

        context = self._build_market_context(symbol=symbol, synthesis=synthesis, l12_verdict=l12_verdict)
        validation = validate_market_context(context)
        validation_payload = validation.to_dict()
        l12_verdict["market_context_validation"] = validation_payload
        synthesis["market_context_validation"] = validation_payload

        self._emit_verdict_stream_event(
            event="market_context_validation",
            symbol=symbol,
            authority="MARKET_CONTEXT",
            verdict_stream="post_l12_pre_throttle",
            verdict=source_verdict,
            direction=l12_verdict.get("direction"),
            extras={
                "mode": self._market_context_guard_mode,
                "final_direction": validation.final_direction,
                "direction_validated": validation.direction_validated,
                "action": validation.action,
                "reason": validation.reason,
            },
        )

        if validation.direction_validated or self._market_context_guard_mode != "block":
            return

        l12_verdict["verdict"] = "HOLD"
        l12_verdict["market_context_from"] = source_verdict
        l12_verdict["market_context_downgrade"] = True
        l12_verdict["effective_reason"] = "MARKET_CONTEXT_UNVALIDATED"
        errors.append(f"MARKET_CONTEXT_UNVALIDATED:{validation.action}")

    def _build_market_context(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        allow_execution_entry_price: bool = True,
    ) -> MarketContext:
        execution = synthesis.get("execution", {}) if isinstance(synthesis.get("execution"), dict) else {}
        direction = self._normalize_market_context_direction(
            l12_verdict.get("direction"),
            source_verdict=l12_verdict.get("verdict"),
            execution_direction=execution.get("direction"),
        )
        latest_tick = self._context_bus.get_latest_tick(symbol)
        latest_tick = latest_tick if isinstance(latest_tick, dict) else {}
        bid = self._coerce_positive_float(latest_tick.get("bid") or latest_tick.get("price"))
        ask = self._coerce_positive_float(latest_tick.get("ask") or latest_tick.get("price"))
        tick_mid = (bid + ask) / 2.0 if bid is not None and ask is not None else bid or ask
        latest_m15_close = self._latest_candle_close(symbol, "M15")
        latest_h1_close = self._latest_candle_close(symbol, "H1")
        entry_price = (
            self._coerce_positive_float(execution.get("entry_price")) if allow_execution_entry_price else None
        )
        pip_value = self._pip_value(symbol)
        structure = self._derive_price_structure(
            symbol=symbol,
            current_price=tick_mid or latest_m15_close or latest_h1_close or entry_price,
        )
        counter_structure = self._derive_counter_entry_structure(
            symbol=symbol,
            structure=structure,
            current_price=tick_mid or latest_m15_close or latest_h1_close or entry_price,
            pip_value=pip_value,
        )
        spread_quality = self._spread_quality(symbol)
        theme_alignment = self._market_theme_alignment_snapshot(synthesis, direction)
        basket_validation = self._basket_direction_validation_snapshot(
            symbol=symbol,
            direction=direction,
            synthesis=synthesis,
        )
        htf_context = self._resolve_htf_structure_context(symbol)

        return MarketContext(
            symbol=symbol,
            raw_allowed_direction=direction,
            bid=bid,
            ask=ask,
            pip_value=pip_value,
            price_at_signal_start=entry_price or latest_m15_close or latest_h1_close or tick_mid,
            price_at_5m_confirm=latest_m15_close or tick_mid,
            price_at_signal_end=tick_mid or latest_m15_close or latest_h1_close,
            m15_phase=self._derive_timeframe_phase(symbol, "M15"),
            h1_phase=self._derive_timeframe_phase(symbol, "H1"),
            h4_phase=self._derive_timeframe_phase(symbol, "H4"),
            d1_phase=self._derive_daily_phase_feed(symbol, htf_snapshot=htf_context),
            htf_daily_bias=self._optional_text_from_mapping(htf_context, "daily_bias"),
            htf_h4_structure=self._optional_text_from_mapping(htf_context, "h4_structure"),
            htf_price_location=self._optional_text_from_mapping(htf_context, "price_location"),
            htf_liquidity_context=self._optional_text_from_mapping(htf_context, "liquidity_context"),
            htf_allowed_playbook=self._optional_text_from_mapping(htf_context, "allowed_playbook"),
            htf_blocked_playbook=self._string_list_from_mapping(htf_context, "blocked_playbook"),
            htf_data_sufficient=self._optional_bool_from_mapping(htf_context, "data_sufficient"),
            htf_structure_reason=self._optional_text_from_mapping(htf_context, "reason"),
            theme_aligned=self._is_market_theme_aligned(synthesis, direction),
            theme_alignment=theme_alignment,
            counter_entry_theme_alignment=theme_alignment,
            base_basket_score=self._coerce_float_or_none(basket_validation.get("base_score")),
            quote_basket_score=self._coerce_float_or_none(basket_validation.get("quote_score")),
            pair_direction_alignment=self._coerce_float_or_none(basket_validation.get("pair_alignment")),
            basket_blockers=self._basket_blockers_from_validation(basket_validation),
            basket_validation=basket_validation or None,
            spread_normal=spread_quality["spread_normal"],
            spread_pips=spread_quality["spread_pips"],
            max_allowed_spread_pips=spread_quality["max_allowed_spread_pips"],
            market_bias=self._derive_market_bias(symbol),
            trend_direction=self._derive_market_bias(symbol),
            price_position=structure.get("price_position"),
            main_support=structure.get("main_support"),
            main_resistance=structure.get("main_resistance"),
            range_position=structure.get("range_position"),
            **counter_structure,
        )

    @staticmethod
    def _normalize_market_context_direction(
        *raw_values: Any,
        source_verdict: Any | None = None,
        execution_direction: Any | None = None,
    ) -> str | None:
        from schemas.direction import normalize_direction  # noqa: PLC0415

        for raw in (source_verdict, *raw_values, execution_direction):
            direction = normalize_direction(str(raw) if raw else None, str(source_verdict) if source_verdict else None)
            if direction in {"BUY", "SELL"}:
                return direction
        return None

    def _latest_tick_mid(self, symbol: str) -> float | None:
        tick = self._context_bus.get_latest_tick(symbol)
        if not isinstance(tick, dict):
            return None
        bid = self._coerce_positive_float(tick.get("bid") or tick.get("price"))
        ask = self._coerce_positive_float(tick.get("ask") or tick.get("price"))
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return bid or ask

    def _latest_candle_close(self, symbol: str, timeframe: str) -> float | None:
        candles = self._context_bus.get_candle_history(symbol, timeframe, count=1)
        if not candles:
            return None
        return self._candle_price(candles[-1], "close")

    def _derive_price_structure(self, *, symbol: str, current_price: float | None) -> dict[str, Any]:
        candles = self._context_bus.get_candle_history(symbol, "H1", count=24)
        h1_bar_count = len(candles)
        m15_structure_bar_count = 0
        if len(candles) < 4:
            candles = self._context_bus.get_candle_history(symbol, "M15", count=32)
            m15_structure_bar_count = len(candles)
        highs = [price for candle in candles if (price := self._candle_price(candle, "high")) is not None]
        lows = [price for candle in candles if (price := self._candle_price(candle, "low")) is not None]
        if current_price is None or not highs or not lows:
            return {
                "price_position": None,
                "main_support": None,
                "main_resistance": None,
                "range_position": None,
                "h1_bar_count": h1_bar_count,
                "m15_structure_bar_count": m15_structure_bar_count,
            }

        main_support = min(lows)
        main_resistance = max(highs)
        price_range = main_resistance - main_support
        if price_range <= 0:
            return {
                "price_position": None,
                "main_support": main_support,
                "main_resistance": main_resistance,
                "range_position": None,
                "h1_bar_count": h1_bar_count,
                "m15_structure_bar_count": m15_structure_bar_count,
            }

        range_position = max(0.0, min(1.0, (current_price - main_support) / price_range))
        tolerance = max(price_range * 0.12, current_price * 0.0008)
        if abs(main_resistance - current_price) <= tolerance or range_position >= 0.88:
            price_position = "MAIN_RESISTANCE"
        elif abs(current_price - main_support) <= tolerance or range_position <= 0.12:
            price_position = "MAIN_SUPPORT"
        else:
            price_position = "MID_RANGE"
        return {
            "price_position": price_position,
            "main_support": main_support,
            "main_resistance": main_resistance,
            "range_position": round(range_position, 4),
            "h1_bar_count": h1_bar_count,
            "m15_structure_bar_count": m15_structure_bar_count,
        }

    def _derive_counter_entry_structure(
        self,
        *,
        symbol: str,
        structure: dict[str, Any],
        current_price: float | None,
        pip_value: float,
    ) -> dict[str, Any]:
        candles = self._context_bus.get_candle_history(symbol, "M15", count=32)
        h1_candles = self._context_bus.get_candle_history(symbol, "H1", count=24)
        m15_bar_count = len(candles)
        latest = candles[-1] if candles else {}
        previous_candle = candles[-2] if len(candles) >= 2 else {}
        previous = candles[:-1]
        previous_lows = [price for candle in previous[-8:] if (price := self._candle_price(candle, "low")) is not None]
        previous_highs = [
            price for candle in previous[-8:] if (price := self._candle_price(candle, "high")) is not None
        ]
        latest_open = self._candle_price(latest, "open") if latest else None
        latest_high = self._candle_price(latest, "high") if latest else None
        latest_low = self._candle_price(latest, "low") if latest else None
        latest_close = self._candle_price(latest, "close") if latest else None
        previous_close = self._candle_price(previous_candle, "close") if previous_candle else None
        m15_range_atr_ratio, m15_body_atr_ratio = self._m15_expansion_ratios(candles)
        main_support = self._coerce_positive_float(structure.get("main_support"))
        main_resistance = self._coerce_positive_float(structure.get("main_resistance"))
        ladder = self._derive_price_ladders(
            current_price=current_price or latest_close,
            m15_candles=candles,
            h1_candles=h1_candles,
            main_support=main_support,
            main_resistance=main_resistance,
            pip_value=pip_value,
        )
        support_levels = ladder["support_levels"]
        resistance_levels = ladder["resistance_levels"]
        minor_support = support_levels[0] if support_levels else None
        major_support = support_levels[1] if len(support_levels) > 1 else main_support
        minor_resistance = resistance_levels[0] if resistance_levels else None
        major_resistance = resistance_levels[1] if len(resistance_levels) > 1 else main_resistance
        resistance_high = main_resistance
        resistance_low = main_resistance - (18.0 * pip_value) if main_resistance is not None else None
        support_high = minor_support
        support_low = major_support if major_support is not None else main_support
        sl_buffer = 8.0 * pip_value
        m15_close_above_resistance = (
            latest_close is not None and resistance_high is not None and latest_close > resistance_high
        )
        m15_breakout_retest_held = (
            previous_close is not None
            and latest_low is not None
            and latest_close is not None
            and resistance_high is not None
            and previous_close > resistance_high
            and latest_low <= resistance_high + (2.0 * pip_value)
            and latest_close >= resistance_high
        )
        m15_rejection_from_resistance = (
            latest_high is not None
            and resistance_high is not None
            and latest_close is not None
            and latest_open is not None
            and latest_high >= resistance_high - (2.0 * pip_value)
            and latest_close < latest_open
        )
        m15_close_below_minor_support = (
            latest_close is not None and minor_support is not None and latest_close < minor_support
        )
        m15_close_below_support = latest_close is not None and support_low is not None and latest_close < support_low
        m15_breakdown_retest_held = (
            previous_close is not None
            and latest_high is not None
            and latest_close is not None
            and support_low is not None
            and previous_close < support_low
            and latest_high >= support_low - (2.0 * pip_value)
            and latest_close <= support_low
        )
        m15_rejection_from_support = (
            latest_low is not None
            and support_low is not None
            and latest_close is not None
            and latest_open is not None
            and latest_low <= support_low + (2.0 * pip_value)
            and latest_close > latest_open
        )
        m15_close_above_minor_resistance = (
            latest_close is not None and minor_resistance is not None and latest_close > minor_resistance
        )
        support_ladder_ready = len(support_levels) >= 2
        resistance_ladder_ready = len(resistance_levels) >= 2
        support_ladder_missing_reason = (
            None
            if support_ladder_ready
            else self._ladder_missing_reason(
                candle_count=m15_bar_count,
                previous_levels=support_levels or previous_lows,
                main_level=main_support,
                missing_label="support",
            )
        )
        resistance_ladder_missing_reason = (
            None
            if resistance_ladder_ready
            else self._ladder_missing_reason(
                candle_count=m15_bar_count,
                previous_levels=resistance_levels or previous_highs,
                main_level=main_resistance,
                missing_label="resistance",
            )
        )
        continuation_sl_safe: float | None = None
        if structure.get("price_position") == "MAIN_RESISTANCE" and resistance_low is not None:
            continuation_sl_safe = resistance_low - (2.0 * sl_buffer)
        elif structure.get("price_position") == "MAIN_SUPPORT" and support_high is not None:
            continuation_sl_safe = support_high + (2.0 * sl_buffer)
        return {
            "key_resistance": main_resistance,
            "key_support": minor_support or main_support,
            "sell_rejection_low": resistance_low,
            "sell_rejection_high": resistance_high,
            "buy_pullback_low": support_low,
            "buy_pullback_high": support_high,
            "breakout_retest_low": resistance_low,
            "breakout_retest_high": resistance_high,
            "resistance_low": resistance_low,
            "resistance_high": resistance_high,
            "minor_support": minor_support,
            "major_support": major_support,
            "m15_close": latest_close,
            "m15_open": latest_open,
            "m15_high": latest_high,
            "m15_low": latest_low,
            "m15_range_atr_ratio": m15_range_atr_ratio,
            "m15_body_atr_ratio": m15_body_atr_ratio,
            "m15_close_above_resistance": m15_close_above_resistance,
            "m15_breakout_retest_held": m15_breakout_retest_held,
            "m15_rejection_from_resistance": m15_rejection_from_resistance,
            "m15_close_below_minor_support": m15_close_below_minor_support,
            "support_low": support_low,
            "support_high": support_high,
            "minor_resistance": minor_resistance,
            "m15_close_below_support": m15_close_below_support,
            "m15_breakdown_retest_held": m15_breakdown_retest_held,
            "m15_rejection_from_support": m15_rejection_from_support,
            "m15_close_above_minor_resistance": m15_close_above_minor_resistance,
            "sl_buffer": sl_buffer,
            "continuation_sl_safe": continuation_sl_safe,
            "tp1_support": support_levels[0] if len(support_levels) > 0 else None,
            "tp2_support": support_levels[1] if len(support_levels) > 1 else None,
            "tp3_support": support_levels[2] if len(support_levels) > 2 else None,
            "tp4_support": support_levels[3] if len(support_levels) > 3 else None,
            "tp1_resistance": minor_resistance,
            "tp2_resistance": major_resistance,
            "tp3_resistance": resistance_levels[2] if len(resistance_levels) > 2 else None,
            "tp4_resistance": resistance_levels[3] if len(resistance_levels) > 3 else None,
            "m15_bar_count": m15_bar_count,
            "h1_bar_count": int(structure.get("h1_bar_count") or 0),
            "support_ladder_ready": support_ladder_ready,
            "resistance_ladder_ready": resistance_ladder_ready,
            "tradeplan_context_ready": support_ladder_ready and resistance_ladder_ready,
            "support_ladder_missing_reason": support_ladder_missing_reason,
            "resistance_ladder_missing_reason": resistance_ladder_missing_reason,
        }

    def _derive_price_ladders(
        self,
        *,
        current_price: float | None,
        m15_candles: list[dict[str, Any]],
        h1_candles: list[dict[str, Any]],
        main_support: float | None,
        main_resistance: float | None,
        pip_value: float,
    ) -> dict[str, list[float]]:
        if current_price is None or current_price <= 0 or pip_value <= 0:
            return {"support_levels": [], "resistance_levels": []}

        m15_lows = [price for candle in m15_candles if (price := self._candle_price(candle, "low")) is not None]
        m15_highs = [price for candle in m15_candles if (price := self._candle_price(candle, "high")) is not None]
        h1_lows = [price for candle in h1_candles if (price := self._candle_price(candle, "low")) is not None]
        h1_highs = [price for candle in h1_candles if (price := self._candle_price(candle, "high")) is not None]

        min_distance = 2.0 * pip_value
        support_candidates = [
            level
            for level in [*m15_lows, *h1_lows, main_support]
            if level is not None and level < current_price - min_distance
        ]
        resistance_candidates = [
            level
            for level in [*m15_highs, *h1_highs, main_resistance]
            if level is not None and level > current_price + min_distance
        ]
        support_levels = self._cluster_ladder_levels(
            support_candidates,
            current_price=current_price,
            pip_value=pip_value,
            side="support",
        )
        resistance_levels = self._cluster_ladder_levels(
            resistance_candidates,
            current_price=current_price,
            pip_value=pip_value,
            side="resistance",
        )
        return {
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
        }

    @staticmethod
    def _cluster_ladder_levels(
        levels: list[float],
        *,
        current_price: float,
        pip_value: float,
        side: str,
    ) -> list[float]:
        if not levels:
            return []
        cluster_width = max(5.0 * pip_value, current_price * 0.00008)
        ordered = sorted(levels, reverse=side == "support")
        clusters: list[list[float]] = []
        for level in ordered:
            if side == "support" and level >= current_price:
                continue
            if side == "resistance" and level <= current_price:
                continue
            if not clusters or abs(level - clusters[-1][-1]) > cluster_width:
                clusters.append([level])
            else:
                clusters[-1].append(level)

        representatives: list[float] = []
        for cluster in clusters:
            representative = max(cluster) if side == "support" else min(cluster)
            rounded = WolfConstitutionalPipeline._round_ladder_level(representative)
            if rounded is not None and rounded not in representatives:
                representatives.append(rounded)
        return representatives[:4]

    @staticmethod
    def _round_ladder_level(value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 3 if abs(float(value)) >= 10 else 5)

    @staticmethod
    def _ladder_missing_reason(
        *,
        candle_count: int,
        previous_levels: list[float],
        main_level: float | None,
        missing_label: str,
    ) -> str:
        if candle_count <= 0:
            return "NO_M15_CANDLE_HISTORY"
        if not previous_levels and main_level is None:
            return f"NO_M15_H1_{missing_label.upper()}_LEVELS"
        if main_level is None:
            return f"NO_MAIN_{missing_label.upper()}"
        if not previous_levels:
            return f"NO_MINOR_{missing_label.upper()}_PREVIOUS_LEVELS"
        return f"{missing_label.upper()}_LADDER_MISSING"

    def _m15_expansion_ratios(
        self, candles: list[dict[str, Any]], period: int = 14
    ) -> tuple[float | None, float | None]:
        if len(candles) < 3:
            return None, None
        latest = candles[-1]
        latest_open = self._candle_price(latest, "open")
        latest_high = self._candle_price(latest, "high")
        latest_low = self._candle_price(latest, "low")
        latest_close = self._candle_price(latest, "close")
        if latest_open is None or latest_high is None or latest_low is None or latest_close is None:
            return None, None

        end = len(candles) - 1
        start = max(1, end - period)
        true_ranges: list[float] = []
        for index in range(start, end):
            candle = candles[index]
            previous_close = self._candle_price(candles[index - 1], "close")
            high = self._candle_price(candle, "high")
            low = self._candle_price(candle, "low")
            if previous_close is None or high is None or low is None:
                continue
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        if not true_ranges:
            return None, None

        atr = sum(true_ranges) / len(true_ranges)
        if atr <= 0.0:
            return None, None
        range_ratio = (latest_high - latest_low) / atr
        body_ratio = abs(latest_close - latest_open) / atr
        return round(range_ratio, 3), round(body_ratio, 3)

    @staticmethod
    def _pip_value(symbol: str) -> float:
        return 0.01 if "JPY" in symbol.upper() else 0.0001

    def _derive_market_bias(self, symbol: str) -> str | None:
        candles = self._context_bus.get_candle_history(symbol, "H1", count=8)
        if len(candles) < 2:
            return None
        first = self._candle_price(candles[0], "close")
        latest = self._candle_price(candles[-1], "close")
        if first is None or latest is None:
            return None
        if latest > first:
            return "BUY"
        if latest < first:
            return "SELL"
        return None

    def _derive_daily_phase_feed(
        self,
        symbol: str,
        *,
        htf_snapshot: dict[str, Any] | None = None,
    ) -> str | None:
        """HTF Daily Phase Feed (flag-guarded, default ON).

        Returns a Daily phase string for ``MarketContext.d1_phase`` so the golden
        matcher's already-written but dormant Daily-aware rules stop being dead
        code. Single source of truth: the H1 HTF snapshot's ``daily_bias`` when it
        has a real read; falls back to a 2-bar D1 phase derivation during the
        transition window (e.g. snapshot still warming up).

        Pure observability/context — it never blocks execution and never mutates a
        verdict. Set ``HTF_DAILY_PHASE_FEED_ENABLED=false`` to return ``None`` and
        preserve legacy matcher decisions.
        Any failure is swallowed (Daily context must never break the pipeline).
        """
        if os.getenv("HTF_DAILY_PHASE_FEED_ENABLED", "true").strip().lower() != "true":
            return None
        try:
            bias = (
                self._optional_text_from_mapping(htf_snapshot, "daily_bias")
                if isinstance(htf_snapshot, dict)
                else self._htf_snapshot_resolver.resolve(symbol).daily_bias
            )
            if bias and bias != "NO_BIAS":
                return bias
        except Exception as exc:  # pragma: no cover - defensive; context must not break execution
            logger.debug("[HTFDailyPhaseFeed] snapshot daily_bias unavailable for {}: {}", symbol, exc)
        try:
            return self._derive_timeframe_phase(symbol, "D1")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[HTFDailyPhaseFeed] D1 fallback failed for {}: {}", symbol, exc)
            return None

    def _resolve_htf_structure_context(self, symbol: str) -> dict[str, Any] | None:
        """Resolve non-executable HTF structure context for watch/decision payloads."""
        if os.getenv("HTF_STRUCTURE_CONTEXT_ENABLED", "true").strip().lower() != "true":
            return None
        try:
            snapshot = self._htf_snapshot_resolver.resolve(symbol)
        except Exception as exc:  # pragma: no cover - defensive; context must not break execution
            logger.debug("[HTFStructureContext] resolve skipped for {}: {}", symbol, exc)
            return None
        return self._htf_structure_context_payload(snapshot.to_dict())

    @staticmethod
    def _htf_structure_context_payload(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(snapshot, dict):
            return None
        context = {
            "source_event": "HTFStructureSnapshot",
            "daily_bias": WolfConstitutionalPipeline._optional_text_from_mapping(snapshot, "daily_bias"),
            "h4_structure": WolfConstitutionalPipeline._optional_text_from_mapping(snapshot, "h4_structure"),
            "price_location": WolfConstitutionalPipeline._optional_text_from_mapping(snapshot, "price_location"),
            "liquidity_context": WolfConstitutionalPipeline._optional_text_from_mapping(snapshot, "liquidity_context"),
            "allowed_playbook": WolfConstitutionalPipeline._optional_text_from_mapping(snapshot, "allowed_playbook"),
            "blocked_playbook": WolfConstitutionalPipeline._string_list_from_mapping(snapshot, "blocked_playbook"),
            "data_sufficient": WolfConstitutionalPipeline._optional_bool_from_mapping(snapshot, "data_sufficient"),
            "reason": WolfConstitutionalPipeline._optional_text_from_mapping(snapshot, "reason"),
            "valid_for_execution": False,
            "execution_impact": False,
            "is_final_signal": False,
            "advisory_only": True,
        }
        return {key: value for key, value in context.items() if value is not None}

    @staticmethod
    def _htf_structure_context_from_market_context(context: Any | None) -> dict[str, Any] | None:
        if context is None:
            return None
        def _field(name: str) -> Any:
            if isinstance(context, dict):
                return context.get(name)
            return getattr(context, name, None)

        payload = {
            "source_event": "HTFStructureSnapshot",
            "daily_bias": _field("htf_daily_bias") or _field("d1_phase"),
            "h4_structure": _field("htf_h4_structure") or _field("h4_phase"),
            "price_location": _field("htf_price_location"),
            "liquidity_context": _field("htf_liquidity_context"),
            "allowed_playbook": _field("htf_allowed_playbook"),
            "blocked_playbook": WolfConstitutionalPipeline._string_list_value(_field("htf_blocked_playbook")),
            "data_sufficient": _field("htf_data_sufficient"),
            "reason": _field("htf_structure_reason"),
            "valid_for_execution": False,
            "execution_impact": False,
            "is_final_signal": False,
            "advisory_only": True,
        }
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _optional_text_from_mapping(source: dict[str, Any] | None, key: str) -> str | None:
        if not isinstance(source, dict):
            return None
        text = str(source.get(key) or "").strip()
        return text or None

    @staticmethod
    def _optional_bool_from_mapping(source: dict[str, Any] | None, key: str) -> bool | None:
        if not isinstance(source, dict):
            return None
        value = source.get(key)
        return value if isinstance(value, bool) else None

    @staticmethod
    def _string_list_from_mapping(source: dict[str, Any] | None, key: str) -> list[str] | None:
        if not isinstance(source, dict):
            return None
        return WolfConstitutionalPipeline._string_list_value(source.get(key))

    @staticmethod
    def _string_list_value(value: Any) -> list[str] | None:
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else None
        if isinstance(value, (list, tuple, set)):
            values = [str(item).strip() for item in value if str(item or "").strip()]
            return values or None
        return None

    def _derive_timeframe_phase(self, symbol: str, timeframe: str) -> str | None:
        candles = self._context_bus.get_candle_history(symbol, timeframe, count=2)
        if len(candles) < 2:
            return None
        previous = candles[-2]
        latest = candles[-1]
        previous_close = self._candle_price(previous, "close")
        latest_open = self._candle_price(latest, "open")
        latest_close = self._candle_price(latest, "close")
        if previous_close is None or latest_open is None or latest_close is None:
            return None

        bullish = latest_close >= previous_close and latest_close >= latest_open
        bearish = latest_close <= previous_close and latest_close <= latest_open
        if timeframe.upper() == "M15":
            if bullish:
                return "BULLISH_PULLBACK"
            if bearish:
                return "BEARISH_PULLBACK"
            return "HIGH_BASE_CONTINUATION" if latest_close >= previous_close else "LOWER_HIGH"

        if bullish:
            return "BULLISH"
        if bearish:
            return "BEARISH"
        return "UPTREND" if latest_close >= previous_close else "DOWNTREND"

    def _is_market_theme_aligned(self, synthesis: dict[str, Any], direction: str | None) -> bool | None:
        if direction not in {"BUY", "SELL"}:
            return None
        execution = synthesis.get("execution", {}) if isinstance(synthesis.get("execution"), dict) else {}
        diagnostics = execution.get("direction_diagnostics", {})
        if isinstance(diagnostics, dict):
            conflicts = diagnostics.get("conflicts")
            if isinstance(conflicts, list) and conflicts:
                return False
            sources = diagnostics.get("sources")
            if isinstance(sources, dict):
                for raw in sources.values():
                    source_direction = self._direction_hint(raw)
                    if source_direction and source_direction != direction:
                        return False

        legacy_fta = synthesis.get("legacy_fta", {})
        if isinstance(legacy_fta, dict) and legacy_fta.get("legacy_fta_present"):
            legacy_direction = self._direction_hint(legacy_fta.get("direction"))
            if legacy_direction and legacy_direction != direction:
                return False

        return True

    def _market_theme_alignment_snapshot(self, synthesis: dict[str, Any], direction: str | None) -> str | None:
        if direction not in {"BUY", "SELL"}:
            return None
        execution = synthesis.get("execution", {}) if isinstance(synthesis.get("execution"), dict) else {}
        diagnostics = execution.get("direction_diagnostics", {})
        if isinstance(diagnostics, dict):
            conflicts = diagnostics.get("conflicts")
            if isinstance(conflicts, list) and conflicts:
                return "DIRECTION_DIAGNOSTICS_CONFLICT"
            sources = diagnostics.get("sources")
            if isinstance(sources, dict):
                aligned_sources: list[str] = []
                conflicting_sources: list[str] = []
                for name, raw in sources.items():
                    source_direction = self._direction_hint(raw)
                    if source_direction == direction:
                        aligned_sources.append(str(name or "source").upper())
                    elif source_direction in {"BUY", "SELL"}:
                        conflicting_sources.append(str(name or "source").upper())
                if conflicting_sources:
                    return f"DIRECTION_DIAGNOSTICS_{'+'.join(conflicting_sources[:3])}_CONFLICT"
                if aligned_sources:
                    return f"{direction}_ALIGNED_BY_{'+'.join(aligned_sources[:3])}"

        legacy_fta = synthesis.get("legacy_fta", {})
        if isinstance(legacy_fta, dict) and legacy_fta.get("legacy_fta_present"):
            legacy_direction = self._direction_hint(legacy_fta.get("direction"))
            if legacy_direction == direction:
                return f"{direction}_ALIGNED_BY_LEGACY_FTA"
            if legacy_direction in {"BUY", "SELL"}:
                return "LEGACY_FTA_DIRECTION_CONFLICT"
        return None

    def _basket_direction_validation_snapshot(
        self,
        *,
        symbol: str,
        direction: str | None,
        synthesis: dict[str, Any],
    ) -> dict[str, Any]:
        if os.getenv("SIGNAL_BASKET_DIRECTION_VALIDATION_ENABLED", "false").strip().lower() != "true":
            return {}
        if direction not in {"BUY", "SELL"}:
            return {}
        ranking = synthesis.get("universe_ranking") if isinstance(synthesis, dict) else None
        if not isinstance(ranking, dict):
            return {}
        scores = ranking.get("currency_scores")
        if not isinstance(scores, dict) or not scores:
            return {}
        try:
            result = validate_basket_direction(symbol, direction, currency_scores=scores)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Pipeline v8.0] Basket validation failed (non-fatal): {}", exc)
            return {}
        payload = result.to_dict()
        payload["advisory_only"] = True
        return payload

    @staticmethod
    def _basket_blockers_from_validation(validation: dict[str, Any]) -> list[str] | None:
        if not validation or validation.get("data_ready") is not True:
            return None
        blockers = validation.get("blockers")
        if not isinstance(blockers, list):
            return None
        values = [str(item).strip().upper() for item in blockers if str(item or "").strip()]
        return values or None

    def _is_spread_normal(self, symbol: str) -> bool | None:
        return self._spread_quality(symbol)["spread_normal"]

    def _spread_quality(self, symbol: str) -> _SpreadQuality:
        tick = self._context_bus.get_latest_tick(symbol)
        if not isinstance(tick, dict):
            return {"spread_normal": None, "spread_pips": None, "max_allowed_spread_pips": None}
        bid = self._coerce_positive_float(tick.get("bid"))
        ask = self._coerce_positive_float(tick.get("ask"))
        spread_raw = self._coerce_positive_float(tick.get("spread"))
        if bid is not None and ask is not None:
            spread_price = abs(ask - bid)
        elif spread_raw is not None:
            spread_price = spread_raw
        else:
            return {"spread_normal": None, "spread_pips": None, "max_allowed_spread_pips": None}

        try:
            from config.pair_spreads import get_spread_pips  # noqa: PLC0415
            from utils.pip_calc import get_pip_multiplier  # noqa: PLC0415

            pip_multiplier = float(get_pip_multiplier(symbol))
            normal_spread_pips = float(get_spread_pips(symbol))
        except Exception:
            pip_multiplier = 100.0 if "JPY" in symbol.upper() else 10000.0
            normal_spread_pips = 2.0

        spread_pips = spread_price if spread_price > 0.05 else spread_price * pip_multiplier
        spread_multiplier = getattr(self, "_market_context_spread_multiplier", 2.5)
        max_allowed_spread_pips = normal_spread_pips * spread_multiplier
        return {
            "spread_normal": spread_pips <= max_allowed_spread_pips,
            "spread_pips": round(spread_pips, 2),
            "max_allowed_spread_pips": round(max_allowed_spread_pips, 2),
        }

    @staticmethod
    def _direction_hint(raw: Any) -> str | None:
        text = str(raw or "").strip().upper()
        if not text:
            return None
        if text in {"BUY", "LONG", "BULL", "BULLISH"} or "BULLISH" in text or text.endswith("_UP"):
            return "BUY"
        if text in {"SELL", "SHORT", "BEAR", "BEARISH"} or "BEARISH" in text or text.endswith("_DOWN"):
            return "SELL"
        return None

    @staticmethod
    def _candle_price(candle: dict[str, Any], field: str) -> float | None:
        aliases = {
            "open": ("open", "o"),
            "close": ("close", "c"),
            "high": ("high", "h"),
            "low": ("low", "l"),
        }
        for key in aliases.get(field, (field,)):
            value = WolfConstitutionalPipeline._coerce_positive_float(candle.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _coerce_positive_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _coerce_float_or_none(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _signal_throttle_market_contexts(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        source_verdict: Any | None = None,
    ) -> dict[str, MarketContext]:
        context_verdict = dict(l12_verdict)
        if source_verdict:
            context_verdict["verdict"] = source_verdict
        contexts = {
            symbol.upper(): self._build_market_context(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=context_verdict,
            )
        }
        contexts.update(
            self._pending_signal_market_contexts(
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                existing_symbols=set(contexts),
            )
        )
        return contexts

    def _pending_signal_market_contexts(
        self,
        *,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        existing_symbols: set[str] | None = None,
    ) -> dict[str, MarketContext]:
        existing_symbols = {symbol.upper() for symbol in (existing_symbols or set())}
        contexts: dict[str, MarketContext] = {}
        for pending_symbol in self._signal_block_finalizer.pending_symbols():
            symbol = pending_symbol.upper()
            if symbol in existing_symbols:
                continue
            pending_state = self._signal_block_finalizer.pending_state(symbol) or {}
            raw_direction = self._direction_hint(
                pending_state.get("raw_direction") or pending_state.get("candidate_direction")
            )
            context_verdict = dict(l12_verdict)
            if raw_direction in {"BUY", "SELL"}:
                context_verdict["verdict"] = f"EXECUTE_{raw_direction}"
                context_verdict["direction"] = raw_direction
            contexts[symbol] = self._build_market_context(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=context_verdict,
                allow_execution_entry_price=False,
            )
        return contexts

    def _hydrate_signal_throttle_candidate_market_contexts(
        self,
        *,
        report: dict[str, Any],
        market_contexts: dict[str, MarketContext],
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        if os.getenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED", "true").strip().lower() != "true":
            return {"enabled": False, "reason": "SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED_FALSE"}
        try:
            max_symbols = max(
                1,
                int(self._parse_env_float("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS", 4.0)),
            )
        except (TypeError, ValueError):
            max_symbols = 4

        existing = {str(symbol or "").upper() for symbol in market_contexts}
        candidates = self._signal_throttle_context_candidates(report)
        hydrated: list[str] = []
        skipped: list[dict[str, Any]] = []
        for candidate in candidates:
            if len(hydrated) >= max_symbols:
                break
            symbol = str(candidate.get("symbol") or "").upper()
            if not symbol:
                continue
            if symbol in existing:
                skipped.append({"symbol": symbol, "reason": "CONTEXT_ALREADY_PRESENT"})
                continue
            direction = self._direction_hint(
                candidate.get("clean_block_direction")
                or candidate.get("raw_pressure_direction")
                or candidate.get("direction")
            )
            if direction not in {"BUY", "SELL"}:
                skipped.append({"symbol": symbol, "reason": "DIRECTION_UNRESOLVED"})
                continue
            context_verdict = dict(l12_verdict)
            context_verdict["direction"] = direction
            context_verdict["verdict"] = f"EXECUTE_{direction}"
            try:
                market_contexts[symbol] = self._build_market_context(
                    symbol=symbol,
                    synthesis=synthesis,
                    l12_verdict=context_verdict,
                    allow_execution_entry_price=False,
                )
            except Exception as exc:  # pragma: no cover - defensive; observability must not break pipeline
                skipped.append({"symbol": symbol, "reason": "BUILD_MARKET_CONTEXT_FAILED", "error": str(exc)})
                continue
            existing.add(symbol)
            hydrated.append(symbol)

        return {
            "enabled": True,
            "source": "SIGNAL_THROTTLE_CLEAN_BLOCK_CANDIDATES",
            "max_symbols": max_symbols,
            "candidate_count": len(candidates),
            "hydrated_symbols": hydrated,
            "skipped": skipped[:12],
            "snapshot_rebuild_required": bool(hydrated),
            "execution_impact": False,
            "advisory_only": True,
        }

    @staticmethod
    def _signal_throttle_context_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
        def _number(value: Any) -> float:
            try:
                return float(value or 0.0)
            except (TypeError, ValueError):
                return 0.0

        tier_scores = {
            str(row.get("symbol") or "").upper(): _number(row.get("tier_score"))
            for row in report.get("pressure_tiers") or []
            if isinstance(row, dict) and str(row.get("symbol") or "").strip()
        }
        candidates: list[dict[str, Any]] = []
        raw_candidates = report.get("clean_block_watch_route_candidates") or report.get("clean_watch_candidates") or []
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("symbol") or "").upper()
            if not symbol:
                continue
            candidate = dict(raw)
            candidate["_tier_score"] = tier_scores.get(symbol, 0.0)
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                _number(item.get("_tier_score")),
                _number(
                    item.get("clean_block_duration_seconds")
                    or item.get("source_clean_block_latest_duration_seconds")
                    or item.get("duration_seconds")
                ),
                _number(item.get("effective_ticks") or item.get("clean_block_event_count") or item.get("events")),
            ),
            reverse=True,
        )
        return candidates

    def _process_signal_throttle_snapshot(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        source_verdict: Any | None,
    ) -> dict[str, Any]:
        market_contexts = self._signal_throttle_market_contexts(
            symbol=symbol,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            source_verdict=source_verdict,
        )
        report = self._signal_throttle_live_analyzer.snapshot(
            market_contexts=market_contexts,
        )
        hydration = self._hydrate_signal_throttle_candidate_market_contexts(
            report=report,
            market_contexts=market_contexts,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
        )
        if hydration.get("snapshot_rebuild_required") is True:
            report = self._signal_throttle_live_analyzer.snapshot(
                market_contexts=market_contexts,
            )
        if hydration.get("enabled") is True:
            report["candidate_market_context_hydration"] = hydration
        report["htf_structure_contexts"] = self._htf_structure_contexts_from_market_contexts(market_contexts)
        self._emit_htf_structure_snapshots_for_contexts(market_contexts)
        self._emit_signal_throttle_fusion_v3_diagnostic(report)
        self._emit_signal_throttle_pressure_tier_snapshot(report)
        self._emit_signal_throttle_followthrough_scores(report)
        self._apply_microboost_continuation_entry_report(l12_verdict=l12_verdict, report=report)
        self._apply_microboost_counter_entry_report(l12_verdict=l12_verdict, report=report)
        self._apply_microboost_watch_entry_report(l12_verdict=l12_verdict, report=report)
        self._apply_clean_block_watch_routes(l12_verdict=l12_verdict, report=report)
        self._apply_signal_block_finalizer(
            l12_verdict=l12_verdict,
            report=report,
            market_contexts=market_contexts,
        )
        self._apply_allowed_quorum_decision_update(
            symbol=symbol,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            report=report,
            market_contexts=market_contexts,
            source_verdict=source_verdict,
        )
        self._emit_microboost_intel_if_new(report)
        self._emit_signal_throttle_state_snapshot(report)
        report["family_counters"] = self.family_counters_snapshot()
        return report

    def _resolve_pressure_observation_direction(
        self,
        *,
        symbol: str | None = None,
        l12_verdict: dict[str, Any],
        synthesis: dict[str, Any] | None,
        source_verdict: Any | None,
    ) -> str | None:
        detail = self._resolve_pressure_observation_direction_detail(
            symbol=symbol,
            l12_verdict=l12_verdict,
            synthesis=synthesis,
            source_verdict=source_verdict,
        )
        direction = detail.get("direction")
        return direction if direction in {"BUY", "SELL"} else None

    def _resolve_pressure_observation_direction_detail(
        self,
        *,
        symbol: str | None = None,
        l12_verdict: dict[str, Any],
        synthesis: dict[str, Any] | None,
        source_verdict: Any | None,
    ) -> dict[str, Any]:
        """Restore the raw pressure direction for a non-execute pressure/canary
        observation from current-tick upstream sources.

        Classification-only: the result seeds ``raw_direction`` on the recorded
        canary so the microboost counter/continuation engines can classify
        (e.g. BUY stalled at resistance -> SELL absorption watch). It MUST NOT set
        ``final_direction`` / ``valid_for_execution`` or emit a ``SignalJSON``.

        Use-if-present and conflict-safe: returns ``None`` when no source carries a
        BUY/SELL direction, or when sources disagree (never guesses). Kill switch:
        ``SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY=false``.
        """
        if os.getenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY", "true").strip().lower() != "true":
            return {}
        from schemas.direction import normalize_direction  # noqa: PLC0415

        intel = l12_verdict.get("signal_throttle_intel")
        execution = synthesis.get("execution") if isinstance(synthesis, dict) else None
        verdict_text = str(source_verdict or "").strip().upper() or None
        raw_sources = (
            l12_verdict.get("direction"),
            l12_verdict.get("raw_direction"),
            intel.get("raw_direction") if isinstance(intel, dict) else None,
            execution.get("direction") if isinstance(execution, dict) else None,
        )
        found: set[str] = set()
        for raw in raw_sources:
            resolved = normalize_direction(str(raw) if raw else None)
            if resolved in {"BUY", "SELL"}:
                found.add(resolved)
        verdict_direction = normalize_direction(None, verdict_text) if verdict_text else None
        if verdict_direction in {"BUY", "SELL"}:
            found.add(verdict_direction)
        if len(found) == 1:
            return {
                "direction": next(iter(found)),
                "direction_source": "CURRENT_TICK_PRESSURE_SOURCE",
                "direction_confidence": "HIGH",
            }
        # P2D' (flag-guarded, default OFF): when the primary sources carry no usable
        # direction -- the common non-execute case where execution.direction has been
        # collapsed to HOLD -- recover the raw pressure direction from the per-layer
        # biases that survive in execution.direction_diagnostics.sources. Only fires
        # when `found` is empty (a genuine primary-source conflict, len > 1, stays None).
        if not found:
            recovered = self._recover_direction_from_diagnostics(execution)
            if recovered in {"BUY", "SELL"}:
                return {
                    "direction": recovered,
                    "direction_source": "DIRECTION_DIAGNOSTICS",
                    "direction_confidence": "MEDIUM",
                }
            if self._diagnostics_direction_conflict(execution):
                return {}
            bridged = self._recover_direction_from_intel_bridge_detail(
                symbol=symbol,
                l12_verdict=l12_verdict,
            )
            if bridged.get("direction") in {"BUY", "SELL"}:
                return bridged
        return {}

    @staticmethod
    def _recover_direction_from_diagnostics(execution: Any | None) -> str | None:
        """P2D' (flag-guarded, default OFF): recover the raw pressure direction from the
        per-layer biases that survive in ``execution.direction_diagnostics.sources``
        after ``resolve_trade_direction`` collapses ``execution.direction`` to HOLD
        (reason ``no_l3_direction`` or ``direction_conflict``).

        Restoration-only and conflict-safe: returns a BUY/SELL only when every layer
        that expresses a direction agrees. Any disagreement -- or a pre-recorded
        ``conflicts`` entry from the resolver -- returns ``None`` so the system never
        guesses. Priority l3 -> l2 -> l1 -> l9 is used for deterministic iteration; the
        agreement check is authoritative. The result only seeds ``raw_direction`` so the
        microboost counter/continuation engines can classify (e.g. BUY stalled at
        resistance -> SELL absorption watch). It NEVER sets ``final_direction`` /
        ``valid_for_execution`` and never emits a ``SignalJSON``.

        Enable with ``SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS=true``.
        """
        if os.getenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "false").strip().lower() != "true":
            return None
        if not isinstance(execution, dict):
            return None
        diagnostics = execution.get("direction_diagnostics")
        if not isinstance(diagnostics, dict):
            return None
        conflicts = diagnostics.get("conflicts")
        if isinstance(conflicts, list) and conflicts:
            return None
        sources = diagnostics.get("sources")
        if not isinstance(sources, dict):
            return None
        from schemas.direction import normalize_direction  # noqa: PLC0415

        found: set[str] = set()
        for key in ("l3", "l2", "l1", "l9"):
            raw = sources.get(key)
            resolved = normalize_direction(str(raw) if raw else None)
            if resolved in {"BUY", "SELL"}:
                found.add(resolved)
        if len(found) == 1:
            return next(iter(found))
        return None

    @staticmethod
    def _diagnostics_direction_conflict(execution: Any | None) -> bool:
        """Return true when current-tick diagnostics explicitly disagree.

        The Intel bridge is cross-tick state. It must not seed a pressure canary
        when same-tick diagnostic sources say BUY and SELL are both present, or
        when the resolver already recorded a conflict.
        """
        if not isinstance(execution, dict):
            return False
        diagnostics = execution.get("direction_diagnostics")
        if not isinstance(diagnostics, dict):
            return False
        conflicts = diagnostics.get("conflicts")
        if isinstance(conflicts, list) and conflicts:
            return True
        sources = diagnostics.get("sources")
        if not isinstance(sources, dict):
            return False
        found: set[str] = set()
        for raw in sources.values():
            direction = WolfConstitutionalPipeline._direction_hint(raw)
            if direction in {"BUY", "SELL"}:
                found.add(direction)
        return len(found) > 1

    @staticmethod
    def _payload_field(payload: Any, key: str) -> Any:
        if isinstance(payload, dict):
            return payload.get(key)
        return getattr(payload, key, None)

    def _cache_signal_throttle_intel_direction(self, symbol: str, throttle_intel: Any) -> None:
        """Cache latest safe Intel raw_direction per symbol for non-execute lanes.

        Cache population is harmless while the bridge flag is OFF. Directions
        from an Intel record that already detected a direction mismatch are not
        cached, so stale clean Intel cannot override a fresh local conflict.
        """
        normalized_symbol = str(symbol or self._payload_field(throttle_intel, "symbol") or "").strip().upper()
        if not normalized_symbol:
            return

        raw_direction = self._payload_field(throttle_intel, "raw_direction")
        direction = self._direction_hint(raw_direction)
        if direction not in {"BUY", "SELL"}:
            return

        final_direction = str(self._payload_field(throttle_intel, "final_direction") or "").strip().upper()
        direction_status = str(self._payload_field(throttle_intel, "direction_status") or "").strip().upper()
        if final_direction == "BLOCK_DIRECTION" or direction_status == "DIRECTION_MISMATCH":
            cache = getattr(self, "_signal_throttle_intel_direction_cache", None)
            if isinstance(cache, dict):
                cache.pop(normalized_symbol, None)
            return

        cache = getattr(self, "_signal_throttle_intel_direction_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._signal_throttle_intel_direction_cache = cache
        cache[normalized_symbol] = (direction, datetime.now(UTC))

    def _recover_direction_from_intel_bridge(
        self,
        *,
        symbol: str | None,
        l12_verdict: dict[str, Any],
    ) -> str | None:
        detail = self._recover_direction_from_intel_bridge_detail(
            symbol=symbol,
            l12_verdict=l12_verdict,
        )
        direction = detail.get("direction")
        return direction if direction in {"BUY", "SELL"} else None

    def _recover_direction_from_intel_bridge_detail(
        self,
        *,
        symbol: str | None,
        l12_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        """Root#1/case-c bridge: carry latest allowed Intel direction to canary.

        Flag-guarded, same-symbol, bounded by a short TTL. The returned value
        only seeds ``record_pressure_canary(direction=...)``; it is never a final
        execution direction and never emits SignalJSON.
        """
        if os.getenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "false").strip().lower() != "true":
            return {}
        normalized_symbol = str(symbol or l12_verdict.get("symbol") or "").strip().upper()
        if not normalized_symbol:
            return {}
        cache = getattr(self, "_signal_throttle_intel_direction_cache", None)
        if not isinstance(cache, dict):
            return {}
        cached = cache.get(normalized_symbol)
        if not isinstance(cached, tuple) or len(cached) != 2:
            cache.pop(normalized_symbol, None)
            return {}
        direction, seen_at = cached
        if direction not in {"BUY", "SELL"} or not isinstance(seen_at, datetime):
            cache.pop(normalized_symbol, None)
            return {}
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=UTC)
        try:
            window_seconds = float(os.getenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", "600"))
        except (TypeError, ValueError):
            window_seconds = 600.0
        window_seconds = max(1.0, window_seconds)
        age_seconds = (datetime.now(UTC) - seen_at).total_seconds()
        if age_seconds > window_seconds:
            cache.pop(normalized_symbol, None)
            return {}
        confidence = "HIGH" if age_seconds <= min(60.0, window_seconds / 2.0) else "MEDIUM"
        return {
            "direction": direction,
            "direction_source": "SIGNAL_THROTTLE_INTEL_CACHE",
            "direction_confidence": confidence,
            "direction_inherited": True,
            "inherited_direction": direction,
            "inherited_direction_age_seconds": round(max(0.0, age_seconds), 3),
        }

    def _record_signal_throttle_downgrade_observation(
        self,
        *,
        symbol: str,
        l12_verdict: dict[str, Any],
        legacy_verdict: Any,
        reason: str,
        synthesis: dict[str, Any] | None = None,
    ) -> None:
        source_verdict = (
            l12_verdict.get("market_context_from")
            or l12_verdict.get("sovereignty_from")
            or l12_verdict.get("throttled_from")
            or legacy_verdict
            or l12_verdict.get("verdict")
        )
        source_text = str(source_verdict or "").strip().upper()
        # C2 (restore direction propagation): a non-execute observation must still
        # carry the raw pressure direction so it does not starve the microboost
        # counter engine (which would fall back to raw_direction_missing). This is
        # classification-only -- it never changes final_direction /
        # valid_for_execution and never emits a SignalJSON.
        direction_detail: dict[str, Any] = {}
        direction = self._direction_hint(l12_verdict.get("direction")) or self._direction_hint(source_text)
        if direction not in {"BUY", "SELL"}:
            direction_detail = self._resolve_pressure_observation_direction_detail(
                symbol=symbol,
                l12_verdict=l12_verdict,
                synthesis=synthesis,
                source_verdict=source_verdict,
            )
            direction = direction_detail.get("direction")
        if direction not in {"BUY", "SELL"}:
            if reason == "non_execute_verdict":
                self._signal_throttle_live_analyzer.record_pressure_canary(
                    symbol=symbol,
                    verdict=l12_verdict.get("verdict"),
                    direction=None,
                    reason=reason,
                )
            return
        direction_metadata = {
            key: value
            for key, value in direction_detail.items()
            if key
            in {
                "direction_source",
                "direction_confidence",
                "direction_inherited",
                "inherited_direction",
                "inherited_direction_age_seconds",
            }
        }
        if reason == "non_execute_verdict" and not source_text.startswith("EXECUTE"):
            self._signal_throttle_live_analyzer.record_pressure_canary(
                symbol=symbol,
                verdict=l12_verdict.get("verdict"),
                direction=direction,
                reason=reason,
                **direction_metadata,
            )
            return
        if not source_text.startswith("EXECUTE"):
            source_text = f"EXECUTE_{direction}"
        self._signal_throttle_live_analyzer.record_downgraded(
            symbol=symbol,
            verdict=source_text,
            direction=direction,
            reason=reason,
        )

    @staticmethod
    def _should_track_lifecycle_candidate(payload: dict[str, Any]) -> bool:
        """Decide whether an emitted watch/continuation is an OFFICIAL lifecycle
        candidate that must earn a terminal outcome via the SignalBlockFinalizer.

        Only official, actionable candidates are tracked. Shadow/observability and
        telemetry/debug pings are deliberately excluded so they never create a
        hanging pending watch (no DecisionUpdate, no SignalJSON, no expiry).
        """
        if not isinstance(payload, dict):
            return False
        status = str(payload.get("status") or "")
        signal_id = payload.get("signal_id") or payload.get("pending_decision_id")
        shadow_only = payload.get("shadow_only") is True
        telemetry_only = payload.get("signal_quality") in {"TELEMETRY_ONLY", "DEBUG_ONLY"}
        validation_only = payload.get("orchestration_status") == "VALIDATION_ONLY_REQUIRES_SIGNAL_WATCH"
        direction = str(
            payload.get("watch_direction")
            or payload.get("candidate_direction")
            or payload.get("validated_direction")
            or ""
        ).upper()
        source_clean_block_confirmed = payload.get("source_clean_block_confirmed")
        source_clean_block_ok = source_clean_block_confirmed is not False
        return (
            bool(payload.get("symbol"))
            and bool(signal_id)
            and not shadow_only
            and not telemetry_only
            and not validation_only
            and direction in {"BUY", "SELL"}
            and source_clean_block_ok
            and (
                status.endswith("_WATCH")
                or status.endswith("_VALID")
                or status.endswith("_BY_DIRECT_ABSORPTION")
            )
        )

    @staticmethod
    def _should_track_official_watch(payload: dict[str, Any]) -> bool:
        """Increment D (flag-guarded, default OFF): admit an OFFICIAL *resolved counter*
        watch (EARLY_SELL_WATCH / EARLY_BUY_WATCH produced by the Increment C
        pattern-aware headline resolver) into finalizer lifecycle tracking even when it
        lacks a clean SignalThrottle block.

        Why this exists: ``_should_track_lifecycle_candidate`` requires
        ``source_clean_block_ok``, but resolved counter watches come from short
        absorption bursts that never form a 5-minute clean block -- so without this
        path they emit as SignalWatchJSON and then hang with no terminal
        SignalDecisionUpdateJSON. This is a pure ADMISSION predicate: it never sets or
        changes ``valid_for_execution`` / ``final_direction`` and never emits a
        SignalJSON; the finalizer still owns the terminal decision on idle/TTL/M15.

        Enable with ``SIGNAL_WATCH_FINALIZER_TRACK_EARLY_ENABLED=true``.
        """
        if os.getenv("SIGNAL_WATCH_FINALIZER_TRACK_EARLY_ENABLED", "false").strip().lower() != "true":
            return False
        if not isinstance(payload, dict):
            return False
        status = str(payload.get("status") or "").upper()
        if status not in {"EARLY_SELL_WATCH", "EARLY_BUY_WATCH"}:
            return False
        if not str(payload.get("symbol") or "").strip():
            return False
        # official watch must carry a lifecycle identity (set by _mark_official_lifecycle_candidate)
        if not (payload.get("signal_id") or payload.get("pending_decision_id")):
            return False
        # never executable, never a final signal -- this is a watch, not an entry
        if payload.get("is_final_signal") is True or payload.get("valid_for_execution") is True:
            return False
        if str(payload.get("final_direction") or "WAIT").upper() != "WAIT":
            return False
        # exclude shadow / telemetry / validation-only pings
        if payload.get("shadow_only") is True or payload.get("signal_quality") in {"TELEMETRY_ONLY", "DEBUG_ONLY"}:
            return False
        if payload.get("orchestration_status") == "VALIDATION_ONLY_REQUIRES_SIGNAL_WATCH":
            return False
        # must lean a concrete scenario direction (resolved counter side)
        direction = str(
            payload.get("watch_direction")
            or payload.get("candidate_direction")
            or payload.get("validated_direction")
            or ""
        ).upper()
        if direction not in {"BUY", "SELL"}:
            return False
        # must be a RESOLVED official counter watch, never a raw generic MICROBOOST_WATCH
        resolved_family = str(payload.get("resolved_family") or payload.get("signal_family") or "").upper()
        return resolved_family == "MICROBOOST_COUNTER_ENTRY"

    def _mark_official_lifecycle_candidate(self, payload: dict[str, Any]) -> None:
        """Attach a stable lifecycle identity so the finalizer can adopt an official
        watch candidate (``_is_pending_watch`` clause: pending_decision_id +
        requires_m15_close). Final execution payloads keep their own terminal path
        and are not flagged as ``requires_m15_close``.
        """
        symbol = str(payload.get("symbol") or "").upper()
        if symbol:
            cluster_id = str(payload.get("cluster_id") or "").strip()
            token = str(
                payload.get("pending_decision_id")
                or cluster_id
                or payload.get("signal_valid_time_utc")
                or "WATCH"
            )
            payload["pending_decision_id"] = _normalized_watch_pending_decision_id(
                symbol,
                token,
                cluster_id=cluster_id,
            )
        if payload.get("valid_for_execution") is not True:
            payload.setdefault("requires_m15_close", True)

    def _prepare_lifecycle_tracking_metadata(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status") or "")
        is_lifecycle_status = (
            status.endswith("_WATCH") or status.endswith("_VALID") or status.endswith("_BY_DIRECT_ABSORPTION")
        )
        excluded = (
            payload.get("shadow_only") is True
            or payload.get("signal_quality") in {"TELEMETRY_ONLY", "DEBUG_ONLY"}
            or payload.get("orchestration_status") == "VALIDATION_ONLY_REQUIRES_SIGNAL_WATCH"
        )
        if is_lifecycle_status and payload.get("symbol") and not excluded:
            self._mark_official_lifecycle_candidate(payload)
        lifecycle_track = self._should_track_lifecycle_candidate(payload) or self._should_track_official_watch(payload)
        payload["lifecycle_track"] = lifecycle_track
        if lifecycle_track:
            payload.setdefault("lifecycle_status", "WATCH_ACTIVE")
            payload.setdefault("terminal_required", True)
            payload.setdefault("terminal_guarantee", "SIGNAL_BLOCK_FINALIZER")
        else:
            payload.setdefault("terminal_required", False)
            payload.setdefault("terminal_guarantee", "OBSERVABILITY_ONLY")

    def _track_official_lifecycle_candidate(self, payload: dict[str, Any]) -> None:
        """Register an official watch/continuation candidate with the finalizer so it
        is guaranteed a terminal outcome. Gated by
        ``SIGNAL_LIFECYCLE_TRACK_OFFICIAL_WATCH_ENABLED`` (default on) for rollback.
        """
        if os.getenv("SIGNAL_LIFECYCLE_TRACK_OFFICIAL_WATCH_ENABLED", "true").strip().lower() != "true":
            return
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status") or "")
        is_lifecycle_status = (
            status.endswith("_WATCH") or status.endswith("_VALID") or status.endswith("_BY_DIRECT_ABSORPTION")
        )
        if not is_lifecycle_status or not payload.get("symbol"):
            return
        if payload.get("shadow_only") is True or payload.get("signal_quality") in {"TELEMETRY_ONLY", "DEBUG_ONLY"}:
            return
        finalizer = getattr(self, "_signal_block_finalizer", None)
        if finalizer is None:
            return
        if payload.get("lifecycle_track") is not True:
            self._prepare_lifecycle_tracking_metadata(payload)
        if payload.get("lifecycle_track") is True:
            finalizer.track(payload)

    def _apply_microboost_continuation_entry_report(
        self,
        *,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        continuation = report.get("microboost_continuation_entry")
        if not isinstance(continuation, dict):
            return
        if continuation.get("status") == "NONE":
            return

        continuation = dict(continuation)
        continuation["orchestration_status"] = "VALIDATION_ONLY_REQUIRES_SIGNAL_WATCH"
        if self._signal_json_gate_adapter.emit_continuation:
            continuation = self._signal_lifecycle_manager.apply(continuation)
        continuation["signal_json_emit_result"] = False
        report["microboost_continuation_entry"] = continuation
        l12_verdict["microboost_continuation_entry"] = continuation
        if self._signal_json_gate_adapter.emit_continuation:
            self._attach_pressure_priority_context(continuation, report)
            self._attach_htf_structure_context(continuation, report)
            self._attach_followthrough_context(continuation, report)
            self._prepare_lifecycle_tracking_metadata(continuation)
            continuation["signal_json_emit_result"] = self._emit_signal_json_payload(continuation)
            if continuation["signal_json_emit_result"]:
                self._track_official_lifecycle_candidate(continuation)

    def _apply_microboost_watch_entry_report(
        self,
        *,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        watch_entry = report.get("microboost_watch_entry")
        if not isinstance(watch_entry, dict):
            return
        if watch_entry.get("status") == "NONE":
            return

        watch_entry = dict(watch_entry)
        self._attach_pressure_priority_context(watch_entry, report)
        self._attach_htf_structure_context(watch_entry, report)
        self._attach_followthrough_context(watch_entry, report)
        self._prepare_lifecycle_tracking_metadata(watch_entry)
        report["microboost_watch_entry"] = watch_entry
        l12_verdict["microboost_watch_entry"] = watch_entry
        watch_entry["signal_json_emit_result"] = self._emit_signal_json_payload(watch_entry)
        if watch_entry["signal_json_emit_result"]:
            self._track_official_lifecycle_candidate(watch_entry)

    def _apply_clean_block_watch_routes(
        self,
        *,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        watch_entries = report.get("clean_block_watch_entries")
        processed: list[dict[str, Any]] = []
        covered_clean_blocks = self._covered_clean_block_watch_ids(report)
        if isinstance(watch_entries, list):
            for raw_entry in watch_entries:
                if not isinstance(raw_entry, dict):
                    continue
                watch_entry = dict(raw_entry)
                source_id = str(watch_entry.get("source_clean_block_id") or "").strip()
                if source_id and source_id in covered_clean_blocks:
                    watch_entry["signal_json_emit_result"] = False
                    watch_entry["clean_block_watch_route_skipped"] = True
                    watch_entry["skip_reason"] = "CLEAN_BLOCK_ALREADY_COVERED_BY_EXISTING_SIGNAL_WATCH"
                    processed.append(watch_entry)
                    continue

                self._prepare_lifecycle_tracking_metadata(watch_entry)
                self._attach_pressure_priority_context(watch_entry, report)
                self._attach_htf_structure_context(watch_entry, report)
                self._attach_followthrough_context(watch_entry, report)
                watch_entry["signal_json_emit_result"] = self._emit_signal_json_payload(watch_entry)
                if watch_entry["signal_json_emit_result"]:
                    self._track_official_lifecycle_candidate(watch_entry)
                    if source_id:
                        covered_clean_blocks.add(source_id)
                processed.append(watch_entry)

        if processed:
            report["clean_block_watch_entries"] = processed
            l12_verdict["clean_block_watch_entries"] = processed

        self._emit_signal_watch_promotion_diagnostics(report)
        diagnostics = report.get("signal_watch_promotion_diagnostics")
        if isinstance(diagnostics, list) and diagnostics:
            l12_verdict["signal_watch_promotion_diagnostics"] = diagnostics

    @staticmethod
    def _covered_clean_block_watch_ids(report: dict[str, Any]) -> set[str]:
        covered: set[str] = set()
        for key in ("microboost_watch_entry", "microboost_counter_entry", "microboost_continuation_entry"):
            candidate = report.get(key)
            if not isinstance(candidate, dict):
                continue
            status = str(candidate.get("status") or "")
            if not status.endswith("_WATCH"):
                continue
            if candidate.get("signal_json_emit_result") is not True:
                continue
            source_id = str(candidate.get("source_clean_block_id") or "").strip()
            if source_id:
                covered.add(source_id)
        return covered

    def _emit_signal_watch_promotion_diagnostics(self, report: dict[str, Any]) -> None:
        diagnostics = report.get("signal_watch_promotion_diagnostics")
        if not isinstance(diagnostics, list):
            return
        enabled = os.getenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true").strip().lower() == "true"
        prefix = os.getenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_LOG_PREFIX", "[SignalWatchPromotionDiagnostic]")
        store = getattr(self, "_last_signal_watch_promotion_diag_key", None)
        if not isinstance(store, dict):
            store = {}
            self._last_signal_watch_promotion_diag_key = store

        processed: list[dict[str, Any]] = []
        for raw_diag in diagnostics:
            if not isinstance(raw_diag, dict):
                continue
            diag = dict(raw_diag)
            diag = self._attach_signal_watch_source_lookup_context(diag, report)
            blocked_by_values = {str(item) for item in diag.get("blocked_by") or []}
            if "SOURCE_CLEAN_BLOCK_ID_MISSING" in blocked_by_values:
                diag, should_emit = self._prepare_signal_watch_lineage_missing_diagnostic(diag, diag)
                if not should_emit:
                    diag["diagnostic_emit_result"] = False
                    processed.append(diag)
                    continue
                diag["diagnostic_emit_result"] = emit_signal_watch_promotion_diagnostic(
                    diag,
                    enabled=enabled,
                    prefix=prefix,
                )
                processed.append(diag)
                continue
            source_id = str(diag.get("source_clean_block_id") or diag.get("symbol") or "").strip()
            blocked_by = "/".join(str(item) for item in diag.get("blocked_by") or [])
            key = f"{source_id}|{blocked_by}|{diag.get('next_required_stage') or ''}"
            if source_id and store.get(source_id) == key:
                diag["diagnostic_emit_result"] = False
                diag["diagnostic_deduped"] = True
                processed.append(diag)
                continue
            if source_id:
                store[source_id] = key
            diag["diagnostic_emit_result"] = emit_signal_watch_promotion_diagnostic(
                diag,
                enabled=enabled,
                prefix=prefix,
            )
            processed.append(diag)

        if processed:
            report["signal_watch_promotion_diagnostics"] = processed

    def _attach_signal_watch_source_lookup_context(
        self,
        diagnostic: dict[str, Any],
        report: dict[str, Any],
    ) -> dict[str, Any]:
        diag = dict(diagnostic)
        blocked_by = {str(item) for item in diag.get("blocked_by") or []}
        if "SOURCE_CLEAN_BLOCK_ID_MISSING" not in blocked_by:
            return diag
        symbol = str(diag.get("symbol") or "").upper()
        cluster_id = str(diag.get("cluster_id") or "").strip()
        diag.setdefault("source_lookup_stage", "SIGNAL_THROTTLE_V1_CLEAN_BLOCK_LEDGER")
        diag.setdefault("source_lookup_key", cluster_id or symbol or None)
        diag.setdefault("raw_cluster_id", cluster_id or None)
        nearest = self._nearest_clean_block_candidate(report, symbol)
        diag.setdefault("nearest_clean_block_candidate", nearest)
        if nearest is None:
            diag.setdefault("why_not_attached", "NO_V1_CLEAN_BLOCK_CANDIDATE_FOR_SYMBOL")
        else:
            diag.setdefault("why_not_attached", "WATCH_CANDIDATE_MISSING_SOURCE_CLEAN_BLOCK_ID")
        return diag

    @staticmethod
    def _nearest_clean_block_candidate(report: dict[str, Any], symbol: str) -> dict[str, Any] | None:
        if not symbol:
            return None
        candidates: list[dict[str, Any]] = []
        for key in ("v1_clean_block_ledger", "clean_watch_candidates"):
            raw_candidates = report.get(key)
            if not isinstance(raw_candidates, list):
                continue
            for raw_candidate in raw_candidates:
                if not isinstance(raw_candidate, dict):
                    continue
                if str(raw_candidate.get("symbol") or "").upper() != symbol:
                    continue
                candidates.append(raw_candidate)
            if candidates:
                break
        if not candidates:
            return None

        def _end_key(candidate: dict[str, Any]) -> str:
            return str(candidate.get("clean_block_end_utc") or candidate.get("block_end_utc") or "")

        candidate = max(candidates, key=_end_key)
        return {
            "symbol": str(candidate.get("symbol") or "").upper(),
            "source_clean_block_id": candidate.get("source_clean_block_id"),
            "clean_block_valid": candidate.get("clean_block_valid"),
            "clean_block_end_utc": candidate.get("clean_block_end_utc") or candidate.get("block_end_utc"),
            "clean_block_duration_seconds": candidate.get("clean_block_duration_seconds")
            or candidate.get("duration_seconds"),
            "raw_pressure_direction": candidate.get("raw_pressure_direction")
            or candidate.get("clean_block_direction")
            or candidate.get("direction"),
        }

    def _prepare_signal_watch_lineage_missing_diagnostic(
        self,
        diagnostic: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        diag = dict(diagnostic)
        blocked_by = {str(item) for item in diag.get("blocked_by") or []}
        if "SOURCE_CLEAN_BLOCK_ID_MISSING" not in blocked_by:
            return diag, True
        replay_store = getattr(self, "_signal_watch_lineage_missing_replay_count", None)
        if not isinstance(replay_store, dict):
            replay_store = {}
            self._signal_watch_lineage_missing_replay_count = replay_store
        replay_key = "|".join(
            str(part or "")
            for part in (
                diag.get("cluster_id") or payload.get("cluster_id"),
                diag.get("symbol") or payload.get("symbol"),
                diag.get("status") or payload.get("status"),
                diag.get("signal_family") or payload.get("signal_family"),
            )
        )
        replay_count = int(replay_store.get(replay_key, 0)) + 1
        replay_store[replay_key] = replay_count
        terminal_threshold = int(
            max(1.0, self._parse_env_float("SIGNAL_WATCH_LINEAGE_MISSING_TERMINAL_THRESHOLD", 3.0))
        )
        diag["lineage_missing_replay_count"] = replay_count
        diag["lineage_missing_terminal_threshold"] = terminal_threshold
        if replay_count > terminal_threshold:
            payload["signal_json_emit_blocked_by_source_guard_terminal"] = True
            diag["signal_json_emit_blocked_by_source_guard_terminal"] = True
            diag["status"] = "LINEAGE_MISSING_TERMINAL"
            diag["reason"] = "source_clean_block_id_missing_replayed_until_terminal"
            diag["next_required_stage"] = "ATTACH_CLEAN_BLOCK_LINEAGE_TERMINAL"
            if replay_count > terminal_threshold + 1:
                payload["signal_watch_source_diagnostic_terminal_suppressed"] = True
                diag["signal_watch_source_diagnostic_terminal_suppressed"] = True
                return diag, False
        return diag, True

    def _emit_signal_watch_source_guard_diagnostic(
        self,
        diagnostic: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        diag, should_emit = self._prepare_signal_watch_lineage_missing_diagnostic(diagnostic, payload)
        if not should_emit:
            return False
        return emit_signal_watch_promotion_diagnostic(
            diag,
            enabled=os.getenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true").strip().lower() == "true",
            prefix=os.getenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_LOG_PREFIX", "[SignalWatchPromotionDiagnostic]"),
        )

    def _attach_pressure_priority_context(self, payload: dict[str, Any], report: dict[str, Any]) -> None:
        if os.getenv("SIGNAL_WATCH_PRESSURE_PRIORITY_CONTEXT_ENABLED", "true").strip().lower() != "true":
            return
        status = str(payload.get("status") or "")
        if not status.endswith("_WATCH"):
            return
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol or isinstance(payload.get("pressure_priority_context"), dict):
            return
        context = pressure_priority_context_for_symbol(
            report.get("pressure_tier_snapshot") if isinstance(report, dict) else None,
            symbol,
            watch_payload=payload,
        )
        if context is not None:
            payload["pressure_priority_context"] = context

    def _attach_htf_structure_context(
        self,
        payload: dict[str, Any],
        report: dict[str, Any],
        *,
        market_contexts: dict[str, Any] | None = None,
    ) -> None:
        if os.getenv("HTF_STRUCTURE_CONTEXT_ENABLED", "true").strip().lower() != "true":
            return
        if isinstance(payload.get("htf_structure_context"), dict):
            return
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol:
            return
        context = self._htf_context_from_report(report, symbol)
        if context is None and isinstance(market_contexts, dict):
            raw_context = (
                market_contexts.get(symbol)
                or market_contexts.get(symbol.lower())
                or market_contexts.get(str(payload.get("symbol") or ""))
            )
            context = self._htf_structure_context_from_market_context(raw_context)
        if context is None:
            context = self._resolve_htf_structure_context(symbol)
        if context is not None:
            payload["htf_structure_context"] = context

    @staticmethod
    def _htf_context_from_report(report: dict[str, Any], symbol: str) -> dict[str, Any] | None:
        contexts = report.get("htf_structure_contexts") if isinstance(report, dict) else None
        if not isinstance(contexts, dict):
            return None
        raw = contexts.get(symbol.upper()) or contexts.get(symbol.lower()) or contexts.get(symbol)
        return dict(raw) if isinstance(raw, dict) else None

    def _htf_structure_contexts_from_market_contexts(self, market_contexts: dict[str, Any]) -> dict[str, dict[str, Any]]:
        contexts: dict[str, dict[str, Any]] = {}
        if os.getenv("HTF_STRUCTURE_CONTEXT_ENABLED", "true").strip().lower() != "true":
            return contexts
        for symbol, context in market_contexts.items():
            symbol_key = str(symbol or getattr(context, "symbol", "") or "").upper()
            if not symbol_key:
                continue
            htf_context = self._htf_structure_context_from_market_context(context)
            if htf_context is not None:
                contexts[symbol_key] = htf_context
        return contexts

    def _emit_htf_structure_snapshots_for_contexts(self, market_contexts: dict[str, Any]) -> None:
        if os.getenv("HTF_STRUCTURE_SNAPSHOT_ENABLED", "true").strip().lower() != "true":
            return
        for symbol in sorted({str(key or "").upper() for key in market_contexts if str(key or "").strip()}):
            self._emit_htf_structure_snapshot(symbol)

    def _attach_followthrough_context(self, payload: dict[str, Any], report: dict[str, Any]) -> None:
        if os.getenv("SIGNAL_WATCH_FOLLOWTHROUGH_CONTEXT_ENABLED", "true").strip().lower() != "true":
            return
        status = str(payload.get("status") or "")
        if not status.endswith("_WATCH"):
            return
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol or isinstance(payload.get("followthrough_context"), dict):
            return
        context = followthrough_context_for_symbol(
            report.get("followthrough_scores") if isinstance(report, dict) else None,
            symbol,
        )
        if context is not None:
            payload["followthrough_context"] = context

    def _apply_microboost_counter_entry_report(
        self,
        *,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        counter_entry = report.get("microboost_counter_entry")
        if not isinstance(counter_entry, dict):
            return
        if counter_entry.get("status") == "NONE":
            return

        counter_entry = self._signal_lifecycle_manager.apply(counter_entry)
        self._attach_pressure_priority_context(counter_entry, report)
        self._attach_htf_structure_context(counter_entry, report)
        self._attach_followthrough_context(counter_entry, report)
        report["microboost_counter_entry"] = counter_entry
        l12_verdict["microboost_counter_entry"] = counter_entry
        self._signal_block_finalizer.track(counter_entry)
        status = str(counter_entry.get("status") or "")
        if status.endswith("_VALID") or status.endswith("_BY_DIRECT_ABSORPTION"):
            l12_verdict["final_direction"] = counter_entry.get("final_direction")
            l12_verdict["action"] = counter_entry.get("action")
            l12_verdict["direction_source"] = "MICROBOOST_COUNTER_ENTRY"
        elif status.endswith("_ABSORPTION_WATCH"):
            l12_verdict["final_direction"] = "WAIT"
            l12_verdict["action"] = counter_entry.get("action")
            l12_verdict["direction_source"] = "MICROBOOST_COUNTER_ENTRY_ABSORPTION_WATCH"
        elif status.endswith("_BY_ABSORPTION"):
            l12_verdict["final_direction"] = "WAIT"
            l12_verdict["action"] = counter_entry.get("action")
            l12_verdict["direction_source"] = "MICROBOOST_COUNTER_ENTRY_TIMING_VALID_CONDITIONAL"
        elif status.endswith("_WATCH"):
            l12_verdict["final_direction"] = "WAIT"
            l12_verdict["action"] = counter_entry.get("action")
            l12_verdict["direction_source"] = "MICROBOOST_COUNTER_ENTRY_WATCH"

        counter_entry["signal_json_emit_result"] = self._emit_signal_json_payload(counter_entry)

    def _apply_signal_block_finalizer(
        self,
        *,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        market_contexts: dict[str, Any],
    ) -> None:
        updates = self._signal_block_finalizer.finalize(
            report=report,
            market_contexts=market_contexts,
        )
        if not updates:
            return

        applied_updates: list[dict[str, Any]] = []
        for update in updates:
            if update.get("event") != "signal_decision_update_json":
                update = self._signal_lifecycle_manager.apply(update)
            self._attach_htf_structure_context(update, report, market_contexts=market_contexts)
            self._signal_block_finalizer.track(update)
            applied_updates.append(update)
            status = str(update.get("status") or "")
            if status.endswith("_VALID") or status.endswith("_BY_DIRECT_ABSORPTION"):
                l12_verdict["final_direction"] = update.get("final_direction")
                l12_verdict["action"] = update.get("action")
                l12_verdict["direction_source"] = "SIGNAL_BLOCK_FINALIZER"
            else:
                l12_verdict["final_direction"] = "WAIT"
                l12_verdict["action"] = update.get("action")
                l12_verdict["direction_source"] = "SIGNAL_BLOCK_FINALIZER_DECISION_UPDATE"

            update["signal_json_emit_result"] = self._emit_signal_json_payload(update)

        report["signal_block_finalizer_updates"] = applied_updates
        l12_verdict["signal_block_finalizer_updates"] = applied_updates

    def _apply_allowed_quorum_decision_update(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        market_contexts: dict[str, MarketContext],
        source_verdict: Any | None,
    ) -> None:
        if os.getenv("SIGNAL_THROTTLE_ALLOWED_QUORUM_DECISION_UPDATE_ENABLED", "true").strip().lower() != "true":
            return
        source_text = str(source_verdict or l12_verdict.get("verdict") or "").strip().upper()
        allowed_quorum_raw = report.get("allowed_quorum")
        allowed_quorum = allowed_quorum_raw if isinstance(allowed_quorum_raw, dict) else {}
        if not bool(allowed_quorum.get("quorum_reached")):
            return
        if self._has_signal_throttle_watch_or_decision_candidate(report):
            return
        symbol_key = str(allowed_quorum.get("symbol") or symbol or "").upper()
        if not symbol_key:
            return
        if not self._should_emit_allowed_quorum_decision(symbol=symbol_key):
            return
        payload = self._allowed_quorum_decision_update_payload(
            symbol=symbol_key,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            report=report,
            market_contexts=market_contexts,
            source_verdict=source_text,
        )
        if payload is None:
            # Context/price is missing, so this cannot become a priced decision update.
            # Emit a PressureState terminal directly; it is observability-only and never
            # passes through the final SignalJSON builder.
            pressure_payload = self._allowed_quorum_contextless_pressure_payload(
                symbol=symbol_key,
                allowed_quorum=allowed_quorum,
                l12_verdict=l12_verdict,
                report=report,
                source_verdict=source_text,
            )
            self._store_signal_pressure_state(
                pressure_payload,
                report=report,
                l12_verdict=l12_verdict,
                state_key="allowed_quorum_pressure_state",
            )
            return
        if self._route_pressure_decision_or_emit(
            payload,
            report=report,
            l12_verdict=l12_verdict,
            state_key="allowed_quorum_pressure_state",
        ):
            return
        payload["signal_json_emit_result"] = self._emit_signal_json_payload(payload)
        report["allowed_quorum_decision_update"] = payload
        l12_verdict["allowed_quorum_decision_update"] = payload

    def _allowed_quorum_contextless_pressure_payload(
        self,
        *,
        symbol: str,
        allowed_quorum: dict[str, Any],
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        source_verdict: str,
    ) -> dict[str, Any]:
        symbol_key = str(symbol or "").upper()
        direction = self._direction_hint(allowed_quorum.get("direction")) or self._direction_hint(
            l12_verdict.get("direction")
        )
        symbol_activity_raw = report.get("symbol_activity")
        symbol_activity = symbol_activity_raw if isinstance(symbol_activity_raw, dict) else {}
        activity_raw = symbol_activity.get(symbol_key)
        activity = activity_raw if isinstance(activity_raw, dict) else {}
        event_time = str(activity.get("latest_event_utc") or datetime.now(UTC).isoformat())
        cluster_stamp = event_time.replace(":", "").replace("-", "").replace("+", "Z")
        cluster_id = f"{symbol_key}_{cluster_stamp}_ALLOWED_QUORUM_CONTEXTLESS"
        blockers = self._allowed_quorum_blockers(l12_verdict=l12_verdict, report=report)
        for forced in ("MARKET_CONTEXT_MISSING", "REFERENCE_PRICE_MISSING", "PRICE_THEME_STRUCTURE_PENDING"):
            blockers.setdefault(forced, 1)
        pressure_event_count = self._no_trade_pressure_event_count(symbol=symbol_key, report=report)
        quorum_streak = self._coerce_non_negative_int(allowed_quorum.get("streak")) or 0
        pressure_event_count = max(pressure_event_count, quorum_streak)
        microboost_summary_raw = report.get("microboost_summary")
        microboost_summary = microboost_summary_raw if isinstance(microboost_summary_raw, dict) else {}
        microboost_detected = bool(microboost_summary.get("count_total"))
        payload: dict[str, Any] = {
            "event": "signal_decision_update_json",
            "schema_version": "1.0-pressure-state",
            "symbol": symbol_key,
            "cluster_id": cluster_id,
            "signal_family": "SIGNAL_THROTTLE_ALLOWED_QUORUM",
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "promotion_stage": "PRESSURE_ONLY",
            "source_status": "CANARY_QUORUM_PENDING_VALIDATION",
            "status": "ALLOWED_QUORUM_WAIT_CONTEXT",
            "previous_status": "CANARY_QUORUM_PENDING_VALIDATION",
            "new_status": "ALLOWED_QUORUM_WAIT_CONTEXT",
            "raw_direction": direction,
            "candidate_direction": direction,
            "validated_direction": None,
            "watch_direction": direction,
            "final_direction": "WAIT",
            "direction_validation_status": "ALLOWED_QUORUM_CONTEXT_MISSING",
            "action": "WAIT_PRICE_THEME_STRUCTURE",
            "next_action": "WAIT_PRICE_THEME_STRUCTURE",
            "next_required_stage": "PRICE_THEME_STRUCTURE",
            "signal_valid_time_utc": event_time,
            "market_context_applied": False,
            "context_missing": True,
            "valid_for_execution": False,
            "signal_valid": False,
            "analysis_valid": True,
            "direction_valid": False,
            "tradeplan_valid": False,
            "execution_valid_now": False,
            "execution_status": "PRESSURE_ONLY",
            "terminal_status": "PRESSURE_ONLY",
            "decision_update_trigger": "ALLOWED_QUORUM_CONTEXT_INCOMPLETE",
            "pending_decision_id": f"{cluster_id}_PRESSURE_STATE",
            "pressure_seen": True,
            "allowed_quorum_seen": True,
            "pair_eligible_for_analysis": True,
            "allowed_quorum": dict(allowed_quorum),
            "pressure_event_count": pressure_event_count,
            "pressure_level": "MICROBOOST_WATCH" if microboost_detected else "PRESSURE_CANARY",
            "pressure_strength": "MICROBOOST" if microboost_detected else "CANARY",
            "pressure_source": "SIGNAL_THROTTLE",
            "source_verdict": source_verdict,
            "source_verdict_is_execute": source_verdict.startswith("EXECUTE"),
            "execution_block_reason": next(iter(blockers), "PRICE_THEME_STRUCTURE_PENDING"),
            "watch_promotion_blockers": blockers,
            "microboost_detected": microboost_detected,
            "reason": (
                "Allowed quorum reached SignalThrottle pressure state, but market context or "
                "reference price is missing. Pressure remains visible; execution stays blocked."
            ),
        }
        if os.getenv("SIGNAL_FAMILY_LINEAGE_ENABLED", "false").strip().lower() == "true":
            payload.update(
                self._pressure_family_lineage(
                    report,
                    microboost_detected=bool(microboost_detected),
                    resolved_family="ALLOWED_QUORUM_CONTEXTLESS_PRESSURE_STATE",
                )
            )
        htf_context = self._resolve_htf_structure_context(symbol_key)
        if htf_context is not None:
            payload["htf_structure_context"] = htf_context
        return payload

    def _emit_contextless_quorum_diagnostic(
        self,
        *,
        symbol: str,
        allowed_quorum: dict[str, Any],
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Increment F.1 (flag default OFF): when an allowed quorum reaches the radar and
        fails watch promotion but the normal *priced* NO_TRADE_REASONED cannot be built
        (no MarketContext / reference price), emit a DIAGNOSTIC-ONLY terminal so the
        pressure does not die silently.

        Deliberately NOT a SignalDecisionUpdateJSON: that contract is price/trade-context
        mandatory (``build_signal_json_event`` rejects a priceless payload) and weakening
        it would risk the same protection that prevents fake SignalJSON. So this emits a
        separate ``signal_quorum_terminal_diagnostic_json`` event straight to the log
        channel -- it never calls ``build_signal_json_event``, never carries / invents a
        price or entry_zone, never invents a direction, and is never executable.

        Enable: ``SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED=true``.
        """
        if (
            os.getenv("SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED", "false").strip().lower()
            != "true"
        ):
            return None
        symbol_key = str(symbol or "").upper()
        if not symbol_key:
            return None
        direction = self._direction_hint(allowed_quorum.get("direction")) or self._direction_hint(
            l12_verdict.get("direction")
        )
        symbol_activity_raw = report.get("symbol_activity")
        symbol_activity = symbol_activity_raw if isinstance(symbol_activity_raw, dict) else {}
        activity_raw = symbol_activity.get(symbol_key)
        activity = activity_raw if isinstance(activity_raw, dict) else {}
        event_time = str(activity.get("latest_event_utc") or datetime.now(UTC).isoformat())
        cluster_stamp = event_time.replace(":", "").replace("-", "").replace("+", "Z")
        cluster_id = f"{symbol_key}_{cluster_stamp}_ALLOWED_QUORUM_CONTEXTLESS"
        blockers = self._allowed_quorum_blockers(l12_verdict=l12_verdict, report=report)
        for forced in ("WATCH_PROMOTION_FAILED", "MARKET_CONTEXT_MISSING", "REFERENCE_PRICE_MISSING"):
            blockers.setdefault(forced, 1)
        payload: dict[str, Any] = {
            "event": "signal_quorum_terminal_diagnostic_json",
            "schema_version": "1.0",
            "symbol": symbol_key,
            "cluster_id": cluster_id,
            "signal_family": "SIGNAL_THROTTLE_ALLOWED_QUORUM",
            "source_status": "CANARY_QUORUM_PENDING_VALIDATION",
            "terminal_status": "NO_TRADE_REASONED_CONTEXTLESS",
            "raw_direction": direction,
            "candidate_direction": direction,
            "validated_direction": None,
            "watch_direction": direction,
            "final_direction": "WAIT",
            "direction_validation_status": "ALLOWED_QUORUM_CONTEXT_MISSING",
            "signal_valid_time_utc": event_time,
            "market_context_applied": False,
            "context_missing": True,
            "diagnostic_only": True,
            "valid_for_execution": False,
            "is_final_signal": False,
            "signal_valid": False,
            "pair_eligible_for_analysis": True,
            "pressure_seen": True,
            "allowed_quorum_seen": True,
            "allowed_quorum": dict(allowed_quorum),
            "decision_update_trigger": "ALLOWED_QUORUM_CONTEXT_MISSING",
            "pending_decision_id": f"{cluster_id}_DIAGNOSTIC",
            "watch_promotion_blockers": blockers,
            "reason": (
                "Allowed quorum reached the throttle radar but watch promotion failed and market "
                "context / reference price was unavailable, so no priced decision object could be "
                "built. Diagnostic only; NOT a SignalDecisionUpdateJSON and never executable."
            ),
        }
        import json  # noqa: PLC0415 -- local: stdlib json is not a module-level import here
        import logging  # noqa: PLC0415 -- local: `logging` is only imported on the loguru-absent path

        logging.getLogger("signal_json").warning(
            "%s %s",
            "[SignalQuorumDiagnosticJSON]",
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )
        report["allowed_quorum_contextless_diagnostic"] = payload
        l12_verdict["allowed_quorum_contextless_diagnostic"] = payload
        return payload

    @staticmethod
    def _has_signal_throttle_watch_or_decision_candidate(report: dict[str, Any]) -> bool:
        for key in (
            "microboost_continuation_entry",
            "microboost_counter_entry",
            "microboost_watch_entry",
        ):
            candidate = report.get(key)
            if isinstance(candidate, dict) and str(candidate.get("status") or "NONE") != "NONE":
                return True
        clean_watch_entries = report.get("clean_block_watch_entries")
        if isinstance(clean_watch_entries, list) and any(
            isinstance(entry, dict) and str(entry.get("status") or "NONE") != "NONE"
            for entry in clean_watch_entries
        ):
            return True
        updates = report.get("signal_block_finalizer_updates")
        if isinstance(updates, list) and any(isinstance(update, dict) for update in updates):
            return True
        if isinstance(report.get("allowed_quorum_pressure_state"), dict):
            return True
        if isinstance(report.get("no_trade_pressure_state"), dict):
            return True
        return isinstance(report.get("no_trade_pressure_decision_update"), dict)

    def _should_emit_allowed_quorum_decision(self, *, symbol: str) -> bool:
        try:
            cooldown_seconds = max(
                0.0,
                float(os.getenv("SIGNAL_THROTTLE_ALLOWED_QUORUM_DECISION_COOLDOWN_SECONDS", "75")),
            )
        except (TypeError, ValueError):
            cooldown_seconds = 75.0
        now = time.time()
        last_seen = getattr(self, "_last_allowed_quorum_decision_at", None)
        if not isinstance(last_seen, dict):
            last_seen = {}
            self._last_allowed_quorum_decision_at = last_seen
        symbol_key = symbol.upper()
        previous = last_seen.get(symbol_key)
        if previous is not None and now - previous < cooldown_seconds:
            return False
        last_seen[symbol_key] = now
        return True

    def _allowed_quorum_decision_update_payload(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        market_contexts: dict[str, MarketContext],
        source_verdict: str,
    ) -> dict[str, Any] | None:
        context = market_contexts.get(symbol.upper())
        if context is None:
            return None
        price_lineage = self._pressure_reference_price_lineage(
            symbol=symbol,
            context=context,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            allow_payload_fallback=False,
        )
        price = None if price_lineage is None else price_lineage.get("price")
        if price is None:
            return None
        allowed_quorum_raw = report.get("allowed_quorum")
        allowed_quorum = allowed_quorum_raw if isinstance(allowed_quorum_raw, dict) else {}
        direction = self._direction_hint(allowed_quorum.get("direction")) or self._direction_hint(
            l12_verdict.get("direction")
        )
        symbol_activity_raw = report.get("symbol_activity")
        symbol_activity = symbol_activity_raw if isinstance(symbol_activity_raw, dict) else {}
        activity_raw = symbol_activity.get(symbol.upper())
        activity = activity_raw if isinstance(activity_raw, dict) else {}
        event_time = str(activity.get("latest_event_utc") or datetime.now(UTC).isoformat())
        cluster_stamp = event_time.replace(":", "").replace("-", "").replace("+", "Z")
        cluster_id = f"{symbol.upper()}_{cluster_stamp}_ALLOWED_QUORUM"
        blockers = self._allowed_quorum_blockers(l12_verdict=l12_verdict, report=report)
        blocker_reason = next(iter(blockers), "CANARY_QUORUM_PENDING_VALIDATION")
        pressure_event_count = self._no_trade_pressure_event_count(symbol=symbol, report=report)
        quorum_streak = self._coerce_non_negative_int(allowed_quorum.get("streak")) or 0
        pressure_event_count = max(pressure_event_count, quorum_streak)
        microboost_summary_raw = report.get("microboost_summary")
        microboost_summary = microboost_summary_raw if isinstance(microboost_summary_raw, dict) else {}
        microboost_detected = bool(microboost_summary.get("count_total"))
        payload: dict[str, Any] = {
            "event": "signal_decision_update_json",
            "symbol": symbol.upper(),
            "cluster_id": cluster_id,
            "signal_family": "SIGNAL_THROTTLE_ALLOWED_QUORUM",
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "promotion_stage": "PRESSURE_ONLY",
            "source_status": "CANARY_QUORUM_PENDING_VALIDATION",
            "status": "NO_TRADE_REASONED",
            "previous_status": "CANARY_QUORUM_PENDING_VALIDATION",
            "new_status": "NO_TRADE_REASONED",
            "raw_direction": direction,
            "candidate_direction": direction,
            "validated_direction": None,
            "watch_direction": direction,
            "final_direction": "WAIT",
            "direction_validation_status": "ALLOWED_QUORUM_CONTEXT_INCOMPLETE",
            "action": "WAIT_PRICE_THEME_STRUCTURE",
            "next_action": "WAIT_PRICE_THEME_STRUCTURE",
            "signal_valid_time_utc": event_time,
            "signal_valid_price": price,
            "entry_reference_price": price,
            "entry_zone": [price, price],
            **self._decision_price_lineage_payload(price_lineage),
            "rr_status": "UNVALIDATED",
            "market_context_applied": context is not None,
            "valid_for_execution": False,
            "signal_valid": False,
            "analysis_valid": True,
            "direction_valid": False,
            "tradeplan_valid": False,
            "execution_valid_now": False,
            "execution_status": "NO_TRADE_REASONED",
            "terminal_status": "NO_TRADE_REASONED",
            "decision_update_trigger": "ALLOWED_QUORUM_CONTEXT_INCOMPLETE",
            "pending_decision_id": f"{cluster_id}_DECISION",
            "pressure_seen": True,
            "allowed_quorum_seen": True,
            "pair_eligible_for_analysis": True,
            "allowed_quorum": dict(allowed_quorum),
            "pressure_event_count": pressure_event_count,
            "pressure_level": "MICROBOOST_WATCH" if microboost_detected else "PRESSURE_CANARY",
            "pressure_strength": "MICROBOOST" if microboost_detected else "CANARY",
            "pressure_source": "SIGNAL_THROTTLE",
            "source_verdict": source_verdict,
            "execution_block_reason": blocker_reason,
            "watch_promotion_blockers": blockers,
            "microboost_detected": microboost_detected,
            "reason": (
                "Allowed quorum pressure reached throttle-radar, but price/theme/structure validation "
                "is incomplete; no order is authorized until validation promotes a watch or final signal."
            ),
        }
        if os.getenv("SIGNAL_FAMILY_LINEAGE_ENABLED", "false").strip().lower() == "true":
            payload.update(
                self._pressure_family_lineage(
                    report,
                    microboost_detected=bool(microboost_detected),
                    resolved_family="ALLOWED_QUORUM_PENDING_VALIDATION",
                )
            )
        htf_context = self._htf_structure_context_from_market_context(context)
        if htf_context is not None:
            payload["htf_structure_context"] = htf_context
        return payload

    def _allowed_quorum_blockers(
        self,
        *,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
    ) -> dict[str, int]:
        blockers_raw = report.get("watch_promotion_blockers")
        blockers: dict[str, int] = dict(blockers_raw) if isinstance(blockers_raw, dict) else {}
        for reason in self._l12_blocker_reasons(l12_verdict):
            blockers[reason] = int(blockers.get(reason, 0)) + 1
        if not blockers:
            blockers["CANARY_QUORUM_PENDING_VALIDATION"] = 1
        return blockers

    @staticmethod
    def _l12_blocker_reasons(l12_verdict: dict[str, Any]) -> list[str]:
        raw_values: list[Any] = []
        for key in ("errors", "blockers", "audit_block_reasons", "hard_blockers", "soft_blockers"):
            value = l12_verdict.get(key)
            if isinstance(value, list):
                raw_values.extend(value)
            elif isinstance(value, str):
                raw_values.append(value)
        reasons: list[str] = []
        for value in raw_values:
            text = str(value or "").strip().upper()
            if not text:
                continue
            if ":" in text:
                text = text.rsplit(":", 1)[-1]
            reasons.append(text)
        return list(dict.fromkeys(reasons))

    def _pressure_reference_price(
        self,
        *,
        context: MarketContext | None,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        allow_payload_fallback: bool = True,
    ) -> float | None:
        lineage = self._pressure_reference_price_lineage(
            symbol=None,
            context=context,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            allow_payload_fallback=allow_payload_fallback,
        )
        return None if lineage is None else self._coerce_positive_float(lineage.get("price"))

    def _pressure_reference_price_lineage(
        self,
        *,
        symbol: str | None,
        context: MarketContext | None,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        allow_payload_fallback: bool = True,
    ) -> dict[str, Any] | None:
        if context is not None:
            for field_name, value in (
                ("price_at_signal_end", context.price_at_signal_end),
                ("price_at_5m_confirm", context.price_at_5m_confirm),
                ("price_at_signal_start", context.price_at_signal_start),
                ("bid", context.bid),
                ("ask", context.ask),
            ):
                price = self._coerce_positive_float(value)
                if price is not None:
                    resolved_symbol = str(symbol or context.symbol or "").upper() or None
                    source_info = self._pressure_reference_price_source(
                        symbol=resolved_symbol,
                        context=context,
                        field_name=field_name,
                        price=price,
                        synthesis=synthesis,
                        l12_verdict=l12_verdict,
                    )
                    source = str(source_info.get("price_source") or "UNKNOWN")
                    return {
                        "price": price,
                        "price_context_field": field_name,
                        **source_info,
                        **self._price_freshness_payload(
                            symbol=resolved_symbol,
                            source=source,
                            source_timestamp=source_info.get("price_source_timestamp_epoch"),
                        ),
                    }
        if not allow_payload_fallback:
            return None
        execution_raw = synthesis.get("execution")
        execution = execution_raw if isinstance(execution_raw, dict) else {}
        for field_name, value in (
            ("l12_entry_price", l12_verdict.get("entry_price")),
            ("l12_entry_reference_price", l12_verdict.get("entry_reference_price")),
            ("execution_entry_price", execution.get("entry_price")),
            ("execution_entry_reference_price", execution.get("entry_reference_price")),
            ("execution_price", execution.get("price")),
        ):
            price = self._coerce_positive_float(value)
            if price is not None:
                return {
                    "price": price,
                    "price_source": "EXECUTION_ENTRY",
                    "price_context_field": field_name,
                    **self._price_freshness_payload(symbol=symbol, source="EXECUTION_ENTRY"),
                }
        return None

    def _decision_price_lineage_payload(self, lineage: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(lineage, dict):
            return {
                "decision_price_role": "REFERENCE_ONLY_NOT_EXECUTABLE",
                "price_source": "UNKNOWN",
                "price_snapshot_time_utc": None,
                "price_age_seconds": None,
                "price_freshness_status": "UNKNOWN",
                "reference_price_is_live": False,
                "price_lineage_version": 1,
            }
        price = self._coerce_positive_float(lineage.get("price"))
        payload = {
            "decision_price_role": "REFERENCE_ONLY_NOT_EXECUTABLE",
            "reference_price_used_for_decision_update": price,
            "price_source": str(lineage.get("price_source") or "UNKNOWN").upper(),
            "price_context_field": lineage.get("price_context_field"),
            "price_snapshot_time_utc": lineage.get("price_snapshot_time_utc"),
            "price_age_seconds": lineage.get("price_age_seconds"),
            "price_freshness_status": str(lineage.get("price_freshness_status") or "UNKNOWN").upper(),
            "reference_price_is_live": bool(lineage.get("reference_price_is_live")),
            "price_lineage_version": 1,
        }
        return payload

    def _pressure_reference_price_source(
        self,
        *,
        symbol: str | None,
        context: MarketContext,
        field_name: str,
        price: float,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        bid = self._coerce_positive_float(context.bid)
        ask = self._coerce_positive_float(context.ask)
        tick_mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
        if tick_mid is not None and self._same_reference_price(price, tick_mid):
            return {"price_source": "LIVE_TICK_MID"}
        if field_name == "bid":
            return {"price_source": "LIVE_TICK_BID"}
        if field_name == "ask":
            return {"price_source": "LIVE_TICK_ASK"}
        if self._matches_execution_entry_price(price, synthesis=synthesis, l12_verdict=l12_verdict):
            return {"price_source": "EXECUTION_ENTRY"}
        if candle_source := self._matching_candle_reference(symbol=symbol, price=price, timeframes=("M15", "H1")):
            return candle_source
        if field_name == "price_at_5m_confirm":
            return {"price_source": "M15_CLOSE"}
        if field_name == "price_at_signal_end" and self._same_reference_price(price, context.price_at_5m_confirm):
            return {"price_source": "M15_CLOSE"}
        if field_name == "price_at_signal_start" and self._same_reference_price(price, context.price_at_5m_confirm):
            return {"price_source": "M15_CLOSE"}
        return {"price_source": "UNKNOWN"}

    def _matching_candle_reference(
        self,
        *,
        symbol: str | None,
        price: float,
        timeframes: tuple[str, ...],
    ) -> dict[str, Any] | None:
        if not symbol:
            return None
        for timeframe in timeframes:
            candle = self._latest_candle_reference(symbol=symbol, timeframe=timeframe)
            if candle is None or not self._same_reference_price(price, candle.get("close")):
                continue
            return {
                "price_source": f"{timeframe.upper()}_CLOSE",
                "price_source_timestamp_epoch": candle.get("timestamp_epoch"),
            }
        return None

    def _latest_candle_reference(self, *, symbol: str, timeframe: str) -> dict[str, Any] | None:
        bus = getattr(self, "_context_bus", None)
        if bus is None or not hasattr(bus, "get_candle_history"):
            return None
        try:
            candles = bus.get_candle_history(symbol, timeframe, count=1)
        except Exception:  # noqa: BLE001 - diagnostics must not break decision payloads.
            return None
        if not candles:
            return None
        candle = candles[-1]
        if not isinstance(candle, dict):
            return None
        close = self._candle_price(candle, "close")
        timestamp = self._candle_timestamp_epoch(candle)
        return {"close": close, "timestamp_epoch": timestamp}

    @staticmethod
    def _candle_timestamp_epoch(candle: dict[str, Any]) -> float | None:
        for key in ("timestamp_close", "close_time", "timestamp", "time", "datetime", "last_seen_ts", "ts"):
            timestamp = _coerce_timestamp_to_epoch(candle.get(key))
            if timestamp is None:
                continue
            if timestamp > 10_000_000_000:
                timestamp /= 1000.0
            return timestamp
        return None

    def _matches_execution_entry_price(
        self,
        price: float,
        *,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> bool:
        execution_raw = synthesis.get("execution")
        execution = execution_raw if isinstance(execution_raw, dict) else {}
        for value in (
            l12_verdict.get("entry_price"),
            l12_verdict.get("entry_reference_price"),
            execution.get("entry_price"),
            execution.get("entry_reference_price"),
            execution.get("price"),
        ):
            if self._same_reference_price(price, self._coerce_positive_float(value)):
                return True
        return False

    @staticmethod
    def _same_reference_price(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return False
        try:
            return abs(float(left) - float(right)) <= 1e-9
        except (TypeError, ValueError):
            return False

    def _price_freshness_payload(
        self,
        *,
        symbol: str | None,
        source: str,
        source_timestamp: Any | None = None,
    ) -> dict[str, Any]:
        symbol_key = str(symbol or "").upper()
        bus = getattr(self, "_context_bus", None)
        feed_status = "UNKNOWN"
        feed_age: float | None = None
        feed_timestamp: float | None = None
        if symbol_key and bus is not None:
            try:
                if hasattr(bus, "get_feed_status"):
                    feed_status = str(bus.get_feed_status(symbol_key) or "UNKNOWN").upper()
            except Exception:  # noqa: BLE001 - diagnostics must not break decision payloads.
                feed_status = "UNKNOWN"
            try:
                if hasattr(bus, "get_feed_age"):
                    raw_age = bus.get_feed_age(symbol_key)
                    feed_age = None if raw_age is None else round(max(0.0, float(raw_age)), 3)
            except Exception:  # noqa: BLE001
                feed_age = None
            try:
                if hasattr(bus, "get_feed_timestamp"):
                    raw_ts = bus.get_feed_timestamp(symbol_key)
                    feed_timestamp = None if raw_ts is None else float(raw_ts)
            except Exception:  # noqa: BLE001
                feed_timestamp = None
        is_tick_source = str(source or "").upper().startswith("LIVE_TICK")
        source_timestamp_epoch = self._coerce_float_or_none(source_timestamp)
        if source_timestamp_epoch is not None and source_timestamp_epoch > 10_000_000_000:
            source_timestamp_epoch /= 1000.0
        source_age = (
            None
            if source_timestamp_epoch is None
            else round(max(0.0, datetime.now(UTC).timestamp() - source_timestamp_epoch), 3)
        )
        snapshot_timestamp = feed_timestamp if is_tick_source else source_timestamp_epoch
        return {
            "price_snapshot_time_utc": self._epoch_to_utc_iso(snapshot_timestamp),
            "price_age_seconds": feed_age if is_tick_source else source_age,
            "price_freshness_status": feed_status,
            "reference_price_is_live": is_tick_source and feed_status == "LIVE",
        }

    @staticmethod
    def _epoch_to_utc_iso(value: float | None) -> str | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), UTC).isoformat()
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    def _apply_no_trade_pressure_decision_update(
        self,
        *,
        symbol: str,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        market_contexts: dict[str, MarketContext],
    ) -> None:
        if os.getenv("SIGNAL_THROTTLE_NO_TRADE_DECISION_UPDATE_ENABLED", "true").strip().lower() != "true":
            return
        if isinstance(report.get("allowed_quorum_pressure_state"), dict) or isinstance(
            l12_verdict.get("allowed_quorum_pressure_state"), dict
        ):
            return
        verdict = str(l12_verdict.get("verdict") or "").strip().upper()
        if verdict.startswith("EXECUTE"):
            return
        pressure_event_count = self._no_trade_pressure_event_count(symbol=symbol, report=report)
        pressure_seen = pressure_event_count > 0
        if not pressure_seen:
            return
        microboost_summary = (
            report.get("microboost_summary") if isinstance(report.get("microboost_summary"), dict) else {}
        )
        microboost_detected = bool((microboost_summary or {}).get("count_total"))
        if not self._should_emit_no_trade_pressure_decision(
            symbol=symbol,
            pressure_event_count=pressure_event_count,
            microboost_detected=microboost_detected,
        ):
            return
        payload = self._no_trade_pressure_decision_update_payload(
            symbol=symbol,
            l12_verdict=l12_verdict,
            report=report,
            market_contexts=market_contexts,
            pressure_event_count=pressure_event_count,
            microboost_detected=microboost_detected,
        )
        if payload is None:
            pressure_payload = self._no_trade_contextless_pressure_payload(
                symbol=symbol,
                l12_verdict=l12_verdict,
                report=report,
                pressure_event_count=pressure_event_count,
                microboost_detected=microboost_detected,
            )
            self._store_signal_pressure_state(
                pressure_payload,
                report=report,
                l12_verdict=l12_verdict,
                state_key="no_trade_pressure_state",
            )
            return
        if self._route_pressure_decision_or_emit(
            payload,
            report=report,
            l12_verdict=l12_verdict,
            state_key="no_trade_pressure_state",
        ):
            return
        payload["signal_json_emit_result"] = self._emit_signal_json_payload(payload)
        report["no_trade_pressure_decision_update"] = payload
        l12_verdict["no_trade_pressure_decision_update"] = payload

    def _no_trade_contextless_pressure_payload(
        self,
        *,
        symbol: str,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        pressure_event_count: int,
        microboost_detected: bool,
    ) -> dict[str, Any]:
        symbol_key = str(symbol or "").upper()
        direction = self._direction_hint(l12_verdict.get("direction"))
        symbol_activity_raw = report.get("symbol_activity")
        symbol_activity = symbol_activity_raw if isinstance(symbol_activity_raw, dict) else {}
        activity_raw = symbol_activity.get(symbol_key)
        activity = activity_raw if isinstance(activity_raw, dict) else {}
        event_time = str(activity.get("latest_event_utc") or datetime.now(UTC).isoformat())
        cluster_stamp = event_time.replace(":", "").replace("-", "").replace("+", "Z")
        cluster_id = f"{symbol_key}_{cluster_stamp}_NO_TRADE_CONTEXTLESS"
        blockers = self._allowed_quorum_blockers(l12_verdict=l12_verdict, report=report)
        for forced in ("NON_EXECUTE_VERDICT", "MARKET_CONTEXT_MISSING", "REFERENCE_PRICE_MISSING"):
            blockers.setdefault(forced, 1)
        payload: dict[str, Any] = {
            "event": "signal_decision_update_json",
            "schema_version": "1.0-pressure-state",
            "symbol": symbol_key,
            "cluster_id": cluster_id,
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "promotion_stage": "PRESSURE_ONLY",
            "status": "PRESSURE_CANARY",
            "previous_status": "PRESSURE_SEEN",
            "new_status": "PRESSURE_CANARY",
            "raw_direction": direction,
            "candidate_direction": direction,
            "validated_direction": None,
            "watch_direction": direction,
            "final_direction": "WAIT",
            "direction_validation_status": "NO_TRADE_PRESSURE_CONTEXT_MISSING",
            "action": "WAIT_FOR_EXECUTION_QUALITY",
            "next_action": "WAIT_FOR_EXECUTION_QUALITY",
            "next_required_stage": "MARKET_CONTEXT_OR_EXECUTION_QUALITY",
            "signal_valid_time_utc": event_time,
            "market_context_applied": False,
            "context_missing": True,
            "valid_for_execution": False,
            "signal_valid": False,
            "analysis_valid": True,
            "direction_valid": False,
            "tradeplan_valid": False,
            "execution_valid_now": False,
            "execution_status": "PRESSURE_ONLY",
            "terminal_status": "PRESSURE_ONLY",
            "decision_update_trigger": "NON_EXECUTE_PRESSURE_CANARY",
            "pending_decision_id": f"{cluster_id}_PRESSURE_STATE",
            "pressure_seen": True,
            "pressure_event_count": pressure_event_count,
            "pressure_level": "MICROBOOST_WATCH" if microboost_detected else "PRESSURE_CANARY",
            "pressure_strength": "MICROBOOST" if microboost_detected else "CANARY",
            "pressure_source": "SIGNAL_THROTTLE",
            "execution_block_reason": "NON_EXECUTE_VERDICT",
            "watch_promotion_blockers": blockers,
            "microboost_detected": microboost_detected,
            "reason": (
                "SignalThrottle pressure exists while L12 remains non-executable and market context "
                "or reference price is missing. Pressure remains visible; execution stays blocked."
            ),
        }
        if os.getenv("SIGNAL_FAMILY_LINEAGE_ENABLED", "false").strip().lower() == "true":
            payload.update(
                self._pressure_family_lineage(
                    report,
                    microboost_detected=bool(microboost_detected),
                    resolved_family="NO_TRADE_CONTEXTLESS_PRESSURE_STATE",
                )
            )
        htf_context = self._resolve_htf_structure_context(symbol_key)
        if htf_context is not None:
            payload["htf_structure_context"] = htf_context
        return payload

    def _no_trade_pressure_event_count(self, *, symbol: str, report: dict[str, Any]) -> int:
        symbol_key = symbol.upper()
        symbol_activity_raw = report.get("symbol_activity")
        symbol_activity = symbol_activity_raw if isinstance(symbol_activity_raw, dict) else {}
        activity_raw = symbol_activity.get(symbol_key)
        activity = activity_raw if isinstance(activity_raw, dict) else None
        if isinstance(activity, dict):
            for key in ("latest_block_effective_ticks", "latest_block_events"):
                value = self._coerce_non_negative_int(activity.get(key))
                if value is not None:
                    return value
        counts_raw = report.get("counts")
        counts = counts_raw if isinstance(counts_raw, dict) else {}
        pairs_raw = counts.get("pairs")
        pairs = pairs_raw if isinstance(pairs_raw, dict) else {}
        pair_count = self._coerce_non_negative_int(pairs.get(symbol_key))
        if pair_count is not None:
            return pair_count
        total_count = self._coerce_non_negative_int(counts.get("total_events"))
        return total_count or 0

    def _coerce_non_negative_int(self, value: Any) -> int | None:
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, coerced)

    def _should_emit_no_trade_pressure_decision(
        self,
        *,
        symbol: str,
        pressure_event_count: int,
        microboost_detected: bool,
    ) -> bool:
        try:
            min_events = max(
                1,
                int(os.getenv("SIGNAL_THROTTLE_NO_TRADE_DECISION_MIN_EVENTS", "3")),
            )
        except (TypeError, ValueError):
            min_events = 3
        try:
            cooldown_seconds = max(
                0.0,
                float(os.getenv("SIGNAL_THROTTLE_NO_TRADE_DECISION_COOLDOWN_SECONDS", "75")),
            )
        except (TypeError, ValueError):
            cooldown_seconds = 75.0
        if not microboost_detected and pressure_event_count < min_events:
            return False
        now = time.time()
        last_seen = getattr(self, "_last_no_trade_pressure_decision_at", None)
        if not isinstance(last_seen, dict):
            last_seen = {}
            self._last_no_trade_pressure_decision_at = last_seen
        symbol_key = symbol.upper()
        previous = last_seen.get(symbol_key)
        if previous is not None and now - previous < cooldown_seconds:
            return False
        last_seen[symbol_key] = now
        return True

    @staticmethod
    def _pressure_family_lineage(
        report: dict[str, Any],
        *,
        microboost_detected: bool,
        resolved_family: str,
    ) -> dict[str, Any]:
        """Derive family lineage for a pressure DecisionUpdate from signals already
        present in ``report`` (pure + deterministic; no new data sources).

        Preserves signal-family intelligence instead of flattening every decision to
        the parent ``signal_family``. Returns ``source_family`` (origin),
        ``source_stage`` (producing pipeline stage), ``resolved_family`` (outcome
        semantics) and a ``family_lineage_version`` for forward-compat.
        """
        quorum_raw = report.get("allowed_quorum")
        quorum = quorum_raw if isinstance(quorum_raw, dict) else {}
        lifecycle_raw = report.get("candidate_lifecycle")
        lifecycle = lifecycle_raw if isinstance(lifecycle_raw, dict) else {}
        lifecycle_status = str(lifecycle.get("status") or "")
        phase = str(report.get("latest_phase") or "")
        micro_raw = report.get("microboost_summary")
        micro = micro_raw if isinstance(micro_raw, dict) else {}
        latest_raw = micro.get("latest")
        latest = latest_raw if isinstance(latest_raw, dict) else {}
        micro_phase = str(latest.get("phase_unpriced") or "").upper()

        if quorum.get("quorum_reached"):
            source_family, source_stage = "ALLOWED_CANARY_QUORUM", "SIGNAL_THROTTLE_INTEL"
        elif microboost_detected:
            source_stage = "MICROBOOST"
            if "REPEATED" in micro_phase:
                source_family = "REPEATED_MICROBOOST"
            elif "IGNITION" in micro_phase:
                source_family = "IGNITION_MICROBOOST"
            elif "NEAR_TIMING_GATE" in micro_phase:
                source_family = "NEAR_GATE_MICROBOOST"
            else:
                source_family = "MICROBOOST_PRESSURE"
        elif lifecycle_status == "LATEST_IGNITION_WATCH_ONLY":
            source_family, source_stage = "IGNITION_WATCH", "CANDIDATE_LIFECYCLE"
        elif lifecycle_status.startswith("PAIR_SIGNAL_CANDIDATE"):
            source_family, source_stage = "TIMING_BLOCK", "CANDIDATE_LIFECYCLE"
        elif phase in {"THEME_PRESSURE", "BROAD_ROTATION_FRAGMENTED"}:
            source_family, source_stage = "THEME_PRESSURE", "PRESSURE_BLOCK"
        else:
            source_family, source_stage = "THROTTLE_PRESSURE_CANARY", "SIGNAL_THROTTLE_INTEL"

        reasons = {
            "ALLOWED_CANARY_QUORUM": "allowed_quorum_reached_but_execution_quality_missing",
            "REPEATED_MICROBOOST": "repeated_microboost_pressure_without_confirmed_direction",
            "IGNITION_MICROBOOST": "ignition_microboost_pressure_pending_validation",
            "NEAR_GATE_MICROBOOST": "near_timing_gate_microboost_pending_context",
            "MICROBOOST_PRESSURE": "microboost_pressure_pending_context",
            "IGNITION_WATCH": "latest_ignition_watch_only_no_clean_block_yet",
            "TIMING_BLOCK": "timing_block_candidate_pending_execution_quality",
            "THEME_PRESSURE": "theme_pressure_fragmented_no_pair_block",
            "THROTTLE_PRESSURE_CANARY": "throttle_pressure_canary_telemetry_only",
        }
        return {
            "source_family": source_family,
            "source_stage": source_stage,
            "resolved_family": resolved_family,
            "family_lineage_version": 1,
            "family_lineage_reason": reasons.get(source_family, "pressure_telemetry_only"),
        }

    def _no_trade_pressure_decision_update_payload(
        self,
        *,
        symbol: str,
        l12_verdict: dict[str, Any],
        report: dict[str, Any],
        market_contexts: dict[str, MarketContext],
        pressure_event_count: int | None = None,
        microboost_detected: bool | None = None,
    ) -> dict[str, Any] | None:
        context = market_contexts.get(symbol.upper())
        price = None
        if context is not None:
            price = (
                context.price_at_signal_end
                or context.price_at_signal_start
                or context.price_at_5m_confirm
                or context.bid
                or context.ask
            )
        price = self._coerce_positive_float(price)
        if price is None:
            return None
        direction = self._direction_hint(l12_verdict.get("direction"))
        symbol_activity_raw = report.get("symbol_activity")
        symbol_activity = symbol_activity_raw if isinstance(symbol_activity_raw, dict) else {}
        activity_raw = symbol_activity.get(symbol.upper())
        activity = activity_raw if isinstance(activity_raw, dict) else {}
        event_time = str(activity.get("latest_event_utc") or datetime.now(UTC).isoformat())
        cluster_stamp = event_time.replace(":", "").replace("-", "").replace("+", "Z")
        cluster_id = f"{symbol.upper()}_{cluster_stamp}_NO_TRADE"
        if pressure_event_count is None:
            pressure_event_count = self._no_trade_pressure_event_count(symbol=symbol, report=report)
        if microboost_detected is None:
            microboost_summary_raw = report.get("microboost_summary")
            microboost_summary = microboost_summary_raw if isinstance(microboost_summary_raw, dict) else {}
            microboost_detected = bool(microboost_summary.get("count_total"))
        payload: dict[str, Any] = {
            "event": "signal_decision_update_json",
            "symbol": symbol.upper(),
            "cluster_id": cluster_id,
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "promotion_stage": "PRESSURE_ONLY",
            "status": "NO_TRADE_REASONED",
            "previous_status": "PRESSURE_SEEN",
            "new_status": "NO_TRADE_REASONED",
            "raw_direction": direction,
            "candidate_direction": direction,
            "validated_direction": None,
            "watch_direction": direction,
            "final_direction": "WAIT",
            "direction_validation_status": "NO_TRADE_PRESSURE_TELEMETRY_ONLY",
            "action": "WAIT_FOR_EXECUTION_QUALITY",
            "next_action": "WAIT_FOR_EXECUTION_QUALITY",
            "signal_valid_time_utc": event_time,
            "signal_valid_price": price,
            "entry_reference_price": price,
            "entry_zone": [price, price],
            "rr_status": "UNVALIDATED",
            "market_context_applied": context is not None,
            "valid_for_execution": False,
            "signal_valid": False,
            "analysis_valid": True,
            "direction_valid": False,
            "tradeplan_valid": False,
            "execution_valid_now": False,
            "execution_status": "NO_TRADE_REASONED",
            "terminal_status": "NO_TRADE_REASONED",
            "decision_update_trigger": "NON_EXECUTE_PRESSURE_CANARY",
            "pending_decision_id": f"{cluster_id}_DECISION",
            "pressure_seen": True,
            "pressure_event_count": pressure_event_count,
            "pressure_level": "MICROBOOST_WATCH" if microboost_detected else "PRESSURE_CANARY",
            "pressure_strength": "MICROBOOST" if microboost_detected else "CANARY",
            "pressure_source": "signal_throttle_check",
            "execution_block_reason": "NON_EXECUTE_VERDICT",
            "microboost_detected": microboost_detected,
            "reason": (
                "Pressure seen but execution verdict remains NO_TRADE; "
                "no order is authorized from pressure telemetry alone."
            ),
        }
        if os.getenv("SIGNAL_FAMILY_LINEAGE_ENABLED", "false").strip().lower() == "true":
            payload.update(
                self._pressure_family_lineage(
                    report,
                    microboost_detected=bool(microboost_detected),
                    resolved_family="NO_TRADE_PRESSURE_TELEMETRY_ONLY",
                )
            )
        htf_context = self._htf_structure_context_from_market_context(context)
        if htf_context is not None:
            payload["htf_structure_context"] = htf_context
        return payload

    def _bump_family_counters(self, payload: dict[str, Any]) -> None:
        """Accumulate in-memory family/direction counters for deploy validation.

        Pure in-memory; does NOT add log volume. Gated by
        ``SIGNAL_FAMILY_COUNTERS_ENABLED`` (default on). Surfaced via
        ``family_counters_snapshot()`` and ``report["family_counters"]``.
        """
        if os.getenv("SIGNAL_FAMILY_COUNTERS_ENABLED", "true").strip().lower() != "true":
            return
        if not isinstance(payload, dict):
            return
        counters = getattr(self, "_family_counters", None)
        if not isinstance(counters, dict):
            counters = {}
            self._family_counters = counters

        def _bump(key: str) -> None:
            counters[key] = int(counters.get(key, 0)) + 1

        event = str(payload.get("event") or "")
        status = str(payload.get("status") or "")
        signal_family = str(payload.get("signal_family") or "")
        direction_source = str(payload.get("direction_source") or "")
        raw_direction = str(payload.get("raw_direction") or "").upper()
        final_direction = str(payload.get("final_direction") or "").upper()

        if event == "signal_decision_update_json":
            _bump("pressure_decision_count")
        if signal_family == "MICROBOOST_WATCH" or status.endswith("_WATCH"):
            _bump("microboost_watch_count")
        if direction_source.startswith("INHERITED"):
            _bump("inherited_direction_count")
            if direction_source == "INHERITED_BUT_PHASE_AMBIGUOUS":
                _bump("phase_ambiguous_count")
        elif direction_source == "DIRECTION_CONFLICT_RECENT_INTEL":
            _bump("recent_conflict_count")
        elif direction_source == "DIRECTION_CONFLICT_PRICE_PHASE":
            _bump("price_phase_conflict_count")
        elif direction_source == "DIRECTION_STALE_INTEL":
            _bump("stale_intel_count")
        elif direction_source == "DIRECTION_MISSING" or (
            status.endswith("_WATCH") and raw_direction in {"", "NONE"}
        ):
            _bump("direction_missing_count")
        if final_direction in {"BUY", "SELL"}:
            _bump("pattern_resolved_count")

    def family_counters_snapshot(self) -> dict[str, Any]:
        """Return running family/direction counters + resolver config (canary telemetry)."""
        snapshot: dict[str, Any] = {
            "pressure_decision_count": 0,
            "microboost_watch_count": 0,
            "direction_missing_count": 0,
            "inherited_direction_count": 0,
            "pattern_resolved_count": 0,
            "phase_ambiguous_count": 0,
            "recent_conflict_count": 0,
            "price_phase_conflict_count": 0,
            "stale_intel_count": 0,
        }
        counters = getattr(self, "_family_counters", None)
        if isinstance(counters, dict):
            for key, value in counters.items():
                snapshot[key] = int(value)
        snapshot["microboost_direction_resolver_enabled"] = (
            os.getenv("MICROBOOST_DIRECTION_INHERIT_ENABLED", "false").strip().lower() == "true"
        )
        snapshot["signal_throttle_intel_direction_bridge_enabled"] = (
            os.getenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "false").strip().lower() == "true"
        )
        try:
            window = float(os.getenv("MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS", "600"))
        except (TypeError, ValueError):
            window = 600.0
        snapshot["direction_inheritance_window_seconds"] = window
        try:
            bridge_window = float(os.getenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", "600"))
        except (TypeError, ValueError):
            bridge_window = 600.0
        snapshot["intel_direction_bridge_window_seconds"] = max(1.0, bridge_window)
        cache = getattr(self, "_signal_throttle_intel_direction_cache", None)
        snapshot["intel_direction_bridge_cache_size"] = len(cache) if isinstance(cache, dict) else 0
        return snapshot

    def _emit_signal_json_payload(self, payload: dict[str, Any]) -> bool:
        self._bump_family_counters(payload)
        self._emit_lifecycle_shadow_preview(payload)
        watch_diagnostic = self._watch_source_guard_diagnostic(payload)
        if watch_diagnostic is not None:
            emit_result = self._emit_signal_watch_source_guard_diagnostic(watch_diagnostic, payload)
            payload["signal_json_emit_blocked_by_source_guard"] = True
            payload["signal_watch_source_diagnostic_emit_result"] = emit_result
            return False
        gated_payload = self._signal_json_gate_adapter.apply(payload)
        signal_event = build_signal_json_event(gated_payload)
        if signal_event is None:
            return False
        return self._signal_json_emitter.emit(signal_event)

    @staticmethod
    def _watch_source_guard_diagnostic(payload: dict[str, Any]) -> dict[str, Any] | None:
        if os.getenv("SIGNAL_WATCH_SOURCE_GUARD_ENABLED", "true").strip().lower() != "true":
            return None
        return signal_watch_source_diagnostic(payload)

    def _route_pressure_decision_or_emit(
        self,
        payload: dict[str, Any],
        *,
        report: dict[str, Any],
        l12_verdict: dict[str, Any],
        state_key: str,
    ) -> bool:
        if os.getenv("SIGNAL_DECISION_SOURCE_GUARD_ENABLED", "true").strip().lower() != "true":
            return False
        if (
            os.getenv("SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED", "true").strip().lower()
            != "true"
        ):
            return False
        route = route_decision_or_pressure(
            payload,
            require_lifecycle_anchor=(
                os.getenv("SIGNAL_DECISION_REQUIRE_LIFECYCLE_ANCHOR", "true").strip().lower() == "true"
            ),
        )
        if route.route != "SIGNAL_PRESSURE_STATE":
            return False
        pressure_payload = route.payload
        pressure_payload["signal_pressure_state_emit_result"] = self._emit_signal_pressure_state_payload(
            pressure_payload
        )
        report[state_key] = pressure_payload
        l12_verdict[state_key] = pressure_payload
        return True

    def _store_signal_pressure_state(
        self,
        payload: dict[str, Any],
        *,
        report: dict[str, Any],
        l12_verdict: dict[str, Any],
        state_key: str,
    ) -> dict[str, Any]:
        pressure_payload = convert_to_signal_pressure_state(payload)
        if "next_required_stage" in payload:
            pressure_payload["next_required_stage"] = payload["next_required_stage"]
        pressure_payload["signal_pressure_state_emit_result"] = self._emit_signal_pressure_state_payload(
            pressure_payload
        )
        report[state_key] = pressure_payload
        l12_verdict[state_key] = pressure_payload
        return pressure_payload

    def _emit_signal_pressure_state_payload(self, payload: dict[str, Any]) -> bool:
        if not self._pressure_state_log_allowed(payload):
            return False
        return emit_signal_pressure_state(
            payload,
            enabled=os.getenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "true").strip().lower() == "true",
            prefix=os.getenv("SIGNAL_PRESSURE_STATE_JSON_LOG_PREFIX", "[SignalPressureStateJSON]"),
        )

    def _pressure_state_log_allowed(self, payload: dict[str, Any]) -> bool:
        interval = self._parse_env_float_allow_zero(
            "SIGNAL_PRESSURE_STATE_RATE_LIMIT_SECONDS",
            60.0 if self._signal_log_compact_mode_enabled() else 0.0,
        )
        if interval <= 0.0:
            return True
        store = getattr(self, "_last_signal_pressure_state_emit", None)
        if not isinstance(store, dict):
            store = {}
            self._last_signal_pressure_state_emit = store
        symbol = str(payload.get("symbol") or "*").upper()
        state_key = self._pressure_state_log_key(payload)
        previous = store.get(symbol)
        now = time.time()
        if isinstance(previous, tuple) and len(previous) == 2:
            previous_key, previous_at = previous
            if previous_key == state_key and now - float(previous_at) < interval:
                return False
        store[symbol] = (state_key, now)
        return True

    @staticmethod
    def _pressure_state_log_key(payload: dict[str, Any]) -> str:
        import json  # noqa: PLC0415 -- local: diagnostic-only key serialization

        htf = payload.get("htf_structure_context")
        htf_key = {}
        if isinstance(htf, dict):
            htf_key = {
                "daily_bias": htf.get("daily_bias"),
                "h4_structure": htf.get("h4_structure"),
                "price_location": htf.get("price_location"),
                "allowed_playbook": htf.get("allowed_playbook"),
                "blocked_playbook": htf.get("blocked_playbook"),
            }
        key = {
            "symbol": payload.get("symbol"),
            "signal_family": payload.get("signal_family"),
            "status": payload.get("status"),
            "raw_direction": payload.get("raw_direction"),
            "candidate_direction": payload.get("candidate_direction"),
            "watch_direction": payload.get("watch_direction"),
            "source_stage": payload.get("source_stage"),
            "resolved_family": payload.get("resolved_family"),
            "direction_validation_status": payload.get("direction_validation_status"),
            "execution_block_reason": payload.get("execution_block_reason"),
            "next_required_stage": payload.get("next_required_stage"),
            "reason": payload.get("reason"),
            "htf": htf_key,
        }
        return json.dumps(key, sort_keys=True, separators=(",", ":"), default=str)

    def _emit_lifecycle_shadow_preview(self, payload: dict[str, Any]) -> None:
        """P1B (flag-guarded, default OFF): shadow-only preview of the active-signal
        lifecycle. Emits a side-channel ``[SignalLifecycleShadowPreview]`` line and
        NEVER mutates the payload, ``terminal_status``, ``lifecycle_status``, or
        ``valid_for_execution``. The live ``SignalLifecycleManager.apply()`` is not
        called; only the pure mapper is used.

        Enable with ``SIGNAL_LIFECYCLE_MANAGER_SHADOW_ENABLED=true``.
        """
        if os.getenv("SIGNAL_LIFECYCLE_MANAGER_SHADOW_ENABLED", "false").strip().lower() != "true":
            return
        if not isinstance(payload, dict):
            return
        record_active_if_execution_grade(self._shadow_active_directions, payload)
        event = shadow_preview_event(self._shadow_active_directions, payload)
        if event is None:
            return
        import json as _json  # noqa: PLC0415
        import logging as _logging  # noqa: PLC0415

        _logging.getLogger("signal_json").warning(
            "%s %s",
            "[SignalLifecycleShadowPreview]",
            _json.dumps(event, separators=(",", ":"), ensure_ascii=False),
        )

    def _emit_microboost_watch_shadow(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        source_verdict: Any | None,
    ) -> None:
        """Emit microboost WATCH logs for observability when verdict is not EXECUTE.

        Side-effect-only logging that decouples ``signal_watch_json`` visibility
        from the execution verdict. It deliberately:
          * works on a throwaway copy of ``l12_verdict`` (never mutates the live
            execution verdict);
          * never touches the signal-block finalizer / lifecycle state;
          * emits ONLY pure ``*_WATCH`` candidates, never execution-grade finals,
        so watch visibility is restored without opening any execution path.

        Disable with ``SIGNAL_WATCH_SHADOW_ENABLED=false``.
        """
        if os.getenv("SIGNAL_WATCH_SHADOW_ENABLED", "true").strip().lower() != "true":
            return
        shadow_verdict = dict(l12_verdict)
        market_contexts = self._signal_throttle_market_contexts(
            symbol=symbol,
            synthesis=synthesis,
            l12_verdict=shadow_verdict,
            source_verdict=source_verdict,
        )
        report = self._signal_throttle_live_analyzer.snapshot(market_contexts=market_contexts)
        report["htf_structure_contexts"] = self._htf_structure_contexts_from_market_contexts(market_contexts)
        self._emit_htf_structure_snapshots_for_contexts(market_contexts)
        self._emit_microboost_intel_if_new(report)
        self._emit_microboost_watch_miss_diagnostic(report)
        self._emit_htf_structure_snapshot(symbol)
        self._apply_allowed_quorum_decision_update(
            symbol=symbol,
            synthesis=synthesis,
            l12_verdict=shadow_verdict,
            report=report,
            market_contexts=market_contexts,
            source_verdict=source_verdict,
        )
        self._apply_no_trade_pressure_decision_update(
            symbol=symbol,
            l12_verdict=shadow_verdict,
            report=report,
            market_contexts=market_contexts,
        )
        if "allowed_quorum_pressure_state" in shadow_verdict:
            l12_verdict["allowed_quorum_pressure_state"] = shadow_verdict["allowed_quorum_pressure_state"]
        if "no_trade_pressure_decision_update" in shadow_verdict:
            l12_verdict["no_trade_pressure_decision_update"] = shadow_verdict["no_trade_pressure_decision_update"]
        if "no_trade_pressure_state" in shadow_verdict:
            l12_verdict["no_trade_pressure_state"] = shadow_verdict["no_trade_pressure_state"]
        for key in ("microboost_continuation_entry", "microboost_counter_entry", "microboost_watch_entry"):
            candidate = report.get(key)
            if not isinstance(candidate, dict):
                continue
            status = str(candidate.get("status") or "")
            if status == "NONE" or not status.endswith("_WATCH"):
                continue
            shadow_candidate = dict(candidate)
            shadow_candidate["shadow_only"] = True
            shadow_candidate["lifecycle_status"] = "SHADOW_WATCH_ACTIVE"
            shadow_candidate["terminal_required"] = False
            shadow_candidate["terminal_guarantee"] = "OBSERVABILITY_ONLY"
            self._prepare_lifecycle_tracking_metadata(shadow_candidate)
            self._emit_signal_json_payload(shadow_candidate)

    def _finalize_idle_signal_blocks(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> None:
        if not self._signal_block_finalizer.pending_symbols():
            return
        current_contexts = self._signal_throttle_market_contexts(
            symbol=symbol,
            synthesis=synthesis,
            l12_verdict=l12_verdict,
            source_verdict=l12_verdict.get("verdict"),
        )
        report = self._signal_throttle_live_analyzer.snapshot(market_contexts=current_contexts)
        self._apply_signal_block_finalizer(
            l12_verdict=l12_verdict,
            report=report,
            market_contexts=current_contexts,
        )

    def _emit_microboost_intel_if_new(self, report: dict[str, Any]) -> None:
        event = build_microboost_intel_event(report)
        if event is not None and self._microboost_source_guard_blocks(report):
            return
        if event is not None:
            key = event.dedupe_key()
            role_change_only = self._parse_env_bool(
                "MICROBOOST_INTEL_EMIT_ON_ROLE_CHANGE_ONLY",
                self._signal_log_compact_mode_enabled(),
            )
            role_key = (
                event.symbol,
                event.microboost_role,
                event.microboost_followthrough_bias,
                event.action,
                event.price_position,
                event.room_to_move_status,
            )
            role_store = getattr(self, "_last_microboost_role_key_by_symbol", None)
            if not isinstance(role_store, dict):
                role_store = {}
                self._last_microboost_role_key_by_symbol = role_store
            can_emit_role = not role_change_only or role_store.get(event.symbol) != role_key
            if can_emit_role and key != self._last_microboost_log_key:
                self._last_microboost_log_key = key
                role_store[event.symbol] = role_key
                emit_microboost_intel(event)
        table_interval = self._parse_env_float_allow_zero(
            "MICROBOOST_TABLE_RATE_LIMIT_SECONDS",
            120.0 if self._signal_log_compact_mode_enabled() else 0.0,
        )
        now = time.time()
        last_table_at = getattr(self, "_last_microboost_table_emit_at", None)
        table_allowed = not (
            table_interval > 0.0
            and isinstance(last_table_at, (int, float))
            and now - float(last_table_at) < table_interval
        )
        emitted_table = False
        for table_event in build_microboost_table_events(report):
            if not table_allowed:
                break
            table_key = table_event.dedupe_key()
            table_keys = getattr(self, "_emitted_microboost_table_keys", None)
            if not isinstance(table_keys, set):
                table_keys = set()
                self._emitted_microboost_table_keys = table_keys
            if table_key in table_keys:
                continue
            table_keys.add(table_key)
            emit_microboost_table_event(table_event)
            emitted_table = True
        if emitted_table:
            self._last_microboost_table_emit_at = now

    def _microboost_source_guard_blocks(self, report: dict[str, Any]) -> bool:
        if os.getenv("MICROBOOST_SOURCE_GUARD_ENABLED", "true").strip().lower() != "true":
            return False
        guard = guard_microboost_source(
            report,
            max_age_seconds=self._source_lineage_max_age_seconds(),
        )
        if guard.can_emit_microboost:
            return False

        diagnostics: list[dict[str, Any]] = []
        for diagnostic in guard.diagnostics:
            diag = dict(diagnostic)
            diag["diagnostic_emit_result"] = self._emit_source_guard_diagnostic(diag)
            diagnostics.append(diag)
        report["microboost_source_diagnostics"] = diagnostics
        return True

    def _emit_source_guard_diagnostic(self, payload: dict[str, Any]) -> bool:
        event = str(payload.get("event") or "")
        prefix = {
            "signal_throttle_freshness_diagnostic": os.getenv(
                "SIGNAL_THROTTLE_FRESHNESS_DIAGNOSTIC_LOG_PREFIX",
                DEFAULT_SIGNAL_THROTTLE_FRESHNESS_PREFIX,
            ),
            "microboost_source_diagnostic": os.getenv(
                "MICROBOOST_SOURCE_DIAGNOSTIC_LOG_PREFIX",
                DEFAULT_MICROBOOST_SOURCE_DIAGNOSTIC_PREFIX,
            ),
            "microboost_stale_diagnostic": os.getenv(
                "MICROBOOST_STALE_DIAGNOSTIC_LOG_PREFIX",
                DEFAULT_MICROBOOST_STALE_DIAGNOSTIC_PREFIX,
            ),
        }.get(event, diagnostic_prefix(event))
        return emit_source_guard_diagnostic(payload, prefix=prefix)

    def _emit_signal_throttle_state_snapshot(self, report: dict[str, Any]) -> None:
        if os.getenv("SIGNAL_THROTTLE_STATE_SNAPSHOT_ENABLED", "true").strip().lower() != "true":
            return
        interval = self._parse_env_float("SIGNAL_THROTTLE_STATE_SNAPSHOT_INTERVAL_SECONDS", 60.0)
        now = time.time()
        last_seen = getattr(self, "_last_signal_throttle_state_snapshot_at", None)
        if isinstance(last_seen, (int, float)) and now - float(last_seen) < max(0.0, interval):
            return
        self._last_signal_throttle_state_snapshot_at = now
        payload = signal_throttle_state_snapshot_payload(
            report,
            max_age_seconds=self._source_lineage_max_age_seconds(),
        )
        report["signal_throttle_state_snapshot"] = payload
        emit_signal_throttle_state_snapshot(
            payload,
            prefix=os.getenv(
                "SIGNAL_THROTTLE_STATE_SNAPSHOT_LOG_PREFIX",
                DEFAULT_SIGNAL_THROTTLE_STATE_SNAPSHOT_PREFIX,
            ),
        )

    def _emit_signal_throttle_fusion_v3_diagnostic(self, report: dict[str, Any]) -> None:
        if os.getenv("SIGNAL_THROTTLE_FUSION_DIAGNOSTIC_ENABLED", "true").strip().lower() != "true":
            return
        payload = report.get("signal_throttle_fusion_v3")
        if not isinstance(payload, dict):
            return
        interval = self._parse_env_float("SIGNAL_THROTTLE_FUSION_DIAGNOSTIC_INTERVAL_SECONDS", 60.0)
        now = time.time()
        import json  # noqa: PLC0415 -- local: diagnostic-only log state key

        state_key = json.dumps(
            {
                "symbol": payload.get("symbol"),
                "block_id": payload.get("block_id"),
                "status": payload.get("status"),
                "direction_status": payload.get("direction_status"),
                "market_structure_status": payload.get("market_structure_status"),
                "next_stage": payload.get("next_stage"),
                "pure_pressure_score": payload.get("pure_pressure_score"),
                "heat_score": payload.get("heat_score"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        previous_key = getattr(self, "_last_signal_throttle_fusion_v3_key", None)
        previous_at = getattr(self, "_last_signal_throttle_fusion_v3_at", None)
        if isinstance(previous_at, (int, float)) and now - float(previous_at) < max(0.0, interval):
            report["signal_throttle_fusion_v3_emit_result"] = False
            report["signal_throttle_fusion_v3_emit_suppressed_reason"] = (
                "UNCHANGED_WITHIN_INTERVAL" if state_key == previous_key else "RATE_LIMITED_WITHIN_INTERVAL"
            )
            return
        self._last_signal_throttle_fusion_v3_key = state_key
        self._last_signal_throttle_fusion_v3_at = now
        report["signal_throttle_fusion_v3_emit_result"] = emit_signal_throttle_fusion_v3_diagnostic(payload)

    def _emit_signal_throttle_pressure_tier_snapshot(self, report: dict[str, Any]) -> None:
        if os.getenv("SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_LOG_ENABLED", "true").strip().lower() != "true":
            return
        max_symbols_per_tier = int(
            self._parse_env_float("SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_MAX_SYMBOLS_PER_TIER", 12.0)
        )
        payload = pressure_tier_snapshot_log_payload(
            report.get("pressure_tier_snapshot"),
            max_symbols_per_tier=max_symbols_per_tier,
        )
        if payload is None:
            return
        interval = self._parse_env_float_allow_zero(
            "PRESSURE_TIER_SNAPSHOT_INTERVAL_SECONDS",
            self._parse_env_float("SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_INTERVAL_SECONDS", 60.0),
        )
        now = time.time()
        import json  # noqa: PLC0415 -- local: diagnostic-only log serialization
        import logging  # noqa: PLC0415 -- local: diagnostic-only logger

        def _tier_state(rows: Any) -> list[dict[str, Any]]:
            if not isinstance(rows, list):
                return []
            return [
                {
                    "symbol": item.get("symbol"),
                    "effective_pressure_tier": item.get("effective_pressure_tier"),
                    "dominant_direction": item.get("dominant_direction"),
                    "tier_action": item.get("tier_action"),
                }
                for item in rows
                if isinstance(item, dict)
            ]

        state_key = json.dumps(
            {
                "tier_1": _tier_state(payload.get("tier_1")),
                "tier_2": _tier_state(payload.get("tier_2")),
                "tier_3_hidden_count": payload.get("tier_3_hidden_count"),
                "stale_archive_count": payload.get("stale_archive_count"),
                "unsafe_mixed_deployment_count": payload.get("unsafe_mixed_deployment_count"),
                "mixed_deployment": payload.get("mixed_deployment"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        previous_key = getattr(self, "_last_signal_throttle_pressure_tier_snapshot_key", None)
        previous_at = getattr(self, "_last_signal_throttle_pressure_tier_snapshot_at", None)
        if isinstance(previous_at, (int, float)) and now - float(previous_at) < max(0.0, interval):
            report["pressure_tier_snapshot_emit_result"] = False
            report["pressure_tier_snapshot_emit_suppressed_reason"] = (
                "UNCHANGED_WITHIN_INTERVAL" if state_key == previous_key else "RATE_LIMITED_WITHIN_INTERVAL"
            )
            return
        self._last_signal_throttle_pressure_tier_snapshot_key = state_key
        self._last_signal_throttle_pressure_tier_snapshot_at = now
        logging.getLogger(
            os.getenv("SIGNAL_THROTTLE_OBSERVABILITY_LOGGER", DEFAULT_SIGNAL_THROTTLE_OBSERVABILITY_LOGGER)
        ).warning(
            "%s %s",
            os.getenv(
                "SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_LOG_PREFIX",
                "[SignalThrottlePressureTierSnapshot]",
            ),
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )
        report["pressure_tier_snapshot_emit_result"] = True

    def _emit_signal_throttle_followthrough_scores(self, report: dict[str, Any]) -> None:
        if os.getenv("SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_LOG_ENABLED", "true").strip().lower() != "true":
            return
        max_symbols = int(self._parse_env_float("SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_MAX_SYMBOLS", 8.0))
        payload = signal_throttle_followthrough_score_log_payload(
            report.get("followthrough_scores"),
            max_symbols=max_symbols,
        )
        if payload is None:
            report["followthrough_score_emit_result"] = False
            report["followthrough_score_emit_suppressed_reason"] = "NO_FOLLOWTHROUGH_SCORES"
            return
        interval = self._parse_env_float("SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_INTERVAL_SECONDS", 60.0)
        now = time.time()
        import json  # noqa: PLC0415 -- local: diagnostic-only log serialization
        import logging  # noqa: PLC0415 -- local: diagnostic-only logger

        state_key = json.dumps(
            {
                "scores": [
                    {
                        "symbol": item.get("symbol"),
                        "direction": item.get("direction"),
                        "followthrough_score": item.get("followthrough_score"),
                        "followthrough_bucket": item.get("followthrough_bucket"),
                        "microboost_role": item.get("microboost_role"),
                        "gap_health": item.get("gap_health"),
                    }
                    for item in payload.get("scores") or []
                    if isinstance(item, dict)
                ],
                "score_count": payload.get("score_count"),
                "late_risk_count": payload.get("late_risk_count"),
                "gap_degraded_count": payload.get("gap_degraded_count"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        previous_key = getattr(self, "_last_signal_throttle_followthrough_score_key", None)
        previous_at = getattr(self, "_last_signal_throttle_followthrough_score_at", None)
        if isinstance(previous_at, (int, float)) and now - float(previous_at) < max(0.0, interval):
            report["followthrough_score_emit_result"] = False
            report["followthrough_score_emit_suppressed_reason"] = (
                "UNCHANGED_WITHIN_INTERVAL" if state_key == previous_key else "RATE_LIMITED_WITHIN_INTERVAL"
            )
            return
        self._last_signal_throttle_followthrough_score_key = state_key
        self._last_signal_throttle_followthrough_score_at = now
        logging.getLogger(
            os.getenv("SIGNAL_THROTTLE_OBSERVABILITY_LOGGER", DEFAULT_SIGNAL_THROTTLE_OBSERVABILITY_LOGGER)
        ).warning(
            "%s %s",
            os.getenv(
                "SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_LOG_PREFIX",
                "[SignalThrottleFollowthroughScore]",
            ),
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )
        report["followthrough_score_emit_result"] = True

    def _source_lineage_max_age_seconds(self) -> float:
        return self._parse_env_float("SIGNAL_THROTTLE_SOURCE_MAX_AGE_SECONDS", DEFAULT_SOURCE_FRESHNESS_SECONDS)

    def _emit_signal_intelligence_flag_snapshot(self) -> None:
        """P1 (once per deployment, default ON): emit the effective state of the
        signal-intelligence / canary flags + deployment identity so a log capture can
        distinguish "flag OFF" from "logic active but failing". Pure observability --
        never touches execution. Gated by ``SIGNAL_INTELLIGENCE_FLAG_SNAPSHOT_ENABLED``.
        """
        if os.getenv("SIGNAL_INTELLIGENCE_FLAG_SNAPSHOT_ENABLED", "true").strip().lower() != "true":
            return

        def _b(name: str, default: str) -> bool:
            return os.getenv(name, default).strip().lower() == "true"

        def _f(name: str, default: str) -> float:
            try:
                return float(os.getenv(name, default))
            except (TypeError, ValueError):
                return float(default)

        import json  # noqa: PLC0415 -- local: stdlib json is not a module-level import here
        import logging  # noqa: PLC0415 -- local: `logging` is only used on this diagnostic path

        payload = {
            "event": "signal_intelligence_flag_snapshot",
            "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID") or os.getenv("DEPLOYMENT_ID") or "unknown",
            "commit_sha": (
                os.getenv("RAILWAY_GIT_COMMIT_SHA")
                or os.getenv("GIT_COMMIT_SHA")
                or os.getenv("COMMIT_SHA")
                or "unknown"
            ),
            "SIGNAL_LOG_COMPACT_MODE_ENABLED": _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true"),
            "SIGNAL_WATCH_EMIT_ON_CHANGE_ONLY": _b(
                "SIGNAL_WATCH_EMIT_ON_CHANGE_ONLY",
                "true" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "false",
            ),
            "SIGNAL_WATCH_BUCKET_EMIT_MINUTES": os.getenv("SIGNAL_WATCH_BUCKET_EMIT_MINUTES", "5,10,15,20,30"),
            "SIGNAL_WATCH_SUPPRESS_IDENTICAL": _b(
                "SIGNAL_WATCH_SUPPRESS_IDENTICAL",
                "true" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "false",
            ),
            "SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED": _b(
                "SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED",
                "true" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "false",
            ),
            "SIGNAL_PRESSURE_STATE_RATE_LIMIT_SECONDS": _f(
                "SIGNAL_PRESSURE_STATE_RATE_LIMIT_SECONDS",
                "60" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "0",
            ),
            "SIGNAL_THROTTLE_RAW_SAMPLE_SECONDS": _f(
                "SIGNAL_THROTTLE_RAW_SAMPLE_SECONDS",
                "60" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "0",
            ),
            "MICROBOOST_INTEL_EMIT_ON_ROLE_CHANGE_ONLY": _b(
                "MICROBOOST_INTEL_EMIT_ON_ROLE_CHANGE_ONLY",
                "true" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "false",
            ),
            "MICROBOOST_TABLE_RATE_LIMIT_SECONDS": _f(
                "MICROBOOST_TABLE_RATE_LIMIT_SECONDS",
                "120" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "0",
            ),
            "PRESSURE_TIER_SNAPSHOT_INTERVAL_SECONDS": _f(
                "PRESSURE_TIER_SNAPSHOT_INTERVAL_SECONDS",
                os.getenv("SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_INTERVAL_SECONDS", "60"),
            ),
            "SIGNAL_THROTTLE_TIER1_VISIBLE_MAX_SYMBOLS": _f(
                "SIGNAL_THROTTLE_TIER1_VISIBLE_MAX_SYMBOLS",
                "5",
            ),
            "HTF_STRUCTURE_SNAPSHOT_EMIT_ON_CHANGE_ONLY": _b(
                "HTF_STRUCTURE_SNAPSHOT_EMIT_ON_CHANGE_ONLY",
                "true" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "false",
            ),
            "HTF_STRUCTURE_SNAPSHOT_INTERVAL_SECONDS": _f(
                "HTF_STRUCTURE_SNAPSHOT_INTERVAL_SECONDS",
                "60" if _b("SIGNAL_LOG_COMPACT_MODE_ENABLED", "true") else "0",
            ),
            "SIGNAL_JSON_VERBOSE_OBSERVABILITY": _b("SIGNAL_JSON_VERBOSE_OBSERVABILITY", "false"),
            "SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY": _b("SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY", "true"),
            "SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS": _b(
                "SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "false"
            ),
            "SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED": _b(
                "SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_ENABLED", "false"
            ),
            "SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS": _f(
                "SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", "600"
            ),
            "SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED": _b(
                "SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED", "true"
            ),
            "SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS": _f(
                "SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS", "4"
            ),
            "SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_LOG_ENABLED": _b(
                "SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_LOG_ENABLED", "true"
            ),
            "SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_MAX_SYMBOLS": _f(
                "SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_MAX_SYMBOLS", "8"
            ),
            "SIGNAL_WATCH_FOLLOWTHROUGH_CONTEXT_ENABLED": _b(
                "SIGNAL_WATCH_FOLLOWTHROUGH_CONTEXT_ENABLED", "true"
            ),
            "SIGNAL_WATCH_PAIR_MEMORY_ENABLED": _b("SIGNAL_WATCH_PAIR_MEMORY_ENABLED", "true"),
            "SIGNAL_WATCH_PHASE_STRUCTURE_VALIDATION_ENABLED": _b(
                "SIGNAL_WATCH_PHASE_STRUCTURE_VALIDATION_ENABLED",
                "true",
            ),
            "PAIR_MEMORY_LOOKBACK_MINUTES": _f("PAIR_MEMORY_LOOKBACK_MINUTES", "720"),
            "PAIR_MEMORY_EXECUTION_IMPACT": _b("PAIR_MEMORY_EXECUTION_IMPACT", "false"),
            "HTF_STRUCTURE_CONTEXT_ENABLED": _b("HTF_STRUCTURE_CONTEXT_ENABLED", "true"),
            "HTF_STRUCTURE_SNAPSHOT_ENABLED": _b("HTF_STRUCTURE_SNAPSHOT_ENABLED", "true"),
            "HTF_DAILY_PHASE_FEED_ENABLED": _b("HTF_DAILY_PHASE_FEED_ENABLED", "true"),
            "MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED": _b(
                "MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED", "false"
            ),
            "MICROBOOST_WATCH_MISS_DIAGNOSTIC_ENABLED": _b("MICROBOOST_WATCH_MISS_DIAGNOSTIC_ENABLED", "false"),
            "MICROBOOST_SHADOW_DIAGNOSTIC_ENABLED": _b("MICROBOOST_SHADOW_DIAGNOSTIC_ENABLED", "false"),
            "SIGNAL_FAMILY_LINEAGE_ENABLED": _b("SIGNAL_FAMILY_LINEAGE_ENABLED", "false"),
            "SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED": _b(
                "SIGNAL_THROTTLE_ALLOWED_QUORUM_CONTEXTLESS_DIAGNOSTIC_ENABLED", "false"
            ),
            "SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED": _b(
                "SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED", "false"
            ),
            "SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED": _b("SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED", "false"),
            "SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK": _b(
                "SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK", "false"
            ),
            "SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED": _b(
                "SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true"
            ),
            "MICROBOOST_SOURCE_GUARD_ENABLED": _b("MICROBOOST_SOURCE_GUARD_ENABLED", "true"),
            "SIGNAL_WATCH_SOURCE_GUARD_ENABLED": _b("SIGNAL_WATCH_SOURCE_GUARD_ENABLED", "true"),
            "SIGNAL_THROTTLE_STATE_SNAPSHOT_ENABLED": _b("SIGNAL_THROTTLE_STATE_SNAPSHOT_ENABLED", "true"),
            "SIGNAL_THROTTLE_SOURCE_MAX_AGE_SECONDS": _f("SIGNAL_THROTTLE_SOURCE_MAX_AGE_SECONDS", "300"),
            "STRUCTURE_LADDER_DIAGNOSTIC_ENABLED": _b("STRUCTURE_LADDER_DIAGNOSTIC_ENABLED", "false"),
            "SIGNAL_JSON_LOG_ENABLED": _b("SIGNAL_JSON_LOG_ENABLED", "true"),
            "SIGNAL_JSON_EMIT_WATCH": _b("SIGNAL_JSON_EMIT_WATCH", "true"),
            "SIGNAL_JSON_EMIT_CONDITIONAL": _b("SIGNAL_JSON_EMIT_CONDITIONAL", "true"),
            "SIGNAL_JSON_EMIT_VALID": _b("SIGNAL_JSON_EMIT_VALID", "true"),
            "SIGNAL_JSON_STRICT_LIFECYCLE": _b("SIGNAL_JSON_STRICT_LIFECYCLE", "true"),
            "SIGNAL_JSON_EXEC_GATES_ENABLED": _b(
                "SIGNAL_JSON_EXEC_GATES_ENABLED",
                "true" if _b("SIGNAL_JSON_FINAL_BARRIER_ENABLED", "true") else "false",
            ),
            "SIGNAL_JSON_EXEC_GATES_ENFORCE": _b("SIGNAL_JSON_EXEC_GATES_ENFORCE", "true"),
            "SIGNAL_JSON_FINAL_BARRIER_ENABLED": _b("SIGNAL_JSON_FINAL_BARRIER_ENABLED", "true"),
            "SIGNAL_JSON_REQUIRE_TERMINAL_DECISION_UPDATE": _b(
                "SIGNAL_JSON_REQUIRE_TERMINAL_DECISION_UPDATE", "true"
            ),
            "SIGNAL_DECISION_SOURCE_GUARD_ENABLED": _b("SIGNAL_DECISION_SOURCE_GUARD_ENABLED", "true"),
            "SIGNAL_PRESSURE_STATE_JSON_ENABLED": _b("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "true"),
            "SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED": _b(
                "SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED", "true"
            ),
            "SIGNAL_DECISION_REQUIRE_LIFECYCLE_ANCHOR": _b("SIGNAL_DECISION_REQUIRE_LIFECYCLE_ANCHOR", "true"),
        }
        logging.getLogger("signal_json").warning(
            "%s %s",
            "[SignalIntelligenceFlagSnapshot]",
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )

    def _emit_microboost_watch_miss_diagnostic(self, report: dict[str, Any]) -> None:
        """Patch 1/2 (flag-guarded, default OFF): explain why the latest microboost block
        did NOT become a watch, so a no-watch deployment is not silent. Diagnostic-only --
        always ``valid_for_execution=false`` / ``is_final_signal=false``, never a SignalJSON.

        Patch 1 ``MICROBOOST_WATCH_MISS_DIAGNOSTIC_ENABLED`` -> microboost_watch_candidate_diagnostic.
        Patch 2 ``MICROBOOST_SHADOW_DIAGNOSTIC_ENABLED`` -> microboost_shadow_watch_diagnostic
        (only when the block would qualify under the looser shadow thresholds).
        Per-symbol dedup suppresses unchanged per-tick repeats.
        """
        diag = report.get("microboost_watch_miss_diagnostic")
        if not isinstance(diag, dict):
            return
        patch1 = os.getenv("MICROBOOST_WATCH_MISS_DIAGNOSTIC_ENABLED", "false").strip().lower() == "true"
        patch2 = os.getenv("MICROBOOST_SHADOW_DIAGNOSTIC_ENABLED", "false").strip().lower() == "true"
        if not patch1 and not patch2:
            return
        symbol = str(diag.get("symbol") or "")
        if not symbol:
            return
        blocked_by = list(diag.get("blocked_by") or [])
        shadow_candidate = bool(diag.get("shadow_watch_candidate"))
        store = getattr(self, "_last_watch_miss_diag_key", None)
        if not isinstance(store, dict):
            store = {}
            self._last_watch_miss_diag_key = store
        key = f"{symbol}|{'/'.join(blocked_by)}|sc={shadow_candidate}|p1={patch1}|p2={patch2}"
        if store.get(symbol) == key:
            return
        store[symbol] = key
        import json  # noqa: PLC0415 -- local: stdlib json is not a module-level import here
        import logging  # noqa: PLC0415 -- local: `logging` is only imported on the loguru-absent path

        logger = logging.getLogger("signal_json")
        # Direction-truthfulness (flag-guarded ``MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED``,
        # default OFF, observability-only). A sub-threshold microboost block can carry no
        # direction even when the SAME symbol's allowed-quorum context already resolved one
        # (the gap behind raw_direction=null while the DecisionUpdate lane shows BUY/SELL).
        # Surface that context here using the very ``allowed_quorum.direction`` the decision
        # lane already trusts -- symbol-matched, so another pair's direction is never stamped.
        # Payload-only: never changes the block, eligibility, the watch path, or execution.
        recovery_on = (
            os.getenv("MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED", "false").strip().lower() == "true"
        )
        raw_direction = diag.get("raw_direction")
        direction_recovery_source = None
        if recovery_on:
            direction_recovery_source = "BLOCK_DIRECT" if raw_direction in {"BUY", "SELL"} else None
            if raw_direction not in {"BUY", "SELL"}:
                quorum = report.get("allowed_quorum")
                if isinstance(quorum, dict) and str(quorum.get("symbol") or "").upper() == symbol.upper():
                    quorum_direction = str(quorum.get("direction") or "").upper()
                    if quorum_direction in {"BUY", "SELL"}:
                        raw_direction = quorum_direction
                        direction_recovery_source = "ALLOWED_QUORUM_REPORT"
        if patch1:
            payload = {
                "event": "microboost_watch_candidate_diagnostic",
                "symbol": symbol,
                "raw_direction": raw_direction,
                "effective_ticks": diag.get("effective_ticks"),
                "effective_density": diag.get("effective_density"),
                "duration_seconds": diag.get("duration_seconds"),
                "threshold_ticks": diag.get("threshold_ticks"),
                "threshold_density": diag.get("threshold_density"),
                "threshold_duration_seconds": diag.get("threshold_duration_seconds"),
                "eligible_for_watch": False,
                "blocked_by": blocked_by,
                "valid_for_execution": False,
                "is_final_signal": False,
            }
            if recovery_on:
                payload["direction_recovery_source"] = direction_recovery_source
            logger.warning(
                "%s %s",
                "[MicroboostWatchDiagnostic]",
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            )
        if patch2 and shadow_candidate:
            payload = {
                "event": "microboost_shadow_watch_diagnostic",
                "symbol": symbol,
                "raw_direction": raw_direction,
                "shadow_watch_candidate": True,
                "official_watch_candidate": False,
                "shadow_thresholds": diag.get("shadow_thresholds"),
                "reason": "below_official_threshold",
                "would_have_been_watch_under_shadow_threshold": True,
                "valid_for_execution": False,
                "is_final_signal": False,
            }
            if recovery_on:
                payload["direction_recovery_source"] = direction_recovery_source
            logger.warning(
                "%s %s",
                "[MicroboostShadowDiagnostic]",
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            )

    def _emit_htf_structure_snapshot(self, symbol: str) -> None:
        """Increment H1 (flag-guarded, default OFF): emit a non-executable HTF
        structure snapshot for an active symbol.

        Answers "where is price on Daily/H4 right now?" so a later increment can
        interpret microboost pressure against structure (BUY pressure at an HTF
        supply/resistance is absorption/no-chase, never an auto BUY LIMIT). This
        is observability-only -- ``valid_for_execution`` is always ``False`` and
        nothing here is a SignalJSON. Disable with
        ``HTF_STRUCTURE_SNAPSHOT_ENABLED=false``.

        Per-symbol dedup suppresses unchanged structure repeats. Any failure is
        swallowed: a snapshot must never disturb the execution path.
        """
        if os.getenv("HTF_STRUCTURE_SNAPSHOT_ENABLED", "true").strip().lower() != "true":
            return
        try:
            snapshot = self._htf_snapshot_resolver.resolve(symbol)
            key = snapshot.dedupe_key()
            emit_on_change_only = self._parse_env_bool(
                "HTF_STRUCTURE_SNAPSHOT_EMIT_ON_CHANGE_ONLY",
                self._signal_log_compact_mode_enabled(),
            )
            last_keys = getattr(self, "_last_htf_snapshot_key", None)
            if not isinstance(last_keys, dict):
                last_keys = {}
                self._last_htf_snapshot_key = last_keys
            if emit_on_change_only and last_keys.get(snapshot.symbol) == key:
                return
            interval = self._parse_env_float_allow_zero(
                "HTF_STRUCTURE_SNAPSHOT_INTERVAL_SECONDS",
                60.0 if self._signal_log_compact_mode_enabled() else 0.0,
            )
            last_at = getattr(self, "_last_htf_snapshot_emit_at", None)
            if not isinstance(last_at, dict):
                last_at = {}
                self._last_htf_snapshot_emit_at = last_at
            now = time.time()
            if interval > 0.0 and last_keys.get(snapshot.symbol) == key:
                previous_at = last_at.get(snapshot.symbol)
                if isinstance(previous_at, (int, float)) and now - float(previous_at) < interval:
                    return
            if not emit_on_change_only and interval > 0.0:
                previous_at = last_at.get(snapshot.symbol)
                if isinstance(previous_at, (int, float)) and now - float(previous_at) < interval:
                    return
            last_keys[snapshot.symbol] = key
            last_at[snapshot.symbol] = now
            emit_htf_structure_snapshot(snapshot, enabled=True)
        except Exception as exc:  # pragma: no cover - defensive; observability must not break
            logger.debug("[HTFStructureSnapshot] resolve/emit skipped for {}: {}", symbol, exc)

    def _apply_effective_verdict_controls(
        self,
        *,
        symbol: str,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        legacy_verdict: Any,
        safe_mode: bool,
        errors: list[str],
    ) -> None:
        final_verdict = l12_verdict.get("verdict", "")
        if final_verdict.startswith("EXECUTE") and not safe_mode:
            self._apply_market_context_guard(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                errors=errors,
            )
            final_verdict = l12_verdict.get("verdict", "")

        v11_overlay_dict: dict[str, Any] | None = None
        if final_verdict.startswith("EXECUTE") and not safe_mode:
            count_before = self._signal_throttle.get_count(symbol)
            remaining_before = self._signal_throttle.get_remaining(symbol)
            if self._signal_throttle.is_throttled(symbol):
                l12_verdict["verdict"] = "HOLD"
                l12_verdict["throttled_from"] = final_verdict
                l12_verdict["signal_throttle"] = {
                    "status": "throttled",
                    "count": count_before,
                    "remaining": remaining_before,
                    "window_seconds": self._signal_throttle.window_seconds,
                    "max_signals": self._signal_throttle.max_signals,
                }
                errors.append("SIGNAL_THROTTLED")
                SIGNAL_THROTTLED.labels(symbol=symbol).inc()
                self._signal_throttle_live_analyzer.record_throttled(
                    symbol=symbol,
                    verdict=final_verdict,
                    count=count_before,
                    remaining=remaining_before,
                    max_signals=self._signal_throttle.max_signals,
                    window_seconds=self._signal_throttle.window_seconds,
                )
                self._process_signal_throttle_snapshot(
                    symbol=symbol,
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    source_verdict=final_verdict,
                )
            else:
                self._signal_throttle.record(symbol)
                self._signal_throttle.emit_allowed(symbol, final_verdict)
                self._signal_throttle_live_analyzer.record_allowed(symbol=symbol, verdict=final_verdict)
                allowed_streak = self._signal_throttle.record_allowed_streak(symbol, final_verdict)
                count_after = self._signal_throttle.get_count(symbol)
                remaining_after = self._signal_throttle.get_remaining(symbol)
                throttle_intel = classify_allowed_signal(
                    symbol=symbol,
                    verdict=final_verdict,
                    l12_direction=l12_verdict.get("direction"),
                    synthesis=synthesis,
                    count=count_after,
                    remaining=remaining_after,
                    max_signals=self._signal_throttle.max_signals,
                    window_seconds=self._signal_throttle.window_seconds,
                    allowed_streak=allowed_streak,
                    count_before=count_before,
                    remaining_before=remaining_before,
                    verdict_source="POST_L12_PRE_V11",
                )
                l12_verdict["signal_throttle_intel"] = throttle_intel.to_dict()
                self._cache_signal_throttle_intel_direction(symbol, throttle_intel)
                self._process_signal_throttle_snapshot(
                    symbol=symbol,
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    source_verdict=final_verdict,
                )
                emit_signal_throttle_intel(throttle_intel)
        elif final_verdict.startswith("EXECUTE") and safe_mode:
            self._emit_verdict_stream_event(
                event="signal_throttle_check",
                symbol=symbol,
                authority="SIGNAL_THROTTLE",
                verdict_stream="post_l12_pre_v11",
                verdict=final_verdict,
                direction=l12_verdict.get("direction"),
                extras={
                    "status": "bypassed_safe_mode",
                    "source_verdict": final_verdict,
                    "safe_mode": safe_mode,
                },
            )
            self._finalize_idle_signal_blocks(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
            )
            self._emit_microboost_watch_shadow(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                source_verdict=final_verdict,
            )
        else:
            throttle_skip_reason = "non_execute_verdict"
            if l12_verdict.get("sovereignty_downgrade"):
                throttle_skip_reason = "sovereignty_downgraded_to_hold"
            elif l12_verdict.get("market_context_downgrade"):
                throttle_skip_reason = "market_context_unvalidated"
            self._record_signal_throttle_downgrade_observation(
                symbol=symbol,
                l12_verdict=l12_verdict,
                legacy_verdict=legacy_verdict,
                reason=throttle_skip_reason,
                synthesis=synthesis,
            )
            self._emit_verdict_stream_event(
                event="signal_throttle_check",
                symbol=symbol,
                authority="SIGNAL_THROTTLE",
                verdict_stream="post_l12_pre_v11",
                verdict=final_verdict,
                direction=l12_verdict.get("direction"),
                extras={
                    "status": "skipped",
                    "reason": throttle_skip_reason,
                    "source_verdict": legacy_verdict,
                    "safe_mode": safe_mode,
                    "sovereignty_downgrade": bool(l12_verdict.get("sovereignty_downgrade")),
                    "throttled_from": l12_verdict.get("throttled_from"),
                },
            )
            self._finalize_idle_signal_blocks(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
            )
            self._emit_microboost_watch_shadow(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                source_verdict=final_verdict,
            )

        try:
            from engines.v11 import V11PipelineHook  # noqa: PLC0415

            _v11 = V11PipelineHook()
            v11_input = SimpleNamespace(
                synthesis=synthesis,
                l12_verdict=l12_verdict,
            )
            v11_overlay = _v11.evaluate(
                pipeline_result=v11_input,
                symbol=symbol,
                timeframe="H1",
            )
            v11_overlay_dict = v11_overlay.to_dict() if v11_overlay else None
            if v11_overlay.should_trade is False and l12_verdict["verdict"].startswith("EXECUTE"):
                logger.warning(
                    f"[Pipeline v8.0] {symbol} V11 VETO — verdict {l12_verdict['verdict']} downgraded to HOLD"
                )
                l12_verdict["verdict"] = "HOLD"
                l12_verdict["v11_veto"] = True
                errors.append("V11_VETO")
            synthesis["v11"] = v11_overlay_dict
        except ImportError:
            pass
        except Exception as v11_exc:
            logger.warning(f"[Pipeline v8.0] V11 error for {symbol}: {v11_exc}")
            errors.append(f"V11_ERROR: {v11_exc}")

        final_effective_verdict = l12_verdict.get("verdict")
        effective_reason = "FINAL_STATE_UNCLASSIFIED"
        if l12_verdict.get("market_context_downgrade"):
            effective_reason = "MARKET_CONTEXT_UNVALIDATED"
        elif l12_verdict.get("throttled_from"):
            effective_reason = "SIGNAL_THROTTLED"
        elif l12_verdict.get("v11_veto"):
            effective_reason = "V11_VETO"
        elif final_effective_verdict == "NO_TRADE":
            effective_reason = "PRE_V11_NO_TRADE"
        elif final_effective_verdict == "HOLD":
            effective_reason = "PRE_V11_HOLD"
        elif isinstance(final_effective_verdict, str) and final_effective_verdict.startswith("EXECUTE"):
            effective_reason = "EFFECTIVE_EXECUTE"

        self._emit_verdict_stream_event(
            event="l12_effective_verdict",
            symbol=symbol,
            authority="L12_EFFECTIVE",
            verdict_stream="effective_final",
            verdict=final_effective_verdict,
            direction=l12_verdict.get("direction"),
            extras={
                "confidence": l12_verdict.get("confidence"),
                "proceed": l12_verdict.get("proceed_to_L13"),
                "legacy_verdict": legacy_verdict,
                "effective_reason": effective_reason,
                "throttled_from": l12_verdict.get("throttled_from"),
                "v11_should_trade": None if v11_overlay_dict is None else v11_overlay_dict.get("should_trade"),
                "v11_skipped_reason": None if v11_overlay_dict is None else v11_overlay_dict.get("skipped_reason"),
                "v11_veto": bool(l12_verdict.get("v11_veto", False)),
            },
        )

    # ══════════════════════════════════════════════════════════════
    #  METRICS RECORDING
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _record_metrics(symbol: str, result: dict[str, Any]) -> None:
        """Record Prometheus metrics from a pipeline result.

        Delegates to pipeline.phases.metrics_recorder.record_pipeline_metrics.
        """
        record_pipeline_metrics(symbol, result)

    @staticmethod
    def record_metrics(symbol: str, result: dict[str, Any]) -> None:
        """Public metrics recorder for tests and external callers."""
        record_pipeline_metrics(symbol, result)

    # ══════════════════════════════════════════════════════════════
    #  EARLY EXIT -- pipeline failure fallback
    # ══════════════════════════════════════════════════════════════

    def _early_exit(
        self,
        symbol: str,
        errors: list[str],
        latency_ms: float,
        *,
        layers_executed: list[str] | None = None,
        engines_invoked: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create early-exit result when pipeline fails."""
        empty_gates: dict[str, Any] = {
            "total_passed": 0,
            "total_gates": 9,
            "gate_1_tii": "FAIL",
            "gate_2_montecarlo": "FAIL",
            "gate_3_frpc": "FAIL",
            "gate_4_conf12": "FAIL",
            "gate_5_rr": "FAIL",
            "gate_6_integrity": "FAIL",
            "gate_7_propfirm": "FAIL",
            "gate_8_drawdown": "FAIL",
            "gate_9_latency": "FAIL",
        }

        result: dict[str, Any] = {
            "schema": self.VERSION,
            "pair": symbol,
            "timestamp": datetime.now(_TZ_GMT8).isoformat(),
            "synthesis": {
                "pair": symbol,
                "scores": {
                    "wolf_30_point": 0,
                    "wolf_score": 0,
                    "tii_score": 0.0,
                    "frpc_score": 0.0,
                    "f_score": 0,
                    "t_score": 0,
                    "fta_score": 0.0,
                    "fta_multiplier": 0.0,
                    "exec_score": 0,
                    "psychology_score": 0,
                    "technical_score": 0,
                    "regime": "UNKNOWN",
                    "session": "",
                },
                "layers": {
                    "L1_context_coherence": 0.0,
                    "L2_reflex_coherence": 0.0,
                    "L3_trq3d_energy": 0.0,
                    "L7_monte_carlo_win": 0.0,
                    "L8_tii_sym": 0.0,
                    "L8_integrity_index": 0.0,
                    "L9_dvg_confidence": 0.0,
                    "L9_liquidity_score": 0.0,
                    "conf12": 0.0,
                },
                "execution": {
                    "direction": "HOLD",
                    "entry_price": 0.0,
                    "stop_loss": 0.0,
                    "take_profit_1": 0.0001,
                    "entry_zone": "0.00000-0.00000",
                    "execution_mode": "TP1_ONLY",
                    "battle_strategy": "SHADOW_STRIKE",
                    "rr_ratio": 0.0,
                    "lot_size": 0.0,
                    "risk_percent": 0.0,
                    "risk_amount": 0.0,
                    "slippage_estimate": 0.0,
                    "optimal_timing": "",
                },
                "risk": {
                    "current_drawdown": 0.0,
                    "drawdown_level": "LEVEL_0",
                    "risk_multiplier": 0.0,
                    "risk_status": "CRITICAL",
                    "lrce": 0.0,
                },
                "propfirm": {
                    "compliant": False,
                    "daily_loss_status": "OK",
                    "max_drawdown_status": "OK",
                    "profit_target_progress": 0.0,
                },
                "bias": {"fundamental": "NEUTRAL", "technical": "NEUTRAL", "macro": "UNKNOWN"},
                "cognitive": {"regime": "RANGE", "dominant_force": "NEUTRAL", "cbv": 0.0, "csi": 0.0},
                "fusion_frpc": {"conf12": 0.0, "frpc_energy": 0.0, "lambda_esi": 0.003, "integrity": 0.0},
                "trq3d": {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "drift": 0.0, "mean_energy": 0.0, "intensity": 0.0},
                "smc": {
                    "structure": "RANGE",
                    "smart_money_signal": "NEUTRAL",
                    "liquidity_zone": "0.00000",
                    "ob_present": False,
                    "fvg_present": False,
                    "sweep_detected": False,
                    "bias": "NEUTRAL",
                    "bos_detected": False,
                    "choch_detected": False,
                    "displacement": False,
                    "liquidity_sweep": False,
                    "fib_retracement_hit": False,
                    "volume_profile_poc": 0.0,
                    "vpc_zones": [],
                },
                "wolf_discipline": {
                    "score": 0.0,
                    "polarity_deviation": 0.0,
                    "lambda_balance": "INACTIVE",
                    "bias_symmetry": "NEUTRAL",
                    "eaf_score": 0.0,
                    "emotional_state": "CALM",
                },
                "macro": {
                    "regime": "UNKNOWN",
                    "phase": "NEUTRAL",
                    "volatility_ratio": 1.0,
                    "mn_aligned": False,
                    "liquidity": {},
                    "bias_override": {},
                },
                "system": {"latency_ms": latency_ms, "safe_mode": False},
            },
            "l12_verdict": {
                "verdict": "HOLD",
                "confidence": "LOW",
                "wolf_status": "NO_HUNT",
                "gates": {"passed": 0, "total": 9},
                "gates_v74": empty_gates,
                "proceed_to_L13": False,
            },
            "reflective": None,
            "reflective_pass1": None,
            "reflective_pass2": None,
            "l14_json": None,
            "l15_meta": None,
            "sovereignty": {
                "execution_rights": "REVOKED",
                "lot_multiplier": 0.0,
                "vault_sync": 0.0,
            },
            "enforcement": {
                "execution_rights": "REVOKED",
                "vault_sync": 0.0,
                "drift_ratio": 0.0,
                "verdict_downgraded": False,
                "original_verdict": "HOLD",
                "lot_multiplier": 0.0,
                "meta_integrity": 0.0,
                "pass1_abg": 0.0,
                "pass2_abg": 0.0,
            },
            "latency_ms": latency_ms,
            "errors": errors,
        }
        # Prefer specific blocker codes over generic Lx_HALT prefix
        _blocker_errors = [e for e in errors if "_BLOCKER:" in e]
        _halt_reason = _blocker_errors[0] if _blocker_errors else errors[0] if errors else "UNKNOWN"
        result["execution_map"] = build_execution_map(
            pair=symbol,
            timestamp=result["timestamp"],
            layers_executed=layers_executed or [],
            engines_invoked=engines_invoked or [],
            halt_reason=_halt_reason,
            constitutional_verdict=str(result.get("l12_verdict", {}).get("verdict", "HOLD")),
        )
        self._record_metrics(symbol, result)
        return result
