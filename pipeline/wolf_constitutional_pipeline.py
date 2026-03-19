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
    Phase 1: L1, L2, L3 (Perception -- independent, halt-on-failure)
    Phase 2: L4, L5 (Confluence & Psychology -- depend on L1-L3)
    Phase 3: L7, L8, L9 (Probability & Validation -- depend on L4/L5)
    Phase 4: L11 -> L6 -> L10 (Execution + Risk -- L11 BEFORE L6!)
    Phase 5: Build synthesis -> 9-Gate Check -> L12 verdict (SOLE AUTHORITY)
    Phase 6: Two-pass L13 governance (baseline -> meta -> refined)
    Phase 7: Sovereignty enforcement (drift detection + verdict downgrade)
    Phase 8: L14 JSON export + final result assembly

Runtime model (capital-protection first):
    SEMI-PARALLEL HALT-SAFE DAG
    batch_1 -> sync barrier -> batch_2 -> sync barrier -> ...
    If any runnable layer in a batch fails, the pipeline halts before
    entering the next batch.

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
from constitution.signal_throttle import SignalThrottle
from constitution.verdict_engine import generate_l12_verdict
from core.dag_engine import DagEngine
from core.metrics import (
    LAYER_LATENCY,
    SIGNAL_THROTTLED,
    TICK_TO_VERDICT_LATENCY,
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
    Runtime is a semi-parallel halt-safe DAG with batch barriers.
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
        "W1": 4,
        "MN": 2,
    }

    # Avoid log storms when a symbol remains degraded for long periods.
    DQ_WARNING_LOG_INTERVAL_SEC: float = 900.0

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

        # Vault health checker (lazy-initialized on first use)
        self._vault_checker: Any = None  # type: VaultHealthChecker | None

        # Per-symbol data quality warning state for log throttling.
        self._dq_warning_state: dict[str, dict[str, Any]] = {}

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
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer  # noqa: PLC0415
        from analysis.layers.L8_tii_integrity import L8TIIIntegrityAnalyzer  # noqa: PLC0415
        from analysis.layers.L9_smc import L9SMCAnalyzer  # noqa: PLC0415
        from analysis.layers.L11_rr import L11RRAnalyzer  # noqa: PLC0415
        from analysis.macro.monthly_regime import MonthlyRegimeAnalyzer  # noqa: PLC0415

        self._l1 = L1ContextAnalyzer()
        self._l2 = L2MTAAnalyzer()
        self._l3 = L3TechnicalAnalyzer()
        self._l4 = L4ScoringEngine()
        self._l5 = L5PsychologyAnalyzer()
        self._l6 = L6RiskAnalyzer()
        self._l7 = L7ProbabilityAnalyzer()
        self._l8 = L8TIIIntegrityAnalyzer()
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
                    "[Pipeline] Layer %s TIMEOUT (>%.0fs) for %s — aborting layer",
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
        """Execute callable layers in a halt-safe DAG batch pipeline.

        Semantics:
        - Within a batch: runnable layers execute concurrently.
        - Between batches: strict synchronization barrier.
        - Failure mode: fail-fast; if one runnable layer raises, no later
          batch is entered.
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
                        "DAG_BATCH_FAILED: batch=%d, runnable=%s, root_cause=%s: %s",
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
        if not safe_mode:
            _warmup_raw = self._context_bus.check_warmup(symbol, self.WARMUP_MIN_BARS)
            warmup = normalize_warmup(_warmup_raw, required=min(self.WARMUP_MIN_BARS.values())).to_dict()

            if not warmup["ready"]:
                missing = warmup["missing"]
                layers_executed.append("L0")
                engines_invoked.append("WarmupGate")
                logger.warning(
                    f"[Pipeline v8.0] {symbol} WARMUP INSUFFICIENT — "
                    f"bars={warmup['bars']}, required={warmup['required']}, "
                    f"missing={missing}"
                )
                # Return full-structure result (same shape as _early_exit)
                # so downstream consumers never hit missing-key errors.
                result = _early_exit_with_map(
                    [f"WARMUP_INSUFFICIENT:{missing}_bars_missing"],
                    time.time() - start_time,
                )
                result["warmup"] = warmup
                return result

        # ═══════════════════════════════════════════════════════
        # DATA QUALITY GATE -- assess candle gap ratio / staleness
        # and compute confidence penalty to degrade gracefully
        # rather than trading on bad data.
        # ═══════════════════════════════════════════════════════
        from analysis.data_quality_gate import DataQualityGate  # noqa: PLC0415

        _dq_gate = DataQualityGate()
        _dq_penalty: float = 0.0
        _dq_reports: list[dict[str, Any]] = []
        for tf in self.WARMUP_MIN_BARS:
            candles = self._context_bus.get_candles(symbol, tf)
            # Extract last-update timestamp from the newest candle so the
            # staleness check uses real data instead of defaulting to inf.
            _last_ts: float | None = None
            if candles:
                _last_c = candles[-1]
                _last_ts = _last_c.get("timestamp_close") or _last_c.get("timestamp") or _last_c.get("time")
                _last_ts = _coerce_timestamp_to_epoch(_last_ts)
            dq_report = _dq_gate.assess(symbol, tf, candles, last_update_ts=_last_ts)
            _dq_reports.append(dq_report.to_dict())
            if dq_report.confidence_penalty > _dq_penalty:
                _dq_penalty = dq_report.confidence_penalty

        _degraded_reports = [r for r in _dq_reports if r["degraded"]]
        if _dq_penalty > 0:
            now_ts = time.time()
            reason_key = tuple(sorted(";".join(r.get("reasons", [])) for r in _degraded_reports))
            state = self._dq_warning_state.get(symbol, {})
            should_log = (
                not state.get("degraded", False)
                or state.get("reason_key") != reason_key
                or (now_ts - float(state.get("last_log_ts", 0.0))) >= self.DQ_WARNING_LOG_INTERVAL_SEC
            )
            if should_log:
                logger.warning(
                    "[Pipeline v8.0] {} DATA QUALITY degraded - penalty={:.2f}, reports={}",
                    symbol,
                    _dq_penalty,
                    _degraded_reports,
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

        # ═══════════════════════════════════════════════════════
        # GOVERNANCE GATE -- unified freshness / producer health /
        # kill-switch enforcement.  Must pass before any analysis
        # layer runs.  Integrates DQ penalty, feed staleness,
        # producer heartbeat, and operator kill-switch into a
        # single ALLOW / HOLD / BLOCK decision.
        # ═══════════════════════════════════════════════════════
        from state.governance_gate import GovernanceAction, assess_governance  # noqa: PLC0415

        _feed_age_ts = (
            self._context_bus.get_feed_timestamp(symbol) if hasattr(self._context_bus, "get_feed_timestamp") else None
        )
        _heartbeat_ts: float | None = None
        _kill_switch_val: str | None = None
        try:
            from state.redis_keys import HEARTBEAT_INGEST, KILL_SWITCH  # noqa: PLC0415

            _redis_client = getattr(self, "_redis", None)
            if _redis_client is None:
                import contextlib as _ctx  # noqa: PLC0415

                from storage.redis_client import RedisClient  # noqa: PLC0415

                with _ctx.suppress(Exception):
                    _redis_client = RedisClient()
            if _redis_client is not None:
                import contextlib as _ctx2  # noqa: PLC0415

                with _ctx2.suppress(Exception):
                    _hb_raw = _redis_client.get(HEARTBEAT_INGEST)
                    if _hb_raw is not None:
                        _heartbeat_ts = _parse_heartbeat_timestamp(_hb_raw)
                with _ctx2.suppress(Exception):
                    _ks_raw = _redis_client.get(KILL_SWITCH)
                    if _ks_raw is not None:
                        _kill_switch_val = str(_ks_raw)
        except Exception:
            pass  # Redis unavailable — governance proceeds with env defaults

        _warmup_raw_gov = (
            self._context_bus.check_warmup(symbol, self.WARMUP_MIN_BARS) if not safe_mode else {"ready": True}
        )
        _warmup_ready_gov = _warmup_raw_gov.get("ready", True) if isinstance(_warmup_raw_gov, dict) else True

        _governance = assess_governance(
            symbol=symbol,
            last_seen_ts=_feed_age_ts,
            transport_ok=True,
            heartbeat_ts=_heartbeat_ts,
            warmup_ready=_warmup_ready_gov,
            dq_penalty=_dq_penalty,
            dq_degraded=len(_degraded_reports) > 0,
            kill_switch_value=_kill_switch_val,
        )

        if _governance.action == GovernanceAction.BLOCK:
            layers_executed.append("GovernanceGate")
            engines_invoked.append("GovernanceGate")
            result = _early_exit_with_map(
                [f"GOVERNANCE_BLOCK:{','.join(_governance.reasons)}"],
                time.time() - start_time,
            )
            result["governance"] = _governance.to_dict()
            return result

        if _governance.action == GovernanceAction.HOLD:
            layers_executed.append("GovernanceGate")
            engines_invoked.append("GovernanceGate")
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
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 1: Perception & Context -- {symbol}")
            engines_invoked.extend(["L1ContextAnalyzer", "L2MTAAnalyzer", "L3TechnicalAnalyzer"])

            assert self._l1 is not None
            assert self._l2 is not None
            assert self._l3 is not None
            l1_analyzer = self._l1
            l2_analyzer = self._l2
            l3_analyzer = self._l3
            phase1_calls: dict[str, Callable[[], dict[str, Any]]] = {
                "L1": lambda: cast(dict[str, Any], _timed_layer_call(l1_analyzer.analyze, "L1", symbol)),
                "L2": lambda: cast(dict[str, Any], _timed_layer_call(l2_analyzer.analyze, "L2", symbol)),
                "L3": lambda: cast(dict[str, Any], _timed_layer_call(l3_analyzer.analyze, "L3", symbol)),
            }
            phase1_results = self._run_dag_batch_calls(dag_batches, phase1_calls)

            l1 = phase1_results["L1"]
            l2 = phase1_results["L2"]
            l3 = phase1_results["L3"]
            layers_executed.extend(["L1", "L2", "L3"])

            if not l1.get("valid"):
                errors.append("L1_CONTEXT_INVALID")
                return _early_exit_with_map(errors, time.time() - start_time)
            if not l2.get("valid"):
                errors.append("L2_MTA_INVALID")
                return _early_exit_with_map(errors, time.time() - start_time)
            if not l3.get("valid"):
                errors.append("L3_TECHNICAL_INVALID")
                return _early_exit_with_map(errors, time.time() - start_time)

            # ═══════════════════════════════════════════════════════
            # PHASE 2 -- ZONA CONFLUENCE & SCORING (L4, L5)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 2: Confluence & Scoring -- {symbol}")
            engines_invoked.extend(["L4ScoringEngine", "L5PsychologyAnalyzer"])

            assert self._l4 is not None
            assert self._l5 is not None
            l4_engine = self._l4
            l5_engine = self._l5
            phase2_calls: dict[str, Callable[[], dict[str, Any]]] = {
                "L4": lambda: cast(dict[str, Any], _timed_layer_call(l4_engine.score, "L4", l1, l2, l3)),
                "L5": lambda: cast(
                    dict[str, Any], _timed_layer_call(l5_engine.analyze, "L5", symbol, volatility_profile=l2)
                ),
            }
            phase2_results = self._run_dag_batch_calls(dag_batches, phase2_calls)
            l4 = phase2_results["L4"]
            l5 = phase2_results["L5"]
            layers_executed.append("L4")
            layers_executed.append("L5")

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
            # Source: LiveContextBus.get_trade_history() resolves from
            # trade_archive (Redis → PostgreSQL → ledger) automatically.
            # Fallback: system_metrics pass-through (caller-provided / test).

            trade_returns: list[float] | None = None
            trade_returns_preconditioned = False
            preconditioning_diag: dict[str, Any] | None = None
            _bus_returns: list[float] | None = cast(
                list[float] | None,
                self._context_bus.get_trade_history(
                    symbol=symbol,
                    lookback=200,
                ),
            )
            if _bus_returns:
                trade_returns = _bus_returns
                logger.info(
                    "[Phase-3] %s Loaded %d historical returns via context bus",
                    symbol,
                    len(_bus_returns),
                )

            # Fallback: system_metrics pass-through (for test harness / manual override)
            if not trade_returns and system_metrics:
                _raw = system_metrics.get("trade_returns", None)
                if isinstance(_raw, list | tuple) and len(cast(list[Any], _raw)) > 0:
                    trade_returns = [float(r) for r in cast(list[Any], _raw)]

            # Fallback: conditioned returns produced by realtime tick ingest.
            if not trade_returns:
                _cond_returns = cast(
                    list[float],
                    self._context_bus.get_conditioned_returns(symbol, count=200),
                )
                if _cond_returns:
                    trade_returns = _cond_returns
                    trade_returns_preconditioned = True
                    preconditioning_diag = cast(
                        dict[str, Any] | None,
                        self._context_bus.get_conditioning_meta(symbol),
                    )
                    logger.info(
                        "[Phase-3] %s Loaded %d conditioned returns via realtime tick path",
                        symbol,
                        len(_cond_returns),
                    )

            # Fallback: derive returns from candle closes and condition them.
            if not trade_returns:
                _h1 = cast(
                    list[dict[str, Any]],
                    self._context_bus.get_candles(symbol, "H1"),
                )
                _m15 = cast(
                    list[dict[str, Any]],
                    self._context_bus.get_candles(symbol, "M15"),
                )
                _candle_source = "H1" if len(_h1) >= len(_m15) else "M15"
                _candles = _h1 if _candle_source == "H1" else _m15
                _prices: list[float] = []
                for c in _candles:
                    _close = c.get("close")
                    if isinstance(_close, int | float | str):
                        with contextlib.suppress(TypeError, ValueError):
                            _prices.append(float(_close))
                if len(_prices) >= 2:
                    _conditioned = self._signal_conditioner.condition_prices(_prices[-300:])
                    trade_returns = _conditioned.conditioned_returns
                    trade_returns_preconditioned = True
                    preconditioning_diag = _conditioned.diagnostics()
                    preconditioning_diag["source"] = f"candle_{_candle_source}"
                    logger.info(
                        "[Phase-3] %s Derived %d conditioned returns from %s candle closes",
                        symbol,
                        len(trade_returns),
                        _candle_source,
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
                    "[Phase-3] %s SignalConditioner: in=%d out=%d noise=%.4f quality=%.4f stride=%d",
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
                    ),
                ),
                "L8": lambda: cast(dict[str, Any], _timed_layer_call(l8_engine.analyze, "L8", symbol)),
                "L9": lambda: cast(dict[str, Any], _timed_layer_call(l9_engine.analyze, "L9", symbol)),
            }
            phase3_results = self._run_dag_batch_calls(dag_batches, phase3_calls)
            l7 = phase3_results["L7"]
            if conditioning_diag is not None:
                l7["signal_conditioning"] = conditioning_diag
            l8 = phase3_results["L8"]
            l9 = phase3_results["L9"]
            layers_executed.extend(["L7", "L8", "L9"])

            logger.info(
                "[Phase-3] %s L7 complete: validation=%s win=%.1f%% pf=%.2f bayes=%.4f ror=%.4f mc_passed=%s",
                symbol,
                l7.get("validation", "N/A"),
                l7.get("win_probability", 0.0),
                l7.get("profit_factor", 0.0),
                l7.get("bayesian_posterior", 0.0),
                l7.get("risk_of_ruin", 1.0),
                l7.get("mc_passed_threshold", False),
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
                "[Phase-4] L6 account wiring via bus: equity=%.2f peak=%.2f daily_dd=%.4f circuit=%s open=%d/%d",
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

            l6: dict[str, Any] = _timed_layer_call(
                self._l6.analyze,
                "L6",
                rr=rr_value,
                trade_returns=trade_returns,
                account_state=_l6_account_state,
            )
            layers_executed.append("L6")

            risk_ok: Any = l6.get("risk_ok", False)
            smc_confidence: Any = l9.get("confidence", 0.0)
            assert self._l10 is not None
            l10: dict[str, Any] = _timed_layer_call(self._l10.analyze, "L10", risk_ok, smc_confidence)
            layers_executed.append("L10")

            # ═══════════════════════════════════════════════════════
            # PHASE 2.5 -- ENGINE ENRICHMENT LAYER (9 Facade Engines)
            #   ADR-011: cognitive/fusion/quantum enrichment before L12
            # ═══════════════════════════════════════════════════════
            enrichment_data: dict[str, Any] = {}
            try:
                if self._enrichment is None:
                    from engines.enrichment_orchestrator import (  # noqa: PLC0415
                        EngineEnrichmentLayer,
                    )

                    self._enrichment = EngineEnrichmentLayer(
                        context_bus=self._context_bus,
                    )

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
                enrichment_result = self._enrichment.run(
                    symbol=symbol,
                    direction=direction,
                    layer_results=_enrich_lr,
                    entry_price=l11.get("entry_price", l11.get("entry", 0.0)),
                    stop_loss=l11.get("stop_loss", l11.get("sl", 0.0)),
                    take_profit=l11.get("take_profit_1", l11.get("tp1", l11.get("tp", 0.0))),
                )
                engines_invoked.extend(
                    [
                        "EngineEnrichmentLayer",
                        "RegimeClassifier",
                        "FusionIntegrator",
                        "TRQ3DEngine",
                        "QuantumReflectiveBridge",
                    ]
                )
                enrichment_data = enrichment_result.to_dict()
                logger.info(
                    "[Pipeline v8.0] Phase 2.5: Enrichment -- %s score=%.3f engines_ok=%d/9",
                    symbol,
                    enrichment_result.enrichment_score,
                    9 - len(enrichment_result.errors),
                )
            except Exception as exc:
                logger.warning("[Pipeline v8.0] Phase 2.5 enrichment failed (non-fatal): %s", exc)
                enrichment_data = {"error": str(exc)}

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
                        risk_ok = False
                        logger.warning(
                            "[Phase-4→2.5] L6 LRCE escalation: %.3f > threshold → HARD BLOCK",
                            _lrce,
                        )
                    else:
                        logger.debug("[Phase-4→2.5] L6 LRCE updated: %.3f (stable)", _lrce)
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
                            "[Pipeline v8.0] L14-B adaptive penalty %.3f applied for %s",
                            adaptive_penalty,
                            symbol,
                        )
                    l14b_report_dict = _l14b_report.to_dict()
            except Exception as exc:
                logger.warning("[Pipeline v8.0] L14-B adaptive reflection failed (non-fatal): %s", exc)

            synthesis["l14b_adaptive"] = l14b_report_dict

            metrics.get("macro_vix_state", {})

            gates = self._evaluate_9_gates(synthesis)
            l12_verdict = generate_l12_verdict(synthesis, governance_penalty=_dq_penalty)
            l12_verdict["gates_v74"] = gates

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
                    reflective_pass1=None,  # pyright: ignore[reportArgumentType]
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

            # ── Tick→verdict end-to-end latency ────────────────────
            if tick_ts is not None:
                e2e_latency = time.time() - tick_ts
                TICK_TO_VERDICT_LATENCY.labels(symbol=symbol).observe(e2e_latency)  # noqa: F821
                result_dict["tick_to_verdict_s"] = round(e2e_latency, 4)

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
                    "f_score": 0,
                    "t_score": 0,
                    "fta_score": 0.0,
                    "fta_multiplier": 0.0,
                    "exec_score": 0,
                    "psychology_score": 0,
                    "technical_score": 0,
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
                    "take_profit_1": 0.0,
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
        result["execution_map"] = build_execution_map(
            pair=symbol,
            timestamp=result["timestamp"],
            layers_executed=layers_executed or [],
            engines_invoked=engines_invoked or [],
            halt_reason=errors[0] if errors else "UNKNOWN",
            constitutional_verdict=str(result.get("l12_verdict", {}).get("verdict", "HOLD")),
        )
        self._record_metrics(symbol, result)
        return result
