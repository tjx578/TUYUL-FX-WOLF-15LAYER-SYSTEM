"""
TUYUL FX — Engine Enrichment Layer (Phase 2.5)

Bridges the 9 facade engines into the main pipeline between
Layer analysis (L1–L11) and the L12 Constitutional Verdict.

Architecture:
    L1–L11 layer analysis  →  EngineEnrichmentLayer.run()  →  synthesis enrichment  →  L12 verdict

Each engine call is individually guarded: if an engine raises,
its key is omitted and a warning is logged — the pipeline is
never blocked by a single engine failure.

ADR-011: Option A — Enrichment Layer integration.
"""

from __future__ import annotations

import logging
import time

from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

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
            # evaluate() takes scalar state dict
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

        # ── 9. Quantum Advisory (cross-engine synthesis) ──
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
