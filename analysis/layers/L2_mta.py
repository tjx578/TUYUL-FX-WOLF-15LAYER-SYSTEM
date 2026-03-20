"""
🧭 L2 — Bayesian Multi-Timeframe Alignment (PRODUCTION v3)
============================================================
Hierarchical Bayesian fusion across 6 timeframes with entropy-based
conflict detection and real engine integration.

Mathematical Model:
    1. Per-TF Probability:  P_i = σ(β₁·slope + β₂·body_str + β₃·wick_rej)
    2. Hierarchical Prior:  P(LTF|HTF) = P(HTF)·P(LTF) / Z
    3. Composite Posterior:  P_MTA = Π(P_i^w_i) / Σ(Π(P_i^w_i))
    4. Entropy Penalty:     H = -Σ D_i·log(D_i)
    5. Alignment Strength:  AS = 1 - H/log(2)
    6. Reflex Coherence:    RC = P_MTA · AS     (target ≥ 0.88)

Engine Integration (correct paths, verified signatures):
    core.core_cognitive_unified.ReflexEmotionCore
        .compute_reflex_emotion(market_data: dict) → ReflexEmotionResult
    core.core_fusion.integrator.FusionIntegrator
        .fuse_reflective_context(*, market_data, coherence_audit) → dict

Pipeline contract:
    Called as ``self._l2.analyze(symbol)`` — signature MUST be (symbol: str).
    Returns dict consumed by L4, L5, build_l12_synthesis, 9-Gate check.

Downstream gates that depend on L2:
    Gate 3: frpc_state == "SYNC"
    Gate 4: conf12 >= 0.75
    L15 Zona 1: L2_reflex_coherence >= 0.88

Zone: analysis/ — Perception & Context (read-only, no execution).
"""  # noqa: N999

from __future__ import annotations

import math
from typing import Any

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


# ── Engine imports (correct paths, verified from repo) ────────────
try:
    from core.core_cognitive_unified import (
        ReflexEmotionCore,
    )
except ImportError:
    ReflexEmotionCore = None

try:
    from core.core_fusion.integrator import (
        FusionIntegrator,
    )
except ImportError:
    FusionIntegrator = None

__all__ = ["L2MTA", "L2MTAAnalyzer"]


# ═══════════════════════════════════════════════════════════════════
# §0  CONSTANTS
# ═══════════════════════════════════════════════════════════════════

# ── Logistic regression coefficients for P_i ──────────────────────
# Tuned for FX (|slope| ~ 0-2, body_str ~ 0-1, wick_rej ~ -1..+1)
_BETA_SLOPE: float = 1.8
_BETA_BODY: float = 1.2
_BETA_WICK: float = 0.6

# ── Static TF weights (fallback / TRANSITION regime) ─────────────
_TF_WEIGHTS_DEFAULT: dict[str, float] = {
    "MN": 0.35,
    "W1": 0.25,
    "D1": 0.15,
    "H4": 0.15,
    "H1": 0.07,
    "M15": 0.03,
}

# Trend regime: amplify HTF structural bias
_TF_WEIGHTS_TREND: dict[str, float] = {
    "MN": 0.40,
    "W1": 0.25,
    "D1": 0.15,
    "H4": 0.10,
    "H1": 0.07,
    "M15": 0.03,
}

# Range regime: amplify LTF mean-reversion signals
_TF_WEIGHTS_RANGE: dict[str, float] = {
    "MN": 0.15,
    "W1": 0.15,
    "D1": 0.15,
    "H4": 0.20,
    "H1": 0.20,
    "M15": 0.15,
}

# TF hierarchy order (HTF → LTF) for Bayesian prior chain
_TF_ORDER: list[str] = ["MN", "W1", "D1", "H4", "H1", "M15"]

_MIN_TIMEFRAMES: int = 3
_LOG2: float = math.log(2.0)

# ── Volatility dampener map ───────────────────────────────────────
_VOL_DAMPENER: dict[str, float] = {
    "EXTREME": 0.60,
    "HIGH": 0.80,
    "LOW": 0.90,
    "DEAD": 0.70,
    "NORMAL": 1.00,
}

