"""
TUYUL FX — Engine Enrichment Layer (Phase 2.5)

Bridges the 9 facade engines into the main pipeline between
Layer analysis (L1–L11) and the L12 Constitutional Verdict.

Architecture:
    L1–L11 layer analysis  →  EngineEnrichmentLayer.run()  →  synthesis enrichment  →  L12 verdict

Each engine call is individually guarded: if an engine raises,
its key is omitted and a warning is logged — the pipeline is
never blocked by a single engine failure.

Engines 1-8 run in parallel (ThreadPoolExecutor) when _PARALLEL_ENRICHMENT is
True; engine 9 (Advisory) always runs sequentially after all others complete
because it depends on their results.  Set _PARALLEL_ENRICHMENT = False to fall
back to the original sequential behaviour for debugging or profiling.

ADR-011: Option A — Enrichment Layer integration.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time

from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parallelism knobs — can be overridden in tests or via env-config
# ---------------------------------------------------------------------------
_PARALLEL_ENRICHMENT: bool = True
_ENRICHMENT_WORKERS: int = 8
_ENRICHMENT_TIMEOUT: float = 10.0  # seconds per engine
# Extra buffer added to the as_completed() call so the outer loop does not
# fire before per-future timeouts have a chance to be handled individually.
_ENRICHMENT_COMPLETION_BUFFER: float = 1.0

# ---------------------------------------------------------------------------
# Timeframes used to build multi-TF candle dicts from the context bus
# ---------------------------------------------------------------------------
_DEFAULT_TFS = ("M15", "H1", "H4", "D1")
_CANDLE_HISTORY_DEPTH = 50  # bars per TF


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class EnrichmentResult:
    """Holds outputs from all 9 facade engines plus an aggregate score."""

    cognitive_coherence: dict[str, Any] = field(default_factory=dict)
    cognitive_context: dict[str, Any] = field(default_factory=dict)
    risk_simulation: dict[str, Any] = field(default_factory=dict)
    fusion_momentum: dict[str, Any] = field(default_factory=dict)
    fusion_precision: dict[str, Any] = field(default_factory=dict)
    fusion_structure: dict[str, Any] = field(default_factory=dict)
    quantum_field: dict[str, Any] = field(default_factory=dict)
    quantum_probability: dict[str, Any] = field(default_factory=dict)
    quantum_advisory: dict[str, Any] = field(default_factory=dict)

    # Aggregate metrics produced by the enrichment layer itself
    confidence_adjustment: float = 0.0
    integrity_boost: float = 0.0
    tail_risk_dampening: float = 0.0
    bias_stability: float = 0.0
    enrichment_score: float = 0.0
    elapsed_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """True if at least one engine produced output."""
        return any([
            self.cognitive_coherence,
            self.cognitive_context,
            self.risk_simulation,
            self.fusion_momentum,
            self.fusion_precision,
            self.fusion_structure,
            self.quantum_field,
            self.quantum_probability,
            self.quantum_advisory,
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "cognitive_coherence": self.cognitive_coherence,
            "cognitive_context": self.cognitive_context,
            "risk_simulation": self.risk_simulation,
            "fusion_momentum": self.fusion_momentum,
            "fusion_precision": self.fusion_precision,
            "fusion_structure": self.fusion_structure,
            "quantum_field": self.quantum_field,
            "quantum_probability": self.quantum_probability,
            "quantum_advisory": self.quantum_advisory,
            "confidence_adjustment": self.confidence_adjustment,
            "integrity_boost": self.integrity_boost,
            "tail_risk_dampening": self.tail_risk_dampening,
            "bias_stability": self.bias_stability,
            "enrichment_score": self.enrichment_score,
            "elapsed_ms": self.elapsed_ms,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class EngineEnrichmentLayer:
    """Orchestrates the 9 facade engines as a Phase 2.5 enrichment step.

    Usage::

        enrichment = EngineEnrichmentLayer(context_bus=bus)
        result = enrichment.run(
            symbol="EURUSD",
            direction="BUY",
            layer_results=layer_results_combined,
        )
        # Inject result.to_dict() into synthesis["enrichment"]

    The orchestrator is **analysis-only** — it produces metrics and scores.
    It never makes execution decisions (that is Layer-12's sole authority).
    """

    def __init__(self, context_bus: Any = None) -> None:
        self._context_bus = context_bus
        # Engines are lazily imported & instantiated on first run
        self._engines: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Lazy engine construction
    # ------------------------------------------------------------------
    def _ensure_engines(self) -> dict[str, Any]:
        if self._engines is not None:
            return self._engines

        from engines import create_engine_suite  # noqa: PLC0415

        self._engines = create_engine_suite()
        return self._engines

    # ------------------------------------------------------------------
    # Multi-TF candle dict builder
    # ------------------------------------------------------------------
    def _build_candles(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        """Fetch candle history from the context bus for all standard TFs.

        Returns a dict keyed by timeframe, each value a list of candle dicts.
        If the context bus is unavailable, returns an empty dict.
        """
        if self._context_bus is None:
            return {}
        candles: dict[str, list[dict[str, Any]]] = {}
        for tf in _DEFAULT_TFS:
            try:
                bars = self._context_bus.get_candle_history(
                    symbol, tf, count=_CANDLE_HISTORY_DEPTH,
                )
                if bars:
                    candles[tf] = bars
            except Exception:
                logger.debug("Enrichment: no %s candles for %s", tf, symbol)
        return candles

    # ------------------------------------------------------------------
    # State builder for cognitive engines (scalar-based, no candles)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_cognitive_state(
        layer_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a flat state dict for CognitiveCoherenceEngine.evaluate()."""
        l5 = layer_results.get("L5", {})
        l8 = layer_results.get("L8", {})
        l2 = layer_results.get("L2", {})
        return {
            "emotion_level": l5.get("psychology_score", 0) / 100.0,
            "loss_stress": l5.get("eaf_score", 0.0),
            "fatigue": 1.0 - l5.get("eaf_score", 0.0),
            "market_volatility": l2.get("frpc_energy", 0.0),
            "tii_sym": l8.get("tii_sym", 0.0),
            "integrity": l8.get("integrity", 0.0),
        }

    # ------------------------------------------------------------------
    # Engine isolation helper
    # ------------------------------------------------------------------
    def _run_engine_safe(
        self,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> tuple[str, Any | None, str | None]:
        """Run a single engine with error isolation.

        Returns
        -------
        (name, result, error_message)
            *result* is ``None`` and *error_message* is set when the engine
            raises; otherwise *error_message* is ``None``.
        """
        try:
            out = fn(*args, **kwargs)
            return (name, out, None)
        except Exception as exc:
            return (name, None, f"{name}: {exc}")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(  # noqa: PLR0912
        self,
        symbol: str,
        direction: str,
        layer_results: dict[str, Any],
        entry_price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> EnrichmentResult:
        """Execute all 9 facade engines and aggregate results.

        Engines 1-8 run in parallel (ThreadPoolExecutor) when the module-level
        ``_PARALLEL_ENRICHMENT`` flag is ``True``.  Engine 9 (Advisory) always
        runs sequentially after the others because it depends on their output.

        Parameters
        ----------
        symbol:
            Trading pair (e.g. "EURUSD").
        direction:
            "BUY" / "SELL" / "HOLD" from L3 trend.
        layer_results:
            Combined L1–L11 + macro results dict (same structure
            as ``layer_results_combined`` in the pipeline).
        entry_price, stop_loss, take_profit:
            From L11, used by CognitiveRiskSimulation.

        Returns
        -------
        EnrichmentResult with per-engine outputs and aggregate metrics.
        """
        t0 = time.time()
        engines = self._ensure_engines()
        result = EnrichmentResult()

        candles = self._build_candles(symbol)
        cog_state = self._build_cognitive_state(layer_results)

        if _PARALLEL_ENRICHMENT:
            result = self._run_engines_parallel(
                result, engines, candles, cog_state,
                direction, symbol, entry_price, stop_loss, take_profit,
            )
        else:
            result = self._run_engines_sequential(
                result, engines, candles, cog_state,
                direction, symbol, entry_price, stop_loss, take_profit,
            )

        # ── 9. Quantum Advisory (cross-engine synthesis, always sequential) ──
        try:
            advisory_inputs: dict[str, Any] = {
                "coherence": result.cognitive_coherence,
                "context": result.cognitive_context,
                "risk_sim": result.risk_simulation,
                "momentum": result.fusion_momentum,
                "precision": result.fusion_precision,
                "structure": result.fusion_structure,
                "field": result.quantum_field,
                "probability": result.quantum_probability,
                "direction": direction,
                "symbol": symbol,
                "wolf_30_point": layer_results.get("L4", {}).get("wolf_30_point", {}).get("total", 0)
                if isinstance(layer_results.get("L4", {}).get("wolf_30_point"), dict) else 0,
                "tii_sym": layer_results.get("L8", {}).get("tii_sym", 0.0),
            }
            adv_out = engines["advisory"].analyze(advisory_inputs, symbol=symbol)
            result.quantum_advisory = adv_out.__dict__ if hasattr(adv_out, "__dict__") else {"raw": str(adv_out)}
        except Exception as exc:
            result.errors.append(f"advisory: {exc}")
            logger.warning("Enrichment: advisory engine failed: %s", exc)

        # ── Aggregate ──
        result = self._aggregate(result, layer_results)
        result.elapsed_ms = (time.time() - t0) * 1000

        logger.info(
            "[Enrichment] %s complete — score=%.3f, engines_ok=%d/9, elapsed=%.1fms",
            symbol,
            result.enrichment_score,
            9 - len(result.errors),
            result.elapsed_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Parallel runner (engines 1-8)
    # ------------------------------------------------------------------
    def _run_engines_parallel(  # noqa: PLR0913
        self,
        result: EnrichmentResult,
        engines: dict[str, Any],
        candles: dict[str, list[dict[str, Any]]],
        cog_state: dict[str, Any],
        direction: str,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> EnrichmentResult:
        """Submit engines 1-8 to a ThreadPoolExecutor and collect results."""

        # Build callable descriptors for the 8 independent engines.
        # Each tuple: (result_field_name, engine_key, callable, args, kwargs, needs_candles)
        tasks: list[tuple[str, str, Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []

        # 1. Cognitive Coherence (scalar state)
        def _run_coherence() -> Any:
            coh_engine = engines["coherence"]
            snapshot = coh_engine.evaluate(cog_state)
            return coh_engine.export(snapshot) if hasattr(coh_engine, "export") else {"raw": str(snapshot)}

        tasks.append(("cognitive_coherence", "coherence", _run_coherence, (), {}))

        # 2. Cognitive Context (scalar state)
        def _run_context() -> Any:
            ctx_engine = engines["context"]
            ctx_out = ctx_engine.evaluate(cog_state)
            return ctx_engine.export(ctx_out) if hasattr(ctx_engine, "export") else {"raw": str(ctx_out)}

        tasks.append(("cognitive_context", "context", _run_context, (), {}))

        if candles:
            # 3. Cognitive Risk Simulation
            def _run_risk_sim() -> Any:
                sim_out = engines["risk_sim"].analyze(
                    candles,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    symbol=symbol,
                )
                return sim_out.__dict__ if hasattr(sim_out, "__dict__") else {"raw": str(sim_out)}

            tasks.append(("risk_simulation", "risk_sim", _run_risk_sim, (), {}))

            # 4. Fusion Momentum
            def _run_momentum() -> Any:
                mom_out = engines["momentum"].analyze(candles, symbol=symbol)
                return mom_out.__dict__ if hasattr(mom_out, "__dict__") else {"raw": str(mom_out)}

            tasks.append(("fusion_momentum", "momentum", _run_momentum, (), {}))

            # 5. Fusion Precision
            def _run_precision() -> Any:
                prec_out = engines["precision"].analyze(candles, direction=direction, symbol=symbol)
                return prec_out.__dict__ if hasattr(prec_out, "__dict__") else {"raw": str(prec_out)}

            tasks.append(("fusion_precision", "precision", _run_precision, (), {}))

            # 6. Fusion Structure
            def _run_structure() -> Any:
                struct_out = engines["structure"].analyze(candles, symbol=symbol)
                return struct_out.__dict__ if hasattr(struct_out, "__dict__") else {"raw": str(struct_out)}

            tasks.append(("fusion_structure", "structure", _run_structure, (), {}))

            # 7. Quantum Field
            def _run_field() -> Any:
                field_out = engines["field"].analyze(candles, symbol=symbol)
                return field_out.__dict__ if hasattr(field_out, "__dict__") else {"raw": str(field_out)}

            tasks.append(("quantum_field", "field", _run_field, (), {}))

            # 8. Quantum Probability
            def _run_probability() -> Any:
                prob_out = engines["probability"].analyze(candles, symbol=symbol)
                return prob_out.__dict__ if hasattr(prob_out, "__dict__") else {"raw": str(prob_out)}

            tasks.append(("quantum_probability", "probability", _run_probability, (), {}))

        # Submit all tasks concurrently
        t_parallel = time.time()
        # We manage the executor manually (not via `with`) so that shutdown can
        # be non-blocking when a TimeoutError occurs.  A context-manager exit
        # always calls shutdown(wait=True), which would block until slow threads
        # finish — defeating the purpose of the per-engine timeout.
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=_ENRICHMENT_WORKERS)
        future_to_field: dict[concurrent.futures.Future[Any], tuple[str, str]] = {
            executor.submit(self._run_engine_safe, field_name, fn): (field_name, engine_key)
            for field_name, engine_key, fn, _args, _kwargs in tasks
        }

        try:
            for future in concurrent.futures.as_completed(
                future_to_field,
                timeout=_ENRICHMENT_TIMEOUT + _ENRICHMENT_COMPLETION_BUFFER,
            ):
                field_name, engine_key = future_to_field[future]
                try:
                    _name, out, err = future.result(timeout=_ENRICHMENT_TIMEOUT)
                    if err is not None:
                        result.errors.append(err)
                        logger.warning("Enrichment: %s engine failed: %s", engine_key, err)
                    elif out is not None:
                        setattr(result, field_name, out)
                except concurrent.futures.TimeoutError:
                    msg = f"{engine_key}: timed out after {_ENRICHMENT_TIMEOUT}s"
                    result.errors.append(msg)
                    logger.warning("Enrichment: %s", msg)
                except Exception as exc:  # noqa: BLE001 — intentional: any engine exception must be non-fatal
                    msg = f"{engine_key}: {exc}"
                    result.errors.append(msg)
                    logger.warning("Enrichment: %s engine failed: %s", engine_key, exc)
        except concurrent.futures.TimeoutError:
            # Some futures did not complete within the allotted window
            for future, (field_name, engine_key) in future_to_field.items():
                if not future.done():
                    msg = f"{engine_key}: timed out after {_ENRICHMENT_TIMEOUT}s"
                    result.errors.append(msg)
                    logger.warning("Enrichment: %s engine timed out", engine_key)
        finally:
            # Do not block on lingering threads; cancel pending and move on.
            executor.shutdown(wait=False, cancel_futures=True)

        logger.debug(
            "[Enrichment] parallel engines 1-8 elapsed=%.1fms",
            (time.time() - t_parallel) * 1000,
        )
        return result

    # ------------------------------------------------------------------
    # Sequential runner (engines 1-8, fallback / debug mode)
    # ------------------------------------------------------------------
    def _run_engines_sequential(  # noqa: PLR0913
        self,
        result: EnrichmentResult,
        engines: dict[str, Any],
        candles: dict[str, list[dict[str, Any]]],
        cog_state: dict[str, Any],
        direction: str,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> EnrichmentResult:
        """Run engines 1-8 one-by-one (original sequential behaviour)."""

        # ── 1. Cognitive Coherence ──
        try:
            coh_engine = engines["coherence"]
            snapshot = coh_engine.evaluate(cog_state)
            result.cognitive_coherence = (
                coh_engine.export(snapshot) if hasattr(coh_engine, "export") else {"raw": str(snapshot)}
            )
        except Exception as exc:
            result.errors.append(f"coherence: {exc}")
            logger.warning("Enrichment: coherence engine failed: %s", exc)

        # ── 2. Cognitive Context ──
        try:
            ctx_engine = engines["context"]
            ctx_out = ctx_engine.evaluate(cog_state)
            result.cognitive_context = (
                ctx_engine.export(ctx_out) if hasattr(ctx_engine, "export") else {"raw": str(ctx_out)}
            )
        except Exception as exc:
            result.errors.append(f"context: {exc}")
            logger.warning("Enrichment: context engine failed: %s", exc)

        # ── 3. Cognitive Risk Simulation ──
        if candles:
            try:
                sim_out = engines["risk_sim"].analyze(
                    candles,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    symbol=symbol,
                )
                result.risk_simulation = sim_out.__dict__ if hasattr(sim_out, "__dict__") else {"raw": str(sim_out)}
            except Exception as exc:
                result.errors.append(f"risk_sim: {exc}")
                logger.warning("Enrichment: risk_sim engine failed: %s", exc)

        # ── 4. Fusion Momentum ──
        if candles:
            try:
                mom_out = engines["momentum"].analyze(candles, symbol=symbol)
                result.fusion_momentum = mom_out.__dict__ if hasattr(mom_out, "__dict__") else {"raw": str(mom_out)}
            except Exception as exc:
                result.errors.append(f"momentum: {exc}")
                logger.warning("Enrichment: momentum engine failed: %s", exc)

        # ── 5. Fusion Precision ──
        if candles:
            try:
                prec_out = engines["precision"].analyze(candles, direction=direction, symbol=symbol)
                result.fusion_precision = prec_out.__dict__ if hasattr(prec_out, "__dict__") else {"raw": str(prec_out)}
            except Exception as exc:
                result.errors.append(f"precision: {exc}")
                logger.warning("Enrichment: precision engine failed: %s", exc)

        # ── 6. Fusion Structure ──
        if candles:
            try:
                struct_out = engines["structure"].analyze(candles, symbol=symbol)
                result.fusion_structure = struct_out.__dict__ if hasattr(struct_out, "__dict__") else {"raw": str(struct_out)}
            except Exception as exc:
                result.errors.append(f"structure: {exc}")
                logger.warning("Enrichment: structure engine failed: %s", exc)

        # ── 7. Quantum Field ──
        if candles:
            try:
                field_out = engines["field"].analyze(candles, symbol=symbol)
                result.quantum_field = field_out.__dict__ if hasattr(field_out, "__dict__") else {"raw": str(field_out)}
            except Exception as exc:
                result.errors.append(f"field: {exc}")
                logger.warning("Enrichment: field engine failed: %s", exc)

        # ── 8. Quantum Probability ──
        if candles:
            try:
                prob_out = engines["probability"].analyze(candles, symbol=symbol)
                result.quantum_probability = prob_out.__dict__ if hasattr(prob_out, "__dict__") else {"raw": str(prob_out)}
            except Exception as exc:
                result.errors.append(f"probability: {exc}")
                logger.warning("Enrichment: probability engine failed: %s", exc)

        return result

    # ------------------------------------------------------------------
    # Aggregation — weighted confidence adjustment
    # ------------------------------------------------------------------
    @staticmethod
    def _aggregate(
        result: EnrichmentResult,
        layer_results: dict[str, Any],
    ) -> EnrichmentResult:
        """Compute aggregate enrichment metrics from per-engine outputs.

        Produces:
        - confidence_adjustment: weighted uplift/dampening for L12 confidence
        - integrity_boost: coherence-derived integrity signal
        - tail_risk_dampening: risk_sim-derived tail risk factor
        - bias_stability: quantum field stability metric
        - enrichment_score: composite 0.0–1.0 score
        """
        scores: list[float] = []

        # Confidence adjustment from cognitive coherence
        coh = result.cognitive_coherence
        coherence_score = coh.get("score", 0.0) if isinstance(coh, dict) else 0.0
        result.integrity_boost = max(0.0, coherence_score - 0.5) * 0.2
        if coherence_score > 0:
            scores.append(coherence_score)

        # Tail risk dampening from risk simulation
        rsim = result.risk_simulation
        if isinstance(rsim, dict) and rsim:
            # Higher tail_risk → more dampening (negative adjustment)
            tail_risk = rsim.get("tail_risk_score", rsim.get("max_drawdown_pct", 0.0))
            result.tail_risk_dampening = min(1.0, max(0.0, tail_risk))
            scores.append(1.0 - result.tail_risk_dampening)

        # Bias stability from quantum field
        qf = result.quantum_field
        if isinstance(qf, dict) and qf:
            stability = qf.get("stability", qf.get("field_stability", 0.5))
            result.bias_stability = float(stability)
            scores.append(result.bias_stability)

        # Momentum contribution
        mom = result.fusion_momentum
        if isinstance(mom, dict) and mom:
            mom_score = mom.get("momentum_score", mom.get("valid", 0))
            if isinstance(mom_score, bool):
                mom_score = 0.7 if mom_score else 0.3
            scores.append(float(mom_score))

        # Precision contribution
        prec = result.fusion_precision
        if isinstance(prec, dict) and prec:
            prec_score = prec.get("precision_weight", prec.get("valid", 0))
            if isinstance(prec_score, bool):
                prec_score = 0.7 if prec_score else 0.3
            scores.append(float(prec_score))

        # Composite enrichment score
        if scores:
            result.enrichment_score = sum(scores) / len(scores)
        else:
            result.enrichment_score = 0.0

        # Net confidence adjustment: positive = boost, negative = dampen
        result.confidence_adjustment = (
            result.integrity_boost
            - (result.tail_risk_dampening * 0.15)
            + (result.bias_stability - 0.5) * 0.1
        )

        return result
