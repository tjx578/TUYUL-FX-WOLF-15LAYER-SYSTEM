"""
Wolf Constitutional Pipeline — Single Canonical Pipeline (v7.4r∞)

This is the SOLE pipeline orchestrator for the entire Wolf 15-Layer System.
Replaces all three existing pipeline paths:
1. main.py → analysis/synthesis.py → constitution/verdict_engine.py
2. reasoning/engine.py (Wolf15LayerEngine)
3. analysis/orchestrators/wolf_sovereign_pipeline.py (WolfSovereignPipeline)

Architecture:
- 3 zones: Perception (L0-L6), Judgement (L7-L11), Constitutional (L12-L14)
- Sequential execution with halt-on-failure
- Uses existing analysis/layers/L1-L11 analyzers
- Uses existing constitution/verdict_engine.py for L12 (SOLE AUTHORITY)
- Outputs L12-contract-compliant synthesis dict
- Integrates vault_sync as 3-component composite (feed, redis, integrity)
- NO HexaVault, NO 6-vault system

Execution order (CRITICAL):
Phase 1: L1, L2, L3 (independent analysis)
Phase 2: L4, L5, L7, L8, L9 (dependent analysis)
Phase 3: L11 (RR) → L6 (risk) → L10 (position) [L11 BEFORE L6!]
Phase 4: Build synthesis → L12 verdict (SOLE AUTHORITY)
Phase 5: L13 reflective pass (only if EXECUTE verdict)
Phase 6: L14 vault sync + sovereignty enforcement
"""

from __future__ import annotations

import time

from typing import Any

from loguru import logger

from constitution.verdict_engine import generate_l12_verdict
from pipeline.constants import get_vault_sync_thresholds, get_vault_sync_weights