# FusionIntegrator default gate = 0.96 (L12 level).
# L2 is perception, not verdict — use lower gate for useful output.
_L2_FUSION_GATE: float = 0.60

# Linear regression lookback for slope estimation
_SLOPE_LOOKBACK: int = 5


# ═══════════════════════════════════════════════════════════════════
# §1  PURE MATH FUNCTIONS
# ═══════════════════════════════════════════════════════════════════


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid σ(x) → (0, 1)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _candle_features(candle: dict[str, Any] | None) -> tuple[float, float, float]:
    """Extract (slope_proxy, body_strength, wick_rejection) from candle.

    Args:
        candle: OHLCV dict with open/high/low/close (and optionally
                a ``closes`` list for slope estimation).

    Returns:
        slope_proxy: Normalized price change direction [-2, +2].
        body_strength: |body| / range in [0, 1].
        wick_rejection: Asymmetric wick bias in [-1, +1].
            +1 = strong lower wick rejection (bullish).
            -1 = strong upper wick rejection (bearish).
    """
    if not candle:
        return 0.0, 0.0, 0.0

    o = float(candle.get("open", 0.0))
    c = float(candle.get("close", 0.0))
    h = float(candle.get("high", max(o, c)))
    lo = float(candle.get("low", min(o, c)))

    rng = h - lo
    if rng < 1e-10:
        return 0.0, 0.0, 0.0

    # Body strength: directional conviction
    body = c - o
    body_strength = min(abs(body) / rng, 1.0)

    # Slope proxy: normalized close-open / range, scaled to ~[-2,+2]
    slope_proxy = (body / rng) * 2.0

    # If we have a closes list, use linear regression slope instead
    closes = candle.get("closes")
    if isinstance(closes, (list, tuple)) and len(closes) >= _SLOPE_LOOKBACK:
        recent = closes[-_SLOPE_LOOKBACK:]
        n = len(recent)
        x_mean = (n - 1) / 2.0
        y_mean = sum(recent) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(recent))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den > 0 and y_mean != 0:
            raw_slope = num / den
            slope_proxy = (raw_slope / abs(y_mean)) * 100.0
            slope_proxy = max(-2.0, min(2.0, slope_proxy))

    # Wick rejection: lower_wick - upper_wick, normalized
    body_top = max(o, c)
    body_bottom = min(o, c)
    upper_wick = h - body_top
    lower_wick = body_bottom - lo
    wick_rejection = (lower_wick - upper_wick) / rng  # [-1, +1]

    return slope_proxy, body_strength, wick_rejection


def _per_tf_probability(
    slope: float,
    body_str: float,
    wick_rej: float,
) -> float:
    """Compute P_i = σ(β₁·slope + β₂·body_str + β₃·wick_rej).

    Returns directional probability in (0, 1).
    > 0.5 = bullish signal, < 0.5 = bearish signal.
    """
    z = _BETA_SLOPE * slope + _BETA_BODY * body_str + _BETA_WICK * wick_rej
    return _sigmoid(z)


