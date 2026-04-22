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
from types import SimpleNamespace
from typing import Any, cast

from analysis.reflex_emc import EMCFilter
from analysis.reflex_gate import ReflexGateController
from analysis.reflex_multitf import compute_multitf_rqi
from analysis.reflex_rqi import compute_rqi, latency_decay
from config_loader import CONFIG

# third-party imports
# import ...
# local imports
from constitution.l12_router_evaluator import L12Input, L12RouterEvaluator
from constitution.signal_throttle import SignalThrottle
from constitution.verdict_engine import generate_l12_verdict
from contracts.shadow_hook import begin_shadow_session, finalize_shadow_session
from core.dag_engine import DagEngine
from core.metrics import (
    LAYER_LATENCY,
    SIGNAL_THROTTLED,
    TICK_TO_VERDICT_LATENCY,
    VERDICT_PATH_EVENT_TOTAL,
)
from core.tracing import layer_span
from pipeline.engines import L13ReflectiveEngine, L15MetaSovereigntyEngine
from pipeline.execution_map import build_execution_map
from pipeline.phases.assembly import build_l14_json
from pipeline.phases.gates import evaluate_9_gates
from pipeline.phases.metrics_recorder import record_pipeline_metrics
from pipeline.phases.synthesis import build_l12_synthesis
from pipeline.phases.vault import compute_vault_sync
from pipeline.result import PipelineResult
from pipeline.warmup_utils import normalize_warmup  # noqa: E402  # delayed import to avoid circular dependency

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
        "H1": 20,
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

        # Signal rate throttle (max 3 EXECUTE per symbol in 5 minutes)
        self._signal_throttle = SignalThrottle(max_signals=3, window_seconds=300)

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

    @staticmethod
    def _parse_env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        with contextlib.suppress(ValueError, TypeError):
            return max(1.0, float(raw))
        return default

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
            last_ts: float | None = None
            if redis_client is not None:
                with contextlib.suppress(Exception):
                    raw_ts = redis_client.hget(_latest_candle_key(symbol, tf), "last_seen_ts")
                    if raw_ts is not None:
                        last_ts = float(str(raw_ts))
            if last_ts is None and candles:
                last_c = candles[-1]
                last_ts = _coerce_timestamp_to_epoch(
                    last_c.get("timestamp_close")
                    or last_c.get("close_time")
                    or last_c.get("timestamp")
                    or last_c.get("time")
                    or last_c.get("open_time")
                )
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
                from core.redis_keys import latest_tick as _latest_tick_key  # noqa: PLC0415

                raw_feed_ts = redis_client.hget(_latest_tick_key(symbol), "last_seen_ts")
                if raw_feed_ts is not None:
                    feed_age_ts = float(str(raw_feed_ts))
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
            elif layer == "L7" and isinstance(const.get("edge_diagnostics"), dict):
                diagnostics = const["edge_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} edge_status={} win_probability={} required={} simulations={} wf_passed={} gap={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    diagnostics.get("edge_status"),
                    diagnostics.get("win_probability"),
                    diagnostics.get("required_win_probability"),
                    diagnostics.get("simulations"),
                    diagnostics.get("wf_passed"),
                    diagnostics.get("primary_edge_gap"),
                )
            elif layer == "L8" and isinstance(const.get("integrity_diagnostics"), dict):
                diagnostics = const["integrity_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} integrity={} required={} gate_status={} missing_sources={} component_count={} gap={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    diagnostics.get("integrity_score"),
                    diagnostics.get("required_integrity"),
                    diagnostics.get("gate_status"),
                    diagnostics.get("missing_sources"),
                    diagnostics.get("component_count"),
                    diagnostics.get("primary_integrity_gap"),
                )
            elif layer == "L9" and isinstance(const.get("structure_diagnostics"), dict):
                diagnostics = const["structure_diagnostics"]
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={} missing_sources={} builder_state={} available_sources={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
                    diagnostics.get("missing_sources"),
                    diagnostics.get("source_builder_state"),
                    diagnostics.get("available_sources"),
                )
            else:
                logger.warning(
                    "[{}] {} {} constitutional FAIL — blockers={} continuation={}",
                    phase,
                    symbol,
                    layer,
                    blockers,
                    cont,
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
            elif layer == "L7" and isinstance(const.get("edge_diagnostics"), dict):
                diagnostics = const["edge_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} edge_status={} win_probability={} simulations={} gap={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    diagnostics.get("edge_status"),
                    diagnostics.get("win_probability"),
                    diagnostics.get("simulations"),
                    diagnostics.get("primary_edge_gap"),
                )
            elif layer == "L8" and isinstance(const.get("integrity_diagnostics"), dict):
                diagnostics = const["integrity_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} integrity={} gate_status={} missing_sources={} gap={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    diagnostics.get("integrity_score"),
                    diagnostics.get("gate_status"),
                    diagnostics.get("missing_sources"),
                    diagnostics.get("primary_integrity_gap"),
                )
            elif layer == "L9" and isinstance(const.get("structure_diagnostics"), dict):
                diagnostics = const["structure_diagnostics"]
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={} missing_sources={} builder_state={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
                    diagnostics.get("missing_sources"),
                    diagnostics.get("source_builder_state"),
                )
            else:
                logger.info(
                    "[{}] {} {} constitutional WARN — warnings={} band={}",
                    phase,
                    symbol,
                    layer,
                    warns,
                    const.get("coherence_band", "N/A"),
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

        _governance = self._assess_governance(
            symbol,
            redis_client=_redis_client,
            warmup_ready=warmup.get("ready", True),
            dq_penalty=_dq_penalty,
            dq_degraded=len(_degraded_reports) > 0,
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

            # ── Inject upstream output for L7 constitutional governor ─
            # L7 constitutional needs Phase 2 / enrichment continuation
            # state to check upstream legality.
            _l7_upstream: dict[str, Any] = {}
            if l5:
                _l7_upstream = l5
            elif l4:
                _l7_upstream = l4
            l7_engine.set_upstream_output(_l7_upstream)

            # ── L8/L9 upstream injection will happen after L7 completes ─
            # L8 needs L7 output, L9 needs L8 output for constitutional chain.
            # Since Phase 3 runs L7/L8/L9 in parallel, we set Phase 2 output
            # as upstream for L8/L9. Post-hoc chain verification follows.
            _l8_upstream = dict(_l7_upstream)
            if l2:
                _l8_upstream["l2_context"] = l2
            l8_engine.set_upstream_output(_l8_upstream)
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

            # ═══════════════════════════════════════════════════════
            # PHASE 4 -- ZONA EXECUTION & DECISION (L11 -> L6 -> L10)
            # CRITICAL: L11 BEFORE L6 (L6 needs RR from L11)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 4: Execution & Decision -- {symbol}")
            engines_invoked.extend(["L11RRAnalyzer", "L6RiskAnalyzer", "L10PositionAnalyzer", "MonthlyRegimeAnalyzer"])

            trend = l3.get("trend", "NEUTRAL")
            if trend == "BULLISH":
                direction = "BUY"
            elif trend == "BEARISH":
                direction = "SELL"
            else:
                direction = "HOLD"

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
                logger.info(
                    "[Pipeline v8.0] {} direction={} → NO_TRADE (no directional bias from L3)",
                    symbol,
                    direction,
                )
                result = _early_exit_with_map(
                    ["no_directional_bias"],
                    time.time() - start_time,
                )
                result["verdict"] = "NO_TRADE"
                result["verdict_reason"] = f"No directional bias (direction={direction})"
                result["l12_verdict"] = {"verdict": "NO_TRADE", "reason": "no_direction"}
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
                )
                synthesis["constitutional_phase5"] = _const_l12
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

                # Pass 1: Baseline reflective (meta_integrity = 1.0)
                synthesis["_meta_integrity"] = 1.0
                reflective_pass1 = l13_engine.reflect(
                    symbol,
                    [l12_verdict],
                    synthesis,
                )

                # Compute vault sync for sovereignty
                sovereignty = self._compute_vault_sync(synthesis, l12_verdict, reflective_pass1)

                # L15 meta computation (uses Pass 1 + sovereignty)
                l15_meta = l15_engine.compute_meta(
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    reflective_pass1=reflective_pass1,
                    sovereignty=sovereignty,
                    gates=gates,
                )
                layers_executed.append("L14")
                engines_invoked.append("L15MetaSovereigntyEngine")

                # Pass 2: Refined reflective (uses real meta_integrity from L15)
                real_meta = l15_meta.get("meta_integrity", 1.0)
                synthesis["_meta_integrity"] = real_meta
                reflective_pass2 = l13_engine.reflect(
                    symbol,
                    [l12_verdict],
                    synthesis,
                )
            else:
                # No L13 -- still compute vault sync and meta
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

            # ═══════════════════════════════════════════════════════
            # PHASE 7 -- SOVEREIGNTY ENFORCEMENT (drift + downgrade)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 7: Sovereignty Enforcement -- {symbol}")
            engines_invoked.append("SovereigntyEnforcer")

            enforcement = l15_engine.enforce_sovereignty(
                l12_verdict=l12_verdict,
                reflective_pass1=reflective_pass1,
                reflective_pass2=reflective_pass2,
                meta=l15_meta,
                sovereignty=sovereignty,
            )

            # ═══════════════════════════════════════════════════════
            # SIGNAL RATE THROTTLE — prevent over-trading
            # If the final verdict is still EXECUTE_* after enforcement,
            # check whether this symbol has exceeded the emission rate
            # limit. If so, downgrade to HOLD.
            # ═══════════════════════════════════════════════════════
            final_verdict = l12_verdict.get("verdict", "")
            if final_verdict.startswith("EXECUTE") and not safe_mode:
                if self._signal_throttle.is_throttled(symbol):
                    logger.warning(
                        f"[Pipeline v8.0] {symbol} SIGNAL THROTTLED — verdict {final_verdict} downgraded to HOLD"
                    )
                    l12_verdict["verdict"] = "HOLD"
                    l12_verdict["throttled_from"] = final_verdict
                    errors.append("SIGNAL_THROTTLED")
                    SIGNAL_THROTTLED.labels(symbol=symbol).inc()
                else:
                    self._signal_throttle.record(symbol)

            # ═══════════════════════════════════════════════════════
            # PHASE 8.5 -- V11 SNIPER FILTER (optional)
            # ═══════════════════════════════════════════════════════
            v11_overlay = None
            try:
                from engines.v11 import V11PipelineHook  # noqa: PLC0415

                _v11 = V11PipelineHook()
                v11_input = SimpleNamespace(  # noqa: F821
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                )
                v11_overlay = _v11.evaluate(
                    pipeline_result=v11_input,
                    symbol=symbol,
                    timeframe="H1",
                )
                if v11_overlay.should_trade is False and l12_verdict["verdict"].startswith("EXECUTE"):
                    logger.warning(
                        f"[Pipeline v8.0] {symbol} V11 VETO — verdict {l12_verdict['verdict']} downgraded to HOLD"
                    )
                    l12_verdict["verdict"] = "HOLD"
                    l12_verdict["v11_veto"] = True
                    errors.append("V11_VETO")
                synthesis["v11"] = v11_overlay.to_dict() if v11_overlay else None
            except ImportError:
                pass  # V11 optional — not installed = skip
            except Exception as v11_exc:
                logger.warning(f"[Pipeline v8.0] V11 error for {symbol}: {v11_exc}")
                errors.append(f"V11_ERROR: {v11_exc}")

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
            input_ref=str(synthesis.get("symbol", "UNKNOWN")),
            timestamp=str(synthesis.get("system", {}).get("timestamp", "")),
            upstream_continuation_allowed=True,
            upstream_next_legal_targets=["PHASE_5"],
            foundation_status=foundation_status,
            scoring_status=scoring_status,
            enrichment_status="PASS" if total_passed >= 7 else "WARN",
            structure_status=structure_status,
            risk_chain_status=risk_chain_status,
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
        return result.to_dict()

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