class WolfConstitutionalPipeline:
    """
    Single canonical pipeline for Wolf 15-Layer System.

    This is the ONLY entry point for analysis in the entire system.
    """

    def __init__(self) -> None:
        """Initialize with lazy loading to avoid circular imports."""
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

        # Macro analyzers
        self._macro = None
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
        from analysis.macro.monthly_regime import MonthlyRegimeAnalyzer
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
        self._macro = MonthlyRegimeAnalyzer()
        self._macro_vol = MacroVolatilityEngine()

    def execute(self, symbol: str) -> dict[str, Any]:
        """
        Execute complete Wolf Constitutional Pipeline.

        Args:
            symbol: Trading pair symbol (e.g., "EURUSD", "XAUUSD")

        Returns:
            Complete result dict with:
            - synthesis: L12-contract synthesis
            - l12_verdict: Constitutional verdict from generate_l12_verdict()
            - reflective: L13 reflective pass (only if EXECUTE verdict)
            - sovereignty: L14 sovereignty enforcement
            - latency_ms: Pipeline execution time
            - errors: List of any errors encountered
        """
        start_time = time.time()
        self._ensure_analyzers()

        errors = []

        try:
            # ═══════════════════════════════════════════════════════════
            # PHASE 1: Perception Zone (L1, L2, L3) - Independent Analysis
            # ═══════════════════════════════════════════════════════════
            logger.debug(f"[Pipeline] Phase 1: Perception for {symbol}")

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
            # PHASE 2: Judgement Zone (L4, L5, L7, L8, L9) - Dependent Analysis
            # ═══════════════════════════════════════════════════════════
            logger.debug(f"[Pipeline] Phase 2: Judgement for {symbol}")

            # L4: Scoring (requires L1, L2, L3)
            l4 = self._l4.score(l1, l2, l3)

            # L5: Psychology (requires volatility profile from L2)
            l5 = self._l5.analyze(symbol, volatility_profile=l2)

            # L7: Probability (requires technical score from L4)
            technical_score = l4.get("technical_score", 0)
            l7 = self._l7.analyze(symbol, technical_score=technical_score)

            # Apply VIX multiplier to L7 win probability
            macro_vix_state = self._macro_vol.get_state()
            vix_risk_multiplier = macro_vix_state.get("risk_multiplier", 1.0)
            if l7.get("win_probability"):
                l7_adjusted = l7.copy()
                l7_adjusted["win_probability"] = l7["win_probability"] * vix_risk_multiplier
                l7 = l7_adjusted

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
            if hasattr(self._l3, "structure"):
                structure = self._l3.structure.analyze(symbol)
            else:
                structure = l3
            l9 = self._l9.analyze(symbol, structure)

            # ═══════════════════════════════════════════════════════════
            # PHASE 3: Execution + Risk (L11 → L6 → L10)
            # CRITICAL: L11 BEFORE L6 (L6 needs RR from L11)
            # ═══════════════════════════════════════════════════════════
            logger.debug(f"[Pipeline] Phase 3: Execution + Risk for {symbol}")

            # Determine direction from L3 trend
            trend = l3.get("trend", "NEUTRAL")
            if trend == "BULLISH":
                direction = "BUY"
            elif trend == "BEARISH":
                direction = "SELL"
            else:
                direction = "HOLD"

            # L11: RR Calculation (BEFORE L6!)
            l11 = {"valid": False, "rr": 2.0}
            if direction in ["BUY", "SELL"]:
                l11 = self._l11.calculate_rr(symbol, direction)
                rr_value = l11.get("rr", 2.0)
            else:
                rr_value = 2.0

            # L6: Risk Check (requires RR from L11)
            l6 = self._l6.analyze(rr=rr_value)

            # L10: Position Feasibility (requires risk_ok from L6, confidence from L9)
            risk_ok = l6.get("risk_ok", False)
            smc_confidence = l9.get("confidence", 0.0)
            l10 = self._l10.analyze(risk_ok, smc_confidence)

            # Macro regime analysis
            macro = self._macro.analyze(symbol)

            # ═══════════════════════════════════════════════════════════
            # PHASE 4: Build Synthesis → L12 Verdict (SOLE AUTHORITY)
            # ═══════════════════════════════════════════════════════════
            logger.debug(f"[Pipeline] Phase 4: Build synthesis + L12 verdict for {symbol}")

            synthesis = self._build_synthesis(
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
                macro=macro,
                macro_vix_state=macro_vix_state,
            )

            # Call L12 verdict engine as SOLE AUTHORITY
            l12_verdict = generate_l12_verdict(synthesis)

            # ═══════════════════════════════════════════════════════════
            # PHASE 5: L13 Reflective Pass (only if EXECUTE verdict)
            # ═══════════════════════════════════════════════════════════
            reflective = None
            if l12_verdict.get("verdict", "").startswith("EXECUTE"):
                logger.debug(f"[Pipeline] Phase 5: Reflective pass for {symbol}")
                reflective = self._run_reflective_pass(synthesis, l12_verdict)

            # ═══════════════════════════════════════════════════════════
            # PHASE 6: L14 Vault Sync + Sovereignty Enforcement
            # ═══════════════════════════════════════════════════════════
            logger.debug(f"[Pipeline] Phase 6: Sovereignty enforcement for {symbol}")
            sovereignty = self._compute_sovereignty(synthesis, l12_verdict, reflective)

            latency_ms = (time.time() - start_time) * 1000

            return {
                "synthesis": synthesis,
                "l12_verdict": l12_verdict,
                "reflective": reflective,
                "sovereignty": sovereignty,
                "latency_ms": latency_ms,
                "errors": errors,
            }

        except Exception as exc:
            logger.error(f"[Pipeline] Fatal error for {symbol}: {exc}", exc_info=True)
            errors.append(f"FATAL_ERROR: {exc}")
            latency_ms = (time.time() - start_time) * 1000
            return self._early_exit(symbol, errors, latency_ms)

    def _build_synthesis(
        self,
        symbol: str,
        l1: dict[str, Any],
        l2: dict[str, Any],
        l3: dict[str, Any],
        l4: dict[str, Any],
        l5: dict[str, Any],
        l6: dict[str, Any],
        l7: dict[str, Any],
        l8: dict[str, Any],
        l9: dict[str, Any],
        l10: dict[str, Any],
        l11: dict[str, Any],
        macro: dict[str, Any],
        macro_vix_state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build L12-contract-compliant synthesis from layer outputs.

        This matches the exact contract expected by generate_l12_verdict().
        """
        # Compute wolf_30_point score (0-30) from L4 breakdown if available
        if "wolf_30_point" in l4 and isinstance(l4["wolf_30_point"], dict):
            wolf_30_point = l4["wolf_30_point"].get("total", 0)
            f_score = l4["wolf_30_point"].get("f_score", 0)
            t_score = l4["wolf_30_point"].get("t_score", 0)
        else:
            # Fallback to old calculation method
            technical_score = l4.get("technical_score", 0)
            win_prob = l7.get("win_probability", 0)
            wolf_30_point = int((technical_score / 100) * 15 + (win_prob / 100) * 15)
            wolf_30_point = max(0, min(30, wolf_30_point))
            f_score = 0
            t_score = 0

        # Compute FTA score (fundamental-technical alignment) 0.0-1.0
        l1_valid = l1.get("valid", False)
        l2_valid = l2.get("valid", False)
        l3_valid = l3.get("valid", False)
        valid_count = sum([l1_valid, l2_valid, l3_valid])
        fta_score = valid_count / 3.0

        # Compute execution readiness score (0-10)
        exec_score = 10 if l10.get("position_ok", False) else 5

        # Determine direction from L3 trend
        trend = l3.get("trend", "NEUTRAL")
        if trend == "BULLISH":
            direction = "BUY"
        elif trend == "BEARISH":
            direction = "SELL"
        else:
            direction = "HOLD"

        # Get execution details from L11
        entry_price = l11.get("entry", l11.get("entry_price", 1.1000))
        stop_loss = l11.get("stop_loss", l11.get("sl", 1.0950))
        take_profit_1 = l11.get("take_profit_1", l11.get("tp1", l11.get("tp", 1.1100)))
        rr_ratio = l11.get("rr", 2.0)

        # Compute entry zone
        if direction == "BUY":
            entry_zone = f"{entry_price - 0.0010:.5f}-{entry_price:.5f}"
        else:
            entry_zone = f"{entry_price:.5f}-{entry_price + 0.0010:.5f}"

        # Risk management (defaults - production should use RiskManager)
        # TODO: Issue #XXX - Integrate real RiskManager from dashboard before production
        # These placeholder values MUST be replaced with account-level risk state
        lot_size = 0.01  # PLACEHOLDER - should come from dashboard
        risk_percent = 0.01  # 1% - PLACEHOLDER
        risk_amount = 100.0  # PLACEHOLDER - should come from account state

        # PropFirm compliance (default to True)
        prop_compliant = True

        # Current drawdown
        current_drawdown = l5.get("current_drawdown", 0.0)

        # Compute confidence index (conf12)
        tii_sym = l8.get("tii_sym", 0.5)
        integrity = l8.get("integrity", 0.5)
        conf12 = (tii_sym + integrity) / 2.0

        # VIX regime
        vix_regime_state = macro_vix_state.get("regime_state", 1)

        return {
            "pair": symbol,
            "scores": {
                "wolf_30_point": wolf_30_point,
                "f_score": f_score,
                "t_score": t_score,
                "fta_score": fta_score,
                "exec_score": exec_score,
            },
            "layers": {
                "L8_tii_sym": tii_sym,
                "L8_integrity_index": integrity,
                "L7_monte_carlo_win": l7.get("win_probability", 70) / 100,
                "conf12": conf12,
            },
            "execution": {
                "direction": direction,
                "entry": entry_price,
                "entry_zone": entry_zone,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit_1": take_profit_1,
                "take_profit": take_profit_1,  # Backwards compatibility
                "rr_ratio": rr_ratio,
                "lot_size": lot_size,
                "risk_percent": risk_percent,
                "risk_amount": risk_amount,
            },
            "risk": {
                "current_drawdown": current_drawdown,
            },
            "propfirm": {
                "compliant": prop_compliant,
            },
            "bias": {
                "fundamental": "NEUTRAL" if not l1_valid else trend,
                "technical": trend,
                "macro": macro.get("regime", "UNKNOWN"),
            },
            "macro": {
                "regime": macro.get("regime", "UNKNOWN"),
                "phase": macro.get("phase", "NEUTRAL"),
                "volatility_ratio": macro.get("macro_vol_ratio", 1.0),
                "mn_aligned": macro.get("alignment", False),
                "liquidity": macro.get("liquidity", {}),
                "bias_override": macro.get("bias_override", {}),
            },
            "macro_vix": {
                "regime_state": vix_regime_state,
                "risk_multiplier": macro_vix_state.get("risk_multiplier", 1.0),
            },
            "system": {
                "latency_ms": 0,  # Will be injected by caller
            },
        }

    def _run_reflective_pass(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        """
        L13: Reflective pass (LRCE + FRPC + αβγ quality score).

        Only runs if L12 verdict is EXECUTE.

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
        gamma = 1.0  # Meta integrity (computed in L14)

        abg_score = alpha * 0.40 + beta * 0.30 + gamma * 0.30

        return {
            "lrce_score": lrce_score,
            "frpc_score": frpc_score,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "abg_score": abg_score,
        }

    def _is_direction_aligned_with_bias(self, direction: str, technical_bias: str) -> bool:
        """
        Check if direction is aligned with technical bias.

        Args:
            direction: Trade direction (BUY/SELL)
            technical_bias: Technical bias (BULLISH/BEARISH/NEUTRAL)

        Returns:
            True if aligned, False otherwise
        """
        if direction == "BUY" and technical_bias == "BULLISH":
            return True
        elif direction == "SELL" and technical_bias == "BEARISH":
            return True
        return False

    def _compute_lrce(self, synthesis: dict[str, Any]) -> float:
        """Compute Layer Recursive Coherence (directional alignment)."""
        direction = synthesis.get("execution", {}).get("direction")
        technical_bias = synthesis.get("bias", {}).get("technical", "NEUTRAL")

        if not direction or direction == "HOLD":
            return 0.5

        # Check alignment
        if self._is_direction_aligned_with_bias(direction, technical_bias):
            return 1.0
        if technical_bias == "NEUTRAL":
            return 0.7
        return 0.3

    def _compute_frpc(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> float:
        """Compute Fusion Recursive Pattern Check (verdict/bias consistency)."""
        verdict = l12_verdict.get("verdict", "HOLD")
        technical_bias = synthesis.get("bias", {}).get("technical", "NEUTRAL")
        direction = synthesis.get("execution", {}).get("direction")

        # Check if verdict matches bias
        if verdict.startswith("EXECUTE"):
            if self._is_direction_aligned_with_bias(direction, technical_bias):
                return 1.0
            if technical_bias == "NEUTRAL":
                return 0.7
            return 0.3
        if verdict == "HOLD":
            return 0.8 if technical_bias == "NEUTRAL" else 0.5
        return 0.5

    def _compute_sovereignty(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        L14: Compute vault sync (3-component) + sovereignty enforcement.

        Vault sync formula: feed × 0.50 + redis × 0.30 + integrity × 0.20

        Returns:
            Sovereignty enforcement decision
        """
        # Get vault sync weights from config
        weights = get_vault_sync_weights()
        thresholds = get_vault_sync_thresholds()

        # Compute 3-component vault sync
        # TODO: Issue #XXX - Implement real health checks before production deployment
        # CRITICAL: These are placeholder values for feed_freshness and redis_health
        # Production MUST implement:
        # - feed_freshness: query LiveContextBus.get_feed_age() and compute freshness score
        # - redis_health: check Redis connection health via ping/info commands
        # - meta_integrity: compute from layer validity ratio (see L15MetaSovereigntyEngine)
        feed_freshness = 1.0  # PLACEHOLDER - should query LiveContextBus
        redis_health = 1.0  # PLACEHOLDER - should check Redis health
        meta_integrity = 1.0  # PLACEHOLDER - should compute from layer validity

        vault_sync = (
            feed_freshness * weights["feed"]
            + redis_health * weights["redis"]
            + meta_integrity * weights["integrity"]
        )

        # Determine execution rights based on vault_sync
        if vault_sync >= thresholds["strict"]:
            execution_rights = "GRANTED"
            lot_multiplier = 1.0
        elif vault_sync >= thresholds["operational"]:
            execution_rights = "RESTRICTED"
            lot_multiplier = 0.7
        elif vault_sync >= thresholds["critical"]:
            execution_rights = "RESTRICTED"
            lot_multiplier = 0.5
        else:
            execution_rights = "REVOKED"
            lot_multiplier = 0.0

        return {
            "execution_rights": execution_rights,
            "lot_multiplier": lot_multiplier,
            "vault_sync": vault_sync,
            "feed_freshness": feed_freshness,
            "redis_health": redis_health,
            "meta_integrity": meta_integrity,
            "weights": weights,
            "thresholds": thresholds,
        }

    def _early_exit(
        self,
        symbol: str,
        errors: list[str],
        latency_ms: float,
    ) -> dict[str, Any]:
        """Create early exit result when pipeline fails."""
        return {
            "synthesis": {
                "pair": symbol,
                "scores": {"wolf_30_point": 0, "f_score": 0, "t_score": 0, "fta_score": 0.0, "exec_score": 0},
                "layers": {"L8_tii_sym": 0.0, "L8_integrity_index": 0.0, "L7_monte_carlo_win": 0.0, "conf12": 0.0},
                "execution": {
                    "direction": "HOLD",
                    "entry_price": 0.0,
                    "stop_loss": 0.0,
                    "take_profit_1": 0.0,
                    "entry_zone": "0.00000-0.00000",
                    "rr_ratio": 0.0,
                    "lot_size": 0.0,
                    "risk_percent": 0.0,
                    "risk_amount": 0.0,
                },
                "risk": {"current_drawdown": 0.0},
                "propfirm": {"compliant": False},
                "bias": {"fundamental": "NEUTRAL", "technical": "NEUTRAL", "macro": "UNKNOWN"},
                "macro": {"regime": "UNKNOWN", "phase": "NEUTRAL", "volatility_ratio": 1.0, "mn_aligned": False, "liquidity": {}, "bias_override": {}},
                "system": {"latency_ms": latency_ms},
            },
            "l12_verdict": {
                "verdict": "HOLD",
                "confidence": "LOW",
                "wolf_status": "NO_HUNT",
                "gates": {"passed": 0, "total": 10},
                "proceed_to_L13": False,
            },
            "reflective": None,
            "sovereignty": {
                "execution_rights": "REVOKED",
                "lot_multiplier": 0.0,
                "vault_sync": 0.0,
            },
            "latency_ms": latency_ms,
            "errors": errors,
        }