def _hierarchical_bayesian_fusion(
    tf_probs: dict[str, float],
    weights: dict[str, float],
) -> tuple[float, float]:
    """Hierarchical Bayesian posterior fusion.

    For each TF (ordered HTF→LTF):
        P_bull(current) = prior_bull * likelihood_bull / Z
        P_bear(current) = prior_bear * likelihood_bear / Z

    Then weighted geometric mean:
        P_MTA_bull = Π(P_i_bull ^ w_i)
        P_MTA_bear = Π(P_i_bear ^ w_i)
        P_MTA = P_MTA_bull / (P_MTA_bull + P_MTA_bear)

    Args:
        tf_probs: {TF: P_i} where P_i > 0.5 = bullish.
        weights: {TF: weight} summing to ~1.0.

    Returns:
        (p_mta, p_bear): Normalized composite probabilities.
    """
    if not tf_probs:
        return 0.5, 0.5

    # Collect in hierarchy order
    ordered_tfs = [tf for tf in _TF_ORDER if tf in tf_probs]
    if not ordered_tfs:
        return 0.5, 0.5

    # Hierarchical prior propagation
    prior_bull: float = 0.5  # uninformative prior
    posterior_bull: dict[str, float] = {}

    for tf in ordered_tfs:
        p_i = tf_probs[tf]
        # Bayes: posterior ∝ prior × likelihood
        like_bull = p_i
        like_bear = 1.0 - p_i
        post_bull = prior_bull * like_bull
        post_bear = (1.0 - prior_bull) * like_bear
        z = post_bull + post_bear
        if z > 0:
            post_bull /= z
        else:
            post_bull = 0.5

        posterior_bull[tf] = post_bull
        # This TF's posterior becomes next TF's prior
        prior_bull = post_bull

    # Weighted geometric mean of posteriors
    log_bull: float = 0.0
    log_bear: float = 0.0
    total_w: float = 0.0

    for tf, post_b in posterior_bull.items():
        w = weights.get(tf, 0.0)
        if w <= 0:
            continue
        total_w += w
        # Clamp to avoid log(0)
        pb = max(1e-8, min(1.0 - 1e-8, post_b))
        log_bull += w * math.log(pb)
        log_bear += w * math.log(1.0 - pb)

    if total_w <= 0:
        return 0.5, 0.5

    # Normalize weights
    log_bull /= total_w
    log_bear /= total_w

    geo_bull = math.exp(log_bull)
    geo_bear = math.exp(log_bear)
    z = geo_bull + geo_bear

    p_mta = geo_bull / z if z > 0 else 0.5

    return p_mta, 1.0 - p_mta


def _entropy_alignment(p_bull: float, p_bear: float) -> float:
    """Compute alignment strength from entropy conflict penalty.

    H_mta = -Σ D_i · log(D_i)
    AS = 1 - H_mta / log(2)

    AS = 1.0 → perfect agreement (one side dominates).
    AS = 0.0 → maximum conflict (50/50 split).

    Returns:
        Alignment strength in [0.0, 1.0].
    """
    if p_bull <= 0 or p_bear <= 0:
        return 1.0  # One side is zero → no conflict

    h = -(p_bull * math.log(p_bull) + p_bear * math.log(p_bear))
    return max(0.0, 1.0 - h / _LOG2)


# ═══════════════════════════════════════════════════════════════════
# §2  ANALYZER CLASS
# ═══════════════════════════════════════════════════════════════════


