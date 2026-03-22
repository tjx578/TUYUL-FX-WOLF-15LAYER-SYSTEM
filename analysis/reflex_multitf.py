"""Multi-Timeframe RQI Synchronization.

Computes per-timeframe RQI scores from L2's per-TF probability data,
then aggregates them into a single weighted RQI_multi score.

Per-TF coherence derivation:
    coherence_tf = |p_bull_tf - 0.5| × 2   (directional conviction [0, 1])

Per-TF RQI:
    RQI_tf = latency_decay × coherence_tf × (1 - emotion_delta)

Weighted aggregation:
    RQI_multi = Σ (w_tf × RQI_tf)    for available timeframes
    Weights are re-normalised over available TFs.

Default weights (execution-relevant timeframes):
    M15 = 0.20  (noisy, low weight)
    H1  = 0.50  (primary execution timeframe)
    H4  = 0.30  (structural context)

This module is analysis-only and has no execution side-effects.
"""

from __future__ import annotations

from typing import Any

from analysis.reflex_rqi import latency_decay

# ── Default TF weights for RQI aggregation ────────────────────────────────────

DEFAULT_TF_WEIGHTS: dict[str, float] = {
    "M15": 0.20,
    "H1": 0.50,
    "H4": 0.30,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def per_tf_coherence(p_bull: float) -> float:
    """Derive directional conviction from a bullish probability.

    Maps p_bull ∈ (0, 1) to conviction strength ∈ [0, 1].
    0.5 (no conviction) → 0.0; 0.0 or 1.0 (full conviction) → 1.0.
    """
    return _clamp01(abs(float(p_bull) - 0.5) * 2.0)


def compute_per_tf_rqi(
    per_tf_detail: dict[str, dict[str, Any]],
    delta_t_sec: float,
    emotion_delta: float,
    sigma_sec: float = 60.0,
) -> dict[str, float]:
    """Compute RQI for each timeframe present in *per_tf_detail*.

    Args:
        per_tf_detail: L2 output mapping TF → {p_bull, ...}.
        delta_t_sec: Signal age in seconds (global).
        emotion_delta: Emotion bias from L5 (global) [0, 1].
        sigma_sec: Gaussian sigma for latency decay (may be adaptive).

    Returns:
        Dict mapping TF → RQI_tf in [0, 1].
    """
    decay = latency_decay(delta_t_sec, sigma_sec)
    emotion_stability = 1.0 - _clamp01(emotion_delta)

    rqi_per_tf: dict[str, float] = {}
    for tf, detail in per_tf_detail.items():
        p_bull = float(detail.get("p_bull", 0.5))
        coh = per_tf_coherence(p_bull)
        rqi_tf = _clamp01(decay * coh * emotion_stability)
        rqi_per_tf[tf] = round(rqi_tf, 6)

    return rqi_per_tf


def aggregate_multitf_rqi(
    rqi_per_tf: dict[str, float],
    tf_weights: dict[str, float] | None = None,
) -> float:
    """Weighted aggregation of per-TF RQI scores.

    Weights are re-normalised over the intersection of *rqi_per_tf* keys
    and *tf_weights* keys so the result is valid even when some timeframes
    are missing.

    Args:
        rqi_per_tf: Per-TF RQI values from ``compute_per_tf_rqi()``.
        tf_weights: Optional weight map.  Defaults to ``DEFAULT_TF_WEIGHTS``.

    Returns:
        Weighted RQI_multi in [0, 1].  Returns 0.0 if no overlap.
    """
    weights = tf_weights or DEFAULT_TF_WEIGHTS

    # Intersect available TFs with weight map
    common = set(rqi_per_tf) & set(weights)
    if not common:
        return 0.0

    total_weight = sum(weights[tf] for tf in common)
    if total_weight <= 0:
        return 0.0

    weighted_sum = sum(weights[tf] * rqi_per_tf[tf] for tf in common)
    return _clamp01(weighted_sum / total_weight)


def compute_multitf_rqi(
    per_tf_detail: dict[str, dict[str, Any]],
    delta_t_sec: float,
    emotion_delta: float,
    sigma_sec: float = 60.0,
    tf_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """End-to-end multi-TF RQI computation.

    Convenience wrapper that calls ``compute_per_tf_rqi`` then
    ``aggregate_multitf_rqi`` and returns both per-TF and aggregate
    results for storage in synthesis.

    Returns:
        {
            "rqi_per_tf": {TF: float, ...},
            "rqi_multi": float,
            "tf_weights_used": {TF: float, ...},
        }
    """
    rqi_per_tf = compute_per_tf_rqi(
        per_tf_detail,
        delta_t_sec,
        emotion_delta,
        sigma_sec,
    )
    rqi_multi = aggregate_multitf_rqi(rqi_per_tf, tf_weights)

    return {
        "rqi_per_tf": rqi_per_tf,
        "rqi_multi": round(rqi_multi, 6),
        "tf_weights_used": tf_weights or DEFAULT_TF_WEIGHTS,
    }
