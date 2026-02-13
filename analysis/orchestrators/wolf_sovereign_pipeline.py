"""
Wolf Sovereign Pipeline — Master Orchestrator

Single entry point for complete analysis flow:
L1-L11 → Synthesis → L12 → L13 (pass 1) → L15 → L13 (pass 2) → Sovereignty

Fixes:
1. Dual pipeline issue - uses constitution/verdict_engine as SOLE AUTHORITY
2. VIX multiplier is properly applied
3. L13 + L15 wired into pipeline with two-pass governance
4. Correct layer execution order (L11 before L6)
5. Contract-safe synthesis builder for L12
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from config.constants import get_threshold
from constitution.verdict_engine import generate_l12_verdict


@dataclass
class SovereignResult:
    """Complete pipeline output."""

    symbol: str
    synthesis: dict[str, Any]
    l12_verdict: dict[str, Any]
    reflective_pass1: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    reflective_pass2: dict[str, Any] | None = None
    enforcement: dict[str, Any] | None = None
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class WolfSovereignPipeline:
    """
    Master orchestrator for Wolf 15-Layer System.

    Correct execution order:
    Phase 1: L1, L2, L3 (independent)
    Phase 2: L4, L5, L7, L8, L9 (dependent)
    Phase 3: L11 (RR calculation) → L6 (risk check) → L10 (position feasibility)
    Phase 4: Build synthesis → L12 verdict (SOLE AUTHORITY)
    Phase 5: L13 pass 1 → L15 meta → L13 pass 2
    Phase 6: Sovereignty enforcement
    """

    def __init__(self) -> None:
        """Initialize with lazy loading to avoid circular imports."""
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
        self._macro_vol = None

    def _ensure_analyzers(self) -> None:
        """Lazy load analyzers to avoid circular imports."""
        if self._l1 is not None:
            return

        # Import here to avoid circular dependencies
        from analysis.layers.L1_context import L1ContextAnalyzer
        from analysis.layers.L2_mta import L2MTAAnalyzer
        from analysis.layers.L3_technical import L3TechnicalAnalyzer
        from analysis.layers.L4_scoring import L4ScoringEngine
        from analysis.layers.L5_psychology import L5PsychologyAnalyzer
        from analysis.layers.L6_risk import L6RiskAnalyzer
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer
        from analysis.layers.L8_tii_integrity import L8TIIIntegrityAnalyzer
        from analysis.layers.L9_smc import L9SMCAnalyzer
        from analysis.layers.L10_position import L10PositionAnalyzer
        from analysis.layers.L11_rr import L11RRAnalyzer
        from analysis.macro_volatility_engine import MacroVolatilityEngine

        self._l1 = L1ContextAnalyzer()
        self._l2 = L2MTAAnalyzer()
        self._l3 = L3TechnicalAnalyzer()
        self._l4 = L4ScoringEngine()
        self._l5 = L5PsychologyAnalyzer()
        self._l6 = L6RiskAnalyzer()
        self._l7 = L7ProbabilityAnalyzer()
        self._l8 = L8TIIIntegrityAnalyzer()
        self._l9 = L9SMCAnalyzer()
        self._l10 = L10PositionAnalyzer()
        self._l11 = L11RRAnalyzer()
        self._macro_vol = MacroVolatilityEngine()

    def run(self, symbol: str, system_metrics: dict | None = None) -> SovereignResult:
        """
        Execute complete Wolf Sovereign Pipeline.

        Args:
            symbol: Trading pair symbol
            system_metrics: Optional system metrics (latency, safe_mode, etc.)

        Returns:
            SovereignResult with complete pipeline output
        """
        start_time = time.time()
        self._ensure_analyzers()

        errors = []
        system_metrics = system_metrics or {"latency_ms": 50, "safe_mode": False}

        try:
            # ═══════════════════════════════════════════════════════════
            # PHASE 1: Independent Analysis (L1, L2, L3)
            # ═══════════════════════════════════════════════════════════
            logger.info(f"[WolfSovereignPipeline] Phase 1: Independent analysis for {symbol}")

            l1 = self._l1.analyze(symbol)
            if not l1.get("valid"):
                errors.append("L1_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            l2 = self._l2.analyze(symbol)
            if not l2.get("valid"):
                errors.append("L2_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            l3 = self._l3.analyze(symbol)
            if not l3.get("valid"):
                errors.append("L3_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            # ═══════════════════════════════════════════════════════════
            # PHASE 2: Dependent Analysis (L4, L5, L7, L8, L9)
            # ═══════════════════════════════════════════════════════════
            logger.info(f"[WolfSovereignPipeline] Phase 2: Dependent analysis for {symbol}")

            # L4: Scoring (requires L1, L2, L3)
            l4 = self._l4.score(l1, l2, l3)

            # L5: Psychology (requires volatility profile from L2)
            l5 = self._l5.analyze(symbol, volatility_profile=l2)

            # L7: Probability (requires technical score from L4)
            technical_score = l4.get("technical_score", 0)
            l7 = self._l7.analyze(symbol, technical_score=technical_score)

            # Apply VIX multiplier to L7 win probability (FIX for bug #2)
            macro_vix_state = self._macro_vol.get_state()
            vix_risk_multiplier = macro_vix_state.get("risk_multiplier", 1.0)
            if l7.get("win_probability"):
                l7["win_probability"] = l7["win_probability"] * vix_risk_multiplier

            # L8: TII & Integrity (requires L1-L7)
            layers_for_l8 = {
                "l1": l1,
                "l2": l2,
                "l3": l3,
                "l4": l4,
                "l7": l7,
            }
            l8 = self._l8.analyze(layers_for_l8)

            # L9: SMC (requires structure from L3)
            # Use structure analyzer if available, otherwise use L3 output directly
            if hasattr(self._l3, "structure"):
                structure = self._l3.structure.analyze(symbol)
            else:
                # Fallback: L3 output already contains structure data
                structure = l3
            l9 = self._l9.analyze(symbol, structure)

            # ═══════════════════════════════════════════════════════════
            # PHASE 3: Execution + Risk + Sizing (L11 → L6 → L10)
            # ═══════════════════════════════════════════════════════════
            logger.info(f"[WolfSovereignPipeline] Phase 3: Execution + Risk for {symbol}")

            # Determine direction from L2 or L3
            direction = l2.get("direction") or l3.get("bias") or "BUY"
            if direction not in ["BUY", "SELL"]:
                direction = "BUY"  # Default fallback

            # L11: RR Calculation (BEFORE L6, as L6 needs RR)
            l11 = self._l11.calculate_rr(symbol, direction)
            rr_value = l11.get("rr_ratio", 2.0)

            # L6: Risk Check (requires RR from L11)
            l6 = self._l6.analyze(rr=rr_value)

            # L10: Position Feasibility (requires risk_ok from L6, smc_confidence from L9)
            risk_ok = l6.get("risk_ok", False)
            smc_confidence = l9.get("confidence", 0.0)
            l10 = self._l10.analyze(risk_ok, smc_confidence)

            # ═══════════════════════════════════════════════════════════
            # PHASE 4: Build Synthesis → L12 Verdict (SOLE AUTHORITY)
            # ═══════════════════════════════════════════════════════════
            logger.info(f"[WolfSovereignPipeline] Phase 4: Build synthesis and L12 verdict for {symbol}")

            synthesis = build_l12_synthesis(
                symbol=symbol,
                l1=l1,
                l2=l2,
                l3=l3,
                l4=l4,
                l5=l5,
                l6=l6,
                l7=l7,
                l8=l8,
                l9=l9,
                l10=l10,
                l11=l11,
                macro_vix_state=macro_vix_state,
                system_metrics=system_metrics,
            )

            # Call L12 verdict engine as SOLE AUTHORITY (fixes bug #1)
            l12_verdict = generate_l12_verdict(synthesis)

            # ═══════════════════════════════════════════════════════════
            # PHASE 5: Two-Pass Governance (L13 → L15 → L13)
            # ═══════════════════════════════════════════════════════════
            reflective_pass1 = None
            meta = None
            reflective_pass2 = None

            # Early exit if verdict is not EXECUTE (fixes bug #3)
            if not l12_verdict.get("proceed_to_L13", False):
                logger.info(f"[WolfSovereignPipeline] Early exit: verdict={l12_verdict.get('verdict')}")
                latency_ms = (time.time() - start_time) * 1000
                return SovereignResult(
                    symbol=symbol,
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    latency_ms=latency_ms,
                    errors=errors,
                )

            logger.info(f"[WolfSovereignPipeline] Phase 5: Two-pass governance for {symbol}")

            # L13 Pass 1 (meta_integrity = 1.0)
            l13_engine = L13ReflectiveEngine()
            reflective_pass1 = l13_engine.reflect(synthesis, l12_verdict, meta_integrity=1.0)

            # L15 Meta Sovereignty
            l15_engine = L15MetaSovereigntyEngine()
            meta = l15_engine.compute_meta(synthesis, l12_verdict, reflective_pass1)

            # L13 Pass 2 (meta_integrity from L15)
            meta_integrity_value = meta.get("meta_integrity", 1.0)
            reflective_pass2 = l13_engine.reflect(synthesis, l12_verdict, meta_integrity=meta_integrity_value)

            # ═══════════════════════════════════════════════════════════
            # PHASE 6: Sovereignty Enforcement
            # ═══════════════════════════════════════════════════════════
            logger.info(f"[WolfSovereignPipeline] Phase 6: Sovereignty enforcement for {symbol}")

            enforcement = l15_engine.enforce_sovereignty(
                l12_verdict, reflective_pass2, meta
            )

            latency_ms = (time.time() - start_time) * 1000

            return SovereignResult(
                symbol=symbol,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective_pass1=reflective_pass1,
                meta=meta,
                reflective_pass2=reflective_pass2,
                enforcement=enforcement,
                latency_ms=latency_ms,
                errors=errors,
            )

        except Exception as exc:
            logger.error(f"[WolfSovereignPipeline] Fatal error: {exc}", exc_info=True)
            errors.append(f"FATAL_ERROR: {exc}")
            latency_ms = (time.time() - start_time) * 1000
            return SovereignResult(
                symbol=symbol,
                synthesis={},
                l12_verdict={"verdict": "HOLD", "confidence": "LOW"},
                latency_ms=latency_ms,
                errors=errors,
            )

    def _early_exit(self, symbol: str, errors: list[str], elapsed: float) -> SovereignResult:
        """Create early exit result."""
        return SovereignResult(
            symbol=symbol,
            synthesis={},
            l12_verdict={"verdict": "HOLD", "confidence": "LOW", "proceed_to_L13": False},
            latency_ms=elapsed * 1000,
            errors=errors,
        )


def build_l12_synthesis(
    symbol: str,
    l1: dict,
    l2: dict,
    l3: dict,
    l4: dict,
    l5: dict,
    l6: dict,
    l7: dict,
    l8: dict,
    l9: dict,
    l10: dict,
    l11: dict,
    macro_vix_state: dict,
    system_metrics: dict,
) -> dict[str, Any]:
    """
    Build synthesis dict matching generate_l12_verdict() contract EXACTLY.

    Required keys (from constitution/verdict_engine.py):
    - scores: wolf_30_point, f_score, t_score, fta_score, exec_score
    - layers: L8_tii_sym, L8_integrity_index, L7_monte_carlo_win, conf12
    - execution: rr_ratio, direction, entry_price, stop_loss, take_profit_1, entry_zone, risk_percent, risk_amount, lot_size
    - propfirm: compliant
    - risk: current_drawdown
    - bias: fundamental, technical
    - macro_vix: regime_state, risk_multiplier
    - system: latency_ms, safe_mode
    - pair: symbol
    - macro: regime, bias_override (optional)
    """
    # Build wolf_30_point from L4 (handle both dict and int)
    wolf_30_point_data = l4.get("wolf_30_point", {})
    if isinstance(wolf_30_point_data, dict):
        wolf_30_point = wolf_30_point_data.get("total_score", 25)
    else:
        wolf_30_point = int(wolf_30_point_data) if wolf_30_point_data else 25

    # Compute scores
    technical_score = l4.get("technical_score", 75)
    f_score = int(technical_score * 0.10) if technical_score else 7
    t_score = int(technical_score * 0.12) if technical_score else 9
    fta_score = (f_score + t_score) / 20.0  # Normalized to 0-1
    exec_score = 10 if l6.get("risk_ok") and l10.get("position_ok") else 5

    # Compute conf12 (confidence score from layers)
    conf12 = (
        l1.get("csi", 0.9) * 0.20
        + l2.get("alignment_strength", 0.88) * 0.20
        + l8.get("integrity", 0.95) * 0.30
        + l7.get("win_probability", 70) / 100 * 0.30
    )

    # Get direction
    direction = l2.get("direction") or l3.get("bias", "BUY")
    if direction not in ["BUY", "SELL"]:
        direction = "BUY"

    # Get execution details from L11
    entry_price = l11.get("entry", 0.0)
    stop_loss = l11.get("stop_loss", 0.0)
    take_profit_1 = l11.get("take_profit", 0.0)
    rr_ratio = l11.get("rr_ratio", 2.0)

    # Compute entry zone
    if direction == "BUY":
        entry_zone = f"{entry_price - 0.0010:.5f}-{entry_price:.5f}"
    else:
        entry_zone = f"{entry_price:.5f}-{entry_price + 0.0010:.5f}"

    # Risk management
    # NOTE: These are placeholder defaults.
    # In production, risk_amount and lot_size MUST come from dashboard's account state.
    risk_percent = 1.0  # Default 1% per trade
    risk_amount = 100.0  # PLACEHOLDER - should come from account state
    lot_size = 0.01  # PLACEHOLDER - should be computed by dashboard

    # PropFirm compliance (default to True)
    propfirm_compliant = True

    # Current drawdown (from L5 or default)
    current_drawdown = l5.get("current_drawdown", 0.0)

    # Bias
    technical_bias = l3.get("bias", "NEUTRAL")
    fundamental_bias = "NEUTRAL"  # Would come from macro analysis

    # Macro VIX regime
    vix_regime_state = macro_vix_state.get("regime_state", 1)

    synthesis = {
        "pair": symbol,
        "scores": {
            "wolf_30_point": wolf_30_point,
            "f_score": f_score,
            "t_score": t_score,
            "fta_score": fta_score,
            "exec_score": exec_score,
        },
        "layers": {
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
            "L8_tii_sym": l8.get("tii_sym", 0.93),
            "L8_integrity_index": l8.get("integrity", 0.95),
            "L7_monte_carlo_win": l7.get("win_probability", 70) / 100,
            "conf12": conf12,
        },
        "execution": {
            "rr_ratio": rr_ratio,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit_1": take_profit_1,
            "entry_zone": entry_zone,
            "risk_percent": risk_percent,
            "risk_amount": risk_amount,
            "lot_size": lot_size,
        },
        "propfirm": {
            "compliant": propfirm_compliant,
            "violations": [],
        },
        "risk": {
            "current_drawdown": current_drawdown,
            "max_drawdown": 5.0,
        },
        "bias": {
            "fundamental": fundamental_bias,
            "technical": technical_bias,
        },
        "macro_vix": {
            "regime_state": vix_regime_state,
            "risk_multiplier": macro_vix_state.get("risk_multiplier", 1.0),
        },
        "system": {
            "latency_ms": system_metrics.get("latency_ms", 50),
            "safe_mode": system_metrics.get("safe_mode", False),
        },
        "macro": {
            "regime": "UNKNOWN",
            "bias_override": {"active": False},
        },
        # Store raw layers for L13/L15 internal use
        "_raw_layers": {
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
        },
    }

    return synthesis


class L13ReflectiveEngine:
    """
    Two-Pass Safe Reflective Authority.

    Pass 1: meta_integrity = 1.0 (baseline)
    Pass 2: meta_integrity from L15 (adjusted)

    Checks:
    - LRCE (Layer Recursive Coherence): directional alignment across layers
    - FRPC (Fusion Recursive Pattern Check): verdict/bias consistency
    - αβγ (Alpha-Beta-Gamma) quality score
    - Drift ratio from meta_integrity
    """

    def reflect(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        meta_integrity: float = 1.0,
    ) -> dict[str, Any]:
        """
        Run reflective analysis on synthesis and verdict.

        Args:
            synthesis: Synthesis dict from build_l12_synthesis
            l12_verdict: Verdict from generate_l12_verdict
            meta_integrity: Meta integrity value (1.0 for pass 1, L15 value for pass 2)

        Returns:
            Reflective analysis results
        """
        # LRCE: Layer Recursive Coherence (directional alignment)
        lrce_score = self._compute_lrce(synthesis)

        # FRPC: Fusion Recursive Pattern Check (verdict/bias consistency)
        frpc_score = self._compute_frpc(synthesis, l12_verdict)

        # αβγ Quality Score
        alpha = lrce_score  # Directional coherence
        beta = frpc_score  # Pattern consistency
        gamma = meta_integrity  # Meta integrity

        abg_score = alpha * 0.40 + beta * 0.30 + gamma * 0.30

        # Drift ratio
        drift_ratio = 1.0 - meta_integrity

        return {
            "lrce_score": lrce_score,
            "frpc_score": frpc_score,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "abg_score": abg_score,
            "drift_ratio": drift_ratio,
            "meta_integrity": meta_integrity,
            "pass": 2 if meta_integrity < 1.0 else 1,
        }

    def _compute_lrce(self, synthesis: dict[str, Any]) -> float:
        """Compute Layer Recursive Coherence (directional alignment)."""
        layers = synthesis.get("layers", {})
        direction = synthesis.get("execution", {}).get("direction")

        if not direction:
            return 0.5  # Neutral

        # Check alignment across layers
        alignments = []

        # L2 alignment
        l2 = layers.get("L2", {})
        if l2.get("direction") == direction:
            alignments.append(1.0)
        else:
            alignments.append(0.0)

        # L3 bias
        l3 = layers.get("L3", {})
        bias = l3.get("bias", "NEUTRAL")
        if (direction == "BUY" and bias == "BULLISH") or (direction == "SELL" and bias == "BEARISH"):
            alignments.append(1.0)
        elif bias == "NEUTRAL":
            alignments.append(0.5)
        else:
            alignments.append(0.0)

        # L9 SMC
        l9 = layers.get("L9", {})
        if l9.get("smc"):
            alignments.append(1.0)
        else:
            alignments.append(0.5)

        return sum(alignments) / len(alignments) if alignments else 0.5

    def _compute_frpc(self, synthesis: dict[str, Any], l12_verdict: dict[str, Any]) -> float:
        """Compute Fusion Recursive Pattern Check (verdict/bias consistency)."""
        verdict = l12_verdict.get("verdict", "HOLD")
        technical_bias = synthesis.get("bias", {}).get("technical", "NEUTRAL")
        direction = synthesis.get("execution", {}).get("direction")

        # Check if verdict matches bias
        if verdict.startswith("EXECUTE"):
            if direction == "BUY" and technical_bias == "BULLISH":
                return 1.0
            elif direction == "SELL" and technical_bias == "BEARISH":
                return 1.0
            elif technical_bias == "NEUTRAL":
                return 0.7
            else:
                return 0.3
        elif verdict == "HOLD":
            return 0.8 if technical_bias == "NEUTRAL" else 0.5
        else:
            return 0.5


class L15MetaSovereigntyEngine:
    """
    Vault Sync + Execution Rights.

    Computes:
    - Meta integrity (valid layer ratio)
    - Vault sync formula: feed_freshness × 0.50 + redis_health × 0.30 + meta_integrity × 0.20
    - Execution rights: GRANTED / RESTRICTED / REVOKED
    - Drift-adaptive position sizing multiplier
    """

    def __init__(self) -> None:
        """Initialize with thresholds from config."""
        self.vault_sync_min = get_threshold("layers.l15.vault_sync_min", 0.985)
        self.drift_max = get_threshold("layers.l15.drift_max", 0.15)

    def compute_meta(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective_pass1: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute meta integrity and vault sync.

        Args:
            synthesis: Synthesis dict
            l12_verdict: L12 verdict
            reflective_pass1: Reflective pass 1 results

        Returns:
            Meta sovereignty analysis
        """
        # Meta integrity: ratio of valid layers
        layers = synthesis.get("layers", {})
        valid_count = sum(
            1
            for key, layer in layers.items()
            if isinstance(layer, dict) and layer.get("valid")
        )
        total_count = 11  # L1-L11

        meta_integrity = valid_count / total_count if total_count > 0 else 0.0

        # Vault sync formula: feed_freshness × 0.50 + redis_health × 0.30 + meta_integrity × 0.20
        # TODO: Replace with real health checks before production use
        # KNOWN LIMITATION: Using placeholder values for feed_freshness and redis_health
        feed_freshness = 1.0  # PLACEHOLDER - should query LiveContextBus feed age
        redis_health = 1.0  # PLACEHOLDER - should check Redis connection health
        vault_sync = (
            feed_freshness * 0.50 + redis_health * 0.30 + meta_integrity * 0.20
        )

        return {
            "meta_integrity": meta_integrity,
            "valid_layers": valid_count,
            "total_layers": total_count,
            "vault_sync": vault_sync,
            "feed_freshness": feed_freshness,
            "redis_health": redis_health,
        }

    def enforce_sovereignty(
        self,
        l12_verdict: dict[str, Any],
        reflective_pass2: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Enforce sovereignty based on meta integrity and drift.

        Returns:
            Enforcement decision: GRANTED / RESTRICTED / REVOKED
        """
        vault_sync = meta.get("vault_sync", 0.0)
        drift_ratio = reflective_pass2.get("drift_ratio", 0.0)
        abg_score = reflective_pass2.get("abg_score", 0.0)

        # Determine execution rights
        if vault_sync >= self.vault_sync_min and drift_ratio <= self.drift_max:
            execution_rights = "GRANTED"
            lot_multiplier = 1.0
        elif vault_sync >= 0.95 and drift_ratio <= 0.20:
            execution_rights = "RESTRICTED"
            lot_multiplier = 0.5  # Reduce lot size
        else:
            execution_rights = "REVOKED"
            lot_multiplier = 0.0
            # Downgrade verdict to HOLD
            l12_verdict["verdict"] = "HOLD"
            l12_verdict["confidence"] = "LOW"

        return {
            "execution_rights": execution_rights,
            "lot_multiplier": lot_multiplier,
            "vault_sync": vault_sync,
            "drift_ratio": drift_ratio,
            "abg_score": abg_score,
            "reason": self._get_enforcement_reason(execution_rights, vault_sync, drift_ratio),
        }

    def _get_enforcement_reason(
        self, rights: str, vault_sync: float, drift_ratio: float
    ) -> str:
        """Get human-readable enforcement reason."""
        if rights == "GRANTED":
            return "All sovereignty checks passed"
        elif rights == "RESTRICTED":
            return f"Marginal drift (vault={vault_sync:.3f}, drift={drift_ratio:.3f})"
        else:
            return f"Failed sovereignty (vault={vault_sync:.3f}, drift={drift_ratio:.3f})"