class L2MTAAnalyzer:
    """Layer 2: Bayesian Multi-Timeframe Alignment.

    Production implementation:
    - Per-TF logistic probability from candle features
    - Hierarchical Bayesian fusion (HTF prior → LTF likelihood)
    - Entropy-based conflict penalty
    - Adaptive TF weights (regime-dependent)
    - Volatility dampener
    - ReflexEmotionCore + FusionIntegrator integration
    - Downstream sensitivity multiplier for L3
    """

    def __init__(self, *, redis_client: Any = None) -> None:
        self._redis_client = redis_client
        self.context: Any = None  # Candle source (mock-able in tests)
        self.bus: Any = None  # Candle bus (mock-able in integration)

        # Lazy-loaded engines
        self._reflex: ReflexEmotionCore | None = None  # type: ignore[type-arg]
        self._fusion: FusionIntegrator | None = None  # type: ignore[type-arg]
        self._engines_loaded: bool = False

    # ──────────────────────────────────────────────────────────
    #  Lazy engine initialization
    # ──────────────────────────────────────────────────────────

    def _ensure_engines(self) -> None:
        """Load engines once. Failures are non-fatal."""
        if self._engines_loaded:
            return
        self._engines_loaded = True

        if ReflexEmotionCore is not None:
            try:
                self._reflex = ReflexEmotionCore()
            except Exception as exc:
                logger.warning("[L2] ReflexEmotionCore init failed: {}", exc)

        if FusionIntegrator is not None:
            try:
                self._fusion = FusionIntegrator(gate_threshold=_L2_FUSION_GATE)
            except Exception as exc:
                logger.warning("[L2] FusionIntegrator init failed: {}", exc)

    # ──────────────────────────────────────────────────────────
    #  Adaptive TF weight selection
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _adaptive_weights(regime: str) -> dict[str, float]:
        """Select TF weight profile from L1 regime."""
        if regime in ("TREND_UP", "TREND_DOWN"):
            return _TF_WEIGHTS_TREND
        if regime == "RANGE":
            return _TF_WEIGHTS_RANGE
        return _TF_WEIGHTS_DEFAULT

    # ──────────────────────────────────────────────────────────
    #  L1 context fetch from bus cache
    # ──────────────────────────────────────────────────────────

    def _fetch_l1_context(self, symbol: str) -> dict[str, Any] | None:
        """Pull latest L1 result from context bus layer cache."""
        source = self.bus or self.context
        if source is None:
            return None
        try:
            return source.get_layer_cache("L1", symbol)
        except (AttributeError, Exception):
            return None

    # ──────────────────────────────────────────────────────────
    #  L3 sensitivity control
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_sensitivity(
        reflex_coherence: float,
        alignment_strength: float,
        conf12: float,
    ) -> float:
        """Downstream sensitivity multiplier for L3.

        > 1.0 → L3 should be more selective (weak L2).
        < 1.0 → L3 can relax thresholds (strong L2).
        """
        base = 1.0
        if reflex_coherence < 0.6:
            base *= 1.2
        if alignment_strength < 0.5:
            base *= 1.1
        if conf12 > 0.9:
            base *= 0.8
        return round(max(0.5, min(1.5, base)), 3)

    # ══════════════════════════════════════════════════════════
    #  MAIN ANALYZE — pipeline entry point
    # ══════════════════════════════════════════════════════════

    def analyze(self, symbol: str) -> dict[str, Any]:  # noqa: PLR0912
        """Bayesian multi-timeframe alignment analysis.

        Pipeline-compatible: called as ``self._l2.analyze(symbol)``.

        Mathematical flow:
            1. Extract candle features per TF (slope, body, wick)
            2. Compute P_i = σ(β·features) per TF
            3. Hierarchical Bayesian fusion (HTF prior → LTF)
            4. Weighted geometric mean posterior
            5. Entropy conflict penalty → alignment strength
            6. RC = P_MTA · AS (target ≥ 0.88)
            7. Engine enrichment (ReflexEmotionCore + FusionIntegrator)
        """
        self._ensure_engines()

        candle_source = self.bus or self.context
        l1_ctx = self._fetch_l1_context(symbol)

        # ── Adaptive TF weights ───────────────────────────────
        regime = l1_ctx.get("regime", "TRANSITION") if l1_ctx else "TRANSITION"
        weights = self._adaptive_weights(regime)

        # ── Collect per-TF candle features & probabilities ────
        tf_probs: dict[str, float] = {}
        per_tf_detail: dict[str, dict[str, Any]] = {}
        available: int = 0

        for tf in _TF_ORDER:
            candle = None
            if candle_source is not None:
                try:
                    candle = candle_source.get_candle(symbol, tf)
                except Exception:
                    candle = None

            if candle is None:
                continue

            slope, body_str, wick_rej = _candle_features(candle)
            p_i = _per_tf_probability(slope, body_str, wick_rej)

            tf_probs[tf] = p_i
            per_tf_detail[tf] = {
                "p_bull": round(p_i, 4),
                "slope": round(slope, 4),
                "body_strength": round(body_str, 4),
                "wick_rejection": round(wick_rej, 4),
            }
            available += 1

        # ── Validity gate ─────────────────────────────────────
        if available < _MIN_TIMEFRAMES:
            return self._fallback(available, per_tf_detail)

        # ── Hierarchical Bayesian Fusion ──────────────────────
        p_mta_bull, p_mta_bear = _hierarchical_bayesian_fusion(
            tf_probs,
            weights,
        )

        # ── Entropy Conflict Penalty ──────────────────────────
        alignment_strength = _entropy_alignment(p_mta_bull, p_mta_bear)

        # ── Reflex Coherence = P_MTA · AS ─────────────────────
        p_mta = max(p_mta_bull, p_mta_bear)
        bayesian_rc = round(p_mta * alignment_strength, 4)

        # ── Volatility dampener ───────────────────────────────
        vol_level = l1_ctx.get("volatility_level", "NORMAL") if l1_ctx else "NORMAL"
        dampener = _VOL_DAMPENER.get(vol_level, 1.0)
        bayesian_rc_damped = round(bayesian_rc * dampener, 4)

        # ── Direction ─────────────────────────────────────────
        if p_mta_bull > 0.5:
            direction = "BULLISH"
        elif p_mta_bear > 0.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Signed composite bias for backward compatibility
        composite_bias = round(
            (p_mta_bull - 0.5) * 2.0 * dampener,
            5,
        )

        aligned = alignment_strength >= 0.6

        # ── Compliance string ─────────────────────────────────
        bullish_tfs = sum(1 for p in tf_probs.values() if p > 0.5)
        bearish_tfs = sum(1 for p in tf_probs.values() if p < 0.5)
        compliance = f"{max(bullish_tfs, bearish_tfs)}/{available}"

        # ══════════════════════════════════════════════════════
        #  ENGINE INTEGRATION
        # ══════════════════════════════════════════════════════

        engine_reflex: float = 0.0
        reflex_gate_str: str = "CLOSED"

        # ── ReflexEmotionCore ─────────────────────────────────
        if self._reflex is not None and l1_ctx is not None:
            try:
                market_data = {
                    "volatility": float(l1_ctx.get("atr_pct", 0.0)) / 100.0,
                    "momentum": composite_bias,
                    "volume_ratio": 1.0,
                }
                result = self._reflex.compute_reflex_emotion(market_data)
                engine_reflex = float(result.reflex_coherence)
                reflex_gate_str = str(result.gate)
            except Exception as exc:
                logger.debug("[L2] Reflex engine error: {}", exc)

        # ── Combined reflex_coherence ─────────────────────────
        # Blend Bayesian RC (math-derived) with engine RC (cognitive)
        # Bayesian is primary (0.65), engine is secondary (0.35)
        if engine_reflex > 0:
            reflex_coherence = round(
                bayesian_rc_damped * 0.65 + engine_reflex * 0.35,
                4,
            )
        else:
            reflex_coherence = bayesian_rc_damped

        # ── FusionIntegrator ──────────────────────────────────
        conf12: float = 0.0
        frpc_energy: float = 0.0
        frpc_state: str = "DESYNC"
        field_phase: str = "CONSOLIDATION"

        if self._fusion is not None and l1_ctx is not None:
            try:
                fusion_market = {
                    "alpha": max(0.5, min(2.0, 1.0 + composite_bias)),
                    "beta": max(
                        0.5,
                        min(2.0, 1.0 + reflex_coherence * 0.5),
                    ),
                    "gamma": 1.0,
                    "lambda_esi": 0.06,
                    "pair": symbol,
                    "timeframe": "MTA",
                    "base_bias": max(
                        0.01,
                        min(1.0, abs(composite_bias) + 0.5),
                    ),
                }

                gate_pass = reflex_gate_str in ("OPEN", "CONDITIONAL")

                fusion_audit = {
                    "reflective_coherence": reflex_coherence,
                    "gate_pass": gate_pass,
                    "gate_threshold": _L2_FUSION_GATE,
                }

                fusion_out = self._fusion.fuse_reflective_context(
                    market_data=fusion_market,
                    coherence_audit=fusion_audit,
                )

                if fusion_out.get("status") == "OK":
                    conf12 = float(fusion_out.get("conf12_final", 0.0))
                else:
                    lineage = fusion_out.get("confidence_lineage", {})
                    if isinstance(lineage, dict):
                        conf12 = float(lineage.get("final", 0.0))

                field_ctx = fusion_out.get(
                    "fusion_output",
                    {},
                ).get("field_context", {})
                frpc_energy = float(
                    field_ctx.get("field_integrity", 0.0),
                )
                field_phase = str(field_ctx.get("phase", "CONSOLIDATION"))

                if fusion_out.get("status") == "OK" and frpc_energy >= 0.85:
                    frpc_state = "SYNC"
                elif fusion_out.get("status") == "OK" and frpc_energy >= 0.5:
                    frpc_state = "PARTIAL"
                else:
                    frpc_state = "DESYNC"

            except Exception as exc:
                logger.debug("[L2] Fusion engine error: {}", exc)

        # ── Fusion-based alignment override ───────────────────
        if conf12 >= 0.9 and frpc_energy >= 0.85:
            aligned = True
            alignment_strength = max(alignment_strength, 0.9)

        # ── Sensitivity multiplier for L3 ─────────────────────
        sensitivity = self._compute_sensitivity(
            reflex_coherence,
            alignment_strength,
            conf12,
        )

        logger.debug(
            "[L2] %s regime=%s dir=%s p_bull=%.4f p_bear=%.4f AS=%.4f RC=%.4f conf12=%.4f frpc=%s sens=%.3f",
            symbol,
            regime,
            direction,
            p_mta_bull,
            p_mta_bear,
            alignment_strength,
            reflex_coherence,
            conf12,
            frpc_state,
            sensitivity,
        )

        return {
            # ── Pipeline-required fields ──
            "mta_compliance": compliance,
            "hierarchy_followed": aligned,
            "reflex_coherence": reflex_coherence,
            "conf12": round(conf12, 4),
            "frpc_energy": round(frpc_energy, 4),
            "frpc_state": frpc_state,
            "field_phase": field_phase,
            "valid": True,
            "direction": direction,
            "composite_bias": composite_bias,
            "available_timeframes": available,
            "aligned": aligned,
            "alignment_strength": round(alignment_strength, 4),
            "per_tf_bias": per_tf_detail,
            # ── New Bayesian fields ──
            "p_mta_bull": round(p_mta_bull, 4),
            "p_mta_bear": round(p_mta_bear, 4),
            "bayesian_rc": bayesian_rc,
            "bayesian_rc_damped": bayesian_rc_damped,
            "entropy_alignment": round(alignment_strength, 4),
            "sensitivity_multiplier": sensitivity,
            "regime_used": regime,
            "volatility_dampener": dampener,
        }

    # ──────────────────────────────────────────────────────────
    #  Legacy compute() — backward compatible
    # ──────────────────────────────────────────────────────────

    def compute(
        self,
        symbol: str,
        macro_bias: str | None = None,
    ) -> dict[str, Any]:
        """Compute MTA with per-TF detail dict (integration entry point).

        Returns dict with ``per_tf`` mapping each TF to
        ``{weight, bias, candle}``. Backward compatible.
        """
        candle_source = self.bus or self.context
        per_tf: dict[str, dict[str, Any]] = {}

        for tf, weight in _TF_WEIGHTS_DEFAULT.items():
            candle = None
            if candle_source is not None:
                try:
                    candle = candle_source.get_candle(symbol, tf)
                except Exception:
                    candle = None

            slope, _body_str, _ = _candle_features(candle)
            if slope > 0:
                bias_str = "BULLISH"
            elif slope < 0:
                bias_str = "BEARISH"
            else:
                bias_str = "NEUTRAL"

            per_tf[tf] = {
                "weight": weight,
                "bias": bias_str,
                "candle": candle,
            }

        return {"per_tf": per_tf, "macro_bias": macro_bias}

    # ──────────────────────────────────────────────────────────
    #  Fallback
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _fallback(
        available: int,
        per_tf_detail: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Safe-default when insufficient TFs available."""
        return {
            "mta_compliance": f"0/{len(_TF_WEIGHTS_DEFAULT)}",
            "hierarchy_followed": False,
            "reflex_coherence": 0.0,
            "conf12": 0.0,
            "frpc_energy": 0.0,
            "frpc_state": "DESYNC",
            "field_phase": "CONSOLIDATION",
            "valid": False,
            "direction": "NEUTRAL",
            "composite_bias": 0.0,
            "available_timeframes": available,
            "aligned": False,
            "alignment_strength": 0.0,
            "per_tf_bias": per_tf_detail,
            "p_mta_bull": 0.5,
            "p_mta_bear": 0.5,
            "bayesian_rc": 0.0,
            "bayesian_rc_damped": 0.0,
            "entropy_alignment": 0.0,
            "sensitivity_multiplier": 1.2,
            "regime_used": "UNKNOWN",
            "volatility_dampener": 1.0,
        }


# Backward compatibility alias
L2MTA = L2MTAAnalyzer
