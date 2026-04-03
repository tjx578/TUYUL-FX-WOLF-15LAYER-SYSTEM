"""Lorentzian Field Stabilizer — feature adapter.

Maps Wolf-15 synthesis features → (alpha, beta, gamma) for LFS engine.
No pipeline dependency — pure dict-in, tuple-out.
"""

from __future__ import annotations


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def map_layer_results_to_abg(synthesis: dict[str, object]) -> tuple[float, float, float]:
    """Derive (alpha, beta, gamma) from a Wolf synthesis dict.

    alpha  ≈  technical energy (L3 TRQ3D + L2 reflex coherence)
    beta   ≈  integrity axis  (L8 TII + L8 integrity index)
    gamma  ≈  fusion axis     (FRPC energy + TWMS + L9 liquidity)
    """
    layers = synthesis.get("layers", {})
    if not isinstance(layers, dict):
        layers = {}
    fusion = synthesis.get("fusion_frpc", {})
    if not isinstance(fusion, dict):
        fusion = {}

    l2_reflex = float(layers.get("L2_reflex_coherence", 0.0) or 0.0)
    l3_energy = float(layers.get("L3_trq3d_energy", 0.0) or 0.0)
    l8_tii = float(layers.get("L8_tii_sym", 0.0) or 0.0)
    l8_integrity = float(layers.get("L8_integrity_index", 0.0) or 0.0)
    l8_twms = float(layers.get("L8_twms_score", 0.0) or 0.0)
    l9_liq = float(layers.get("L9_liquidity_score", 0.0) or 0.0)
    frpc_energy = float(fusion.get("frpc_energy", 0.0) or 0.0)

    alpha = _clamp(0.55 * l3_energy + 0.45 * l2_reflex)
    beta = _clamp(0.50 * l8_tii + 0.50 * l8_integrity)
    gamma = _clamp(0.60 * frpc_energy + 0.25 * l8_twms + 0.15 * l9_liq)

    return alpha, beta, gamma
