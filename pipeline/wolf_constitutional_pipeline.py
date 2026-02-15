"""
Wolf Constitutional Pipeline v7.4r∞ - UNIFIED CORE MODULES INTEGRATION

SOLE pipeline orchestrator for the Wolf 15-Layer System.
This is the ONE AND ONLY analysis pipeline in the entire repository.

══════════════════════════════════════════════════════════════════════
4 Core Unified Modules × 15 Analytical Layers × Complete Pipeline
══════════════════════════════════════════════════════════════════════

Core Modules:
    1. core_cognitive_unified.py    → Emotion, Regime, Risk, TWMS, SMC
    2. core_fusion_unified.py       → Fusion, MTF, Confluence, WLWCI, MC
    3. core_quantum_unified.py      → TRQ3D, Decision Engine, Scenario Matrix
    4. core_reflective_unified.py   → TII, FRPC, Wolf Discipline, Evolution

15-Layer Architecture:
    ZONA 1 - Perception & Context   : L1, L2, L3
    ZONA 2 - Confluence & Scoring   : L4, L5, L6
    ZONA 3 - Probability & Validation: L7, L8, L9
    ZONA 4 - Execution & Decision   : L10, L11, L12 (SOLE AUTHORITY)
    ZONA 5 - Meta & Reflective      : L13, L14, L15

Execution order (CRITICAL):
    Phase 1: L1, L2, L3 (Perception - independent)
    Phase 2: L4, L5 (Confluence & Psychology - depend on L1-L3)
    Phase 3: L7, L8, L9 (Probability & Validation - depend on L4/L5)
    Phase 4: L11 → L6 → L10 (Execution + Risk - L11 BEFORE L6!)
    Phase 5: Build synthesis → L12 verdict (SOLE AUTHORITY)
    Phase 6: L13 reflective pass (only if EXECUTE verdict)
    Phase 7: L14 JSON export + L15 meta synthesis

Authority: Layer-12 is the SOLE CONSTITUTIONAL AUTHORITY.
Discipline: Wolf 30-Point + F-T-P Trias.
Integrity: TIIₛᵧₘ ≥ 0.93 | FRPC ≥ 0.96 | RR ≥ 1:2.0
"""

from __future__ import annotations

import time

from datetime import datetime, timedelta, timezone
from typing import Any

from constitution.verdict_engine import generate_l12_verdict
from pipeline.constants import (
    get_conf12_min,
    get_integrity_min,
    get_max_drawdown,
    get_max_latency_ms,
    get_monte_min,
    get_rr_min,
    get_tii_min,
    get_vault_sync_thresholds,
    get_vault_sync_weights,
)

try:
    from loguru import logger  # pyright: ignore[reportMissingImports]
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ─── GMT+8 timezone for timestamps ───
_TZ_GMT8 = timezone(timedelta(hours=8))


class WolfConstitutionalPipeline:
    """
    Wolf 15-Layer Constitutional Pipeline v7.4r∞.

    This is the ONLY entry point for analysis in the entire system.
    All 15 layers (L1-L15) are executed sequentially with halt-on-failure.
    Layer-12 is the SOLE decision authority (Constitutional Verdict).
    """

    VERSION = "v7.4r∞"

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

    # ──────────────────────────────────────────────────────
    #  Lazy-load all layer analyzers
    # ──────────────────────────────────────────────────────

    def _ensure_analyzers(self) -> None:
        """Lazy load analyzers to avoid circular imports."""
        if self._l1 is not None:
            return

        import analysis.layers.L10_execution  # pyright: ignore[reportMissingImports]  # noqa: PLC0415
        import analysis.macro_volatility_engine  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

        from analysis.layers.L4_scoring import (  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
            L4ScoringEngine,  # pyright: ignore[reportMissingImports]
        )
        from analysis.layers.L5_psychology import (  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
            L5PsychologyAnalyzer,  # pyright: ignore[reportMissingImports]
        )

        from analysis.layers.L1_context import (  # noqa: PLC0415
            L1ContextAnalyzer,  # pyright: ignore[reportAttributeAccessIssue]
        )
        from analysis.layers.L2_mta import L2MTAAnalyzer  # noqa: PLC0415
        from analysis.layers.L3_technical import L3TechnicalAnalyzer  # noqa: PLC0415
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
        self._l10 = analysis.layers.L10_execution.L10PositionAnalyzer()
        self._l11 = L11RRAnalyzer()
        self._macro = MonthlyRegimeAnalyzer()
        self._macro_vol = analysis.macro_volatility_engine.MacroVolatilityEngine()

    # ══════════════════════════════════════════════════════════════
    #  MAIN EXECUTE - the single canonical entry point
    # ══════════════════════════════════════════════════════════════

    def execute(self, symbol: str) -> dict[str, Any]:
        """
        Execute complete Wolf 15-Layer Constitutional Pipeline.

        Args:
            symbol: Trading pair symbol (e.g., "EURUSD", "XAUUSD")

        Returns:
            Complete v7.4r∞ result dict with:
            - schema: pipeline version
            - pair, timestamp
            - synthesis: L12-contract synthesis (all layer data)
            - l12_verdict: Constitutional verdict (SOLE AUTHORITY)
            - reflective: L13 reflective pass (only if EXECUTE)
            - l14_json: Full L14 JSON export
            - l15_meta: L15 meta synthesis (full unity state)
            - sovereignty: vault sync + sovereignty enforcement
            - latency_ms: Pipeline execution time
            - errors: List of any errors encountered
        """
        start_time = time.time()
        self._ensure_analyzers()
        errors: list[str] = []
        now = datetime.now(_TZ_GMT8)

        try:
            # ═══════════════════════════════════════════════════════
            # PHASE 1 - ZONA PERCEPTION & CONTEXT (L1, L2, L3)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v7.4r∞] Phase 1: Perception & Context - {symbol}")

            l1 = self._l1.analyze(symbol) # pyright: ignore[reportOptionalMemberAccess]
            if not l1.get("valid"):
                errors.append("L1_CONTEXT_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            l2 = self._l2.analyze(symbol) # pyright: ignore[reportOptionalMemberAccess]
            if not l2.get("valid"):
                errors.append("L2_MTA_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            l3 = self._l3.analyze(symbol) # pyright: ignore[reportOptionalMemberAccess]
            if not l3.get("valid"):
                errors.append("L3_TECHNICAL_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            # ═══════════════════════════════════════════════════════
            # PHASE 2 - ZONA CONFLUENCE & SCORING (L4, L5)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v7.4r∞] Phase 2: Confluence & Scoring - {symbol}")

            # L4: Wolf 30-Point Scoring (requires L1, L2, L3)
            l4 = self._l4.score(l1, l2, l3) # pyright: ignore[reportOptionalMemberAccess]

            # L5: Psychology Gates + RGO Governance
            l5 = self._l5.analyze(symbol, volatility_profile=l2) # pyright: ignore[reportOptionalMemberAccess]

            # ═══════════════════════════════════════════════════════
            # PHASE 3 - ZONA PROBABILITY & VALIDATION (L7, L8, L9)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v7.4r∞] Phase 3: Probability & Validation - {symbol}")

            # L7: Monte Carlo FTTC Validation
            technical_score = l4.get("technical_score", 0)
            l7 = self._l7.analyze(symbol, technical_score=technical_score) # pyright: ignore[reportOptionalMemberAccess]

            # Apply VIX multiplier to L7 win probability
            macro_vix_state = self._macro_vol.get_state() # pyright: ignore[reportOptionalMemberAccess]
            vix_risk_multiplier = macro_vix_state.get("risk_multiplier", 1.0)
            if l7.get("win_probability"):
                l7_adjusted = l7.copy()
                l7_adjusted["win_probability"] = l7["win_probability"] * vix_risk_multiplier
                l7 = l7_adjusted

            # L8: TIIₛᵧₘ Algo Precision Engine (CRITICAL GATE)
            layers_for_l8 = {
                "l1": l1, "l2": l2, "l3": l3, "l4": l4, "l7": l7,
            }
            l8 = self._l8.analyze(layers_for_l8) # pyright: ignore[reportOptionalMemberAccess]

            # L9: SMC Integration Analysis
            if hasattr(self._l3, "structure"):
                structure = self._l3.structure.analyze(symbol) # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]
            else:
                structure = l3
            l9 = self._l9.analyze(symbol, structure) # pyright: ignore[reportOptionalMemberAccess]

            # ═══════════════════════════════════════════════════════
            # PHASE 4 - ZONA EXECUTION & DECISION (L11 → L6 → L10)
            # CRITICAL: L11 BEFORE L6 (L6 needs RR from L11)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v7.4r∞] Phase 4: Execution & Decision - {symbol}")

            # Determine direction from L3 trend
            trend = l3.get("trend", "NEUTRAL")
            if trend == "BULLISH":
                direction = "BUY"
            elif trend == "BEARISH":
                direction = "SELL"
            else:
                direction = "HOLD"

            # L11: Risk-Reward Optimization + Battle Strategy (BEFORE L6!)
            l11: dict[str, Any] = {"valid": False, "rr": 0.0}
            if direction in ("BUY", "SELL"):
                l11 = self._l11.calculate_rr(symbol, direction) # pyright: ignore[reportOptionalMemberAccess]
            rr_value = l11.get("rr", 0.0)

            # L6: Risk Management + Lorentzian Stabilization
            l6 = self._l6.analyze(rr=rr_value) # pyright: ignore[reportOptionalMemberAccess]

            # L10: Position Sizing & FTA Multiplier
            risk_ok = l6.get("risk_ok", False)
            smc_confidence = l9.get("confidence", 0.0)
            l10 = self._l10.analyze(risk_ok, smc_confidence) # pyright: ignore[reportOptionalMemberAccess]

            # Macro regime analysis
            macro = self._macro.analyze(symbol) # pyright: ignore[reportOptionalMemberAccess]

            # ═══════════════════════════════════════════════════════
            # PHASE 5 - L12 CONSTITUTIONAL VERDICT (SOLE AUTHORITY)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v7.4r∞] Phase 5: Constitutional Verdict - {symbol}")

            synthesis = self._build_synthesis(
                symbol=symbol,
                l1=l1, l2=l2, l3=l3, l4=l4, l5=l5,
                l6=l6, l7=l7, l8=l8, l9=l9, l10=l10, l11=l11,
                macro=macro,
                macro_vix_state=macro_vix_state,
            )

            # 9-Gate Constitutional Check
            gates = self._evaluate_9_gates(synthesis, l8, l7, l2, l6, l9, l11, start_time)

            # Call L12 verdict engine as SOLE AUTHORITY
            l12_verdict = generate_l12_verdict(synthesis)

            # Inject 9-gate results into verdict
            l12_verdict["gates_v74"] = gates

            # ═══════════════════════════════════════════════════════
            # PHASE 6 - L13 REFLECTIVE EXECUTION (only if EXECUTE)
            # ═══════════════════════════════════════════════════════
            reflective = None
            if l12_verdict.get("verdict", "").startswith("EXECUTE"):
                logger.info(f"[Pipeline v7.4r∞] Phase 6: Reflective Execution - {symbol}")
                reflective = self._run_reflective_pass(synthesis, l12_verdict)

            # ═══════════════════════════════════════════════════════
            # PHASE 7 - L14 JSON OUTPUT + L15 META SYNTHESIS
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v7.4r∞] Phase 7: L14/L15 - {symbol}")

            sovereignty = self._compute_sovereignty(synthesis, l12_verdict, reflective)
            latency_ms = (time.time() - start_time) * 1000

            l14_json = self._build_l14_json(
                symbol=symbol,
                now=now,
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective=reflective,
                gates=gates,
                l1=l1, l2=l2, l3=l3, l5=l5, l6=l6,
                l8=l8, l9=l9, l10=l10, l11=l11,
                sovereignty=sovereignty,
                latency_ms=latency_ms,
            )

            l15_meta = self._build_l15_meta(
                synthesis=synthesis,
                l12_verdict=l12_verdict,
                reflective=reflective,
                sovereignty=sovereignty,
                gates=gates,
            )

            return {
                "schema": self.VERSION,
                "pair": symbol,
                "timestamp": now.isoformat(),
                "synthesis": synthesis,
                "l12_verdict": l12_verdict,
                "reflective": reflective,
                "l14_json": l14_json,
                "l15_meta": l15_meta,
                "sovereignty": sovereignty,
                "latency_ms": latency_ms,
                "errors": errors,
            }

        except Exception as exc:
            logger.error(f"[Pipeline v7.4r∞] Fatal error for {symbol}: {exc}", exc_info=True)
            errors.append(f"FATAL_ERROR: {exc}")
            latency_ms = (time.time() - start_time) * 1000
            return self._early_exit(symbol, errors, latency_ms)

    # ══════════════════════════════════════════════════════════════
    #  BUILD SYNTHESIS - L12-contract payload from L1-L11
    # ══════════════════════════════════════════════════════════════

    def _build_synthesis(  # noqa: PLR0913
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

        Matches the exact contract expected by generate_l12_verdict().
        """
        # ── Wolf 30-Point from L4 ──
        if "wolf_30_point" in l4 and isinstance(l4["wolf_30_point"], dict):
            wolf_30_point = l4["wolf_30_point"].get("total", 0)
            f_score = l4["wolf_30_point"].get("f_score", 0)
            t_score = l4["wolf_30_point"].get("t_score", 0)
            fta_score_raw = l4["wolf_30_point"].get("fta_score", 0.0)
            exec_score = l4["wolf_30_point"].get("exec_score", 0)
        else:
            technical_score = l4.get("technical_score", 0)
            win_prob = l7.get("win_probability", 0)
            wolf_30_point = int((technical_score / 100) * 15 + (win_prob / 100) * 15)
            wolf_30_point = max(0, min(30, wolf_30_point))
            f_score = 0
            t_score = 0
            fta_score_raw = 0.0
            exec_score = 0

        # ── FTA Score (enriched from L10 or fallback) ──
        fta_score = l10.get("fta_score", fta_score_raw)
        fta_multiplier = l10.get("fta_multiplier", 1.0)
        if exec_score == 0:
            exec_score = 6 if l10.get("position_ok", False) else 0

        # ── Direction from L3 ──
        trend = l3.get("trend", "NEUTRAL")
        direction = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(trend, "HOLD")

        # ── Execution details from L11 ──
        entry_price = l11.get("entry_price", l11.get("entry", 0.0))
        stop_loss = l11.get("stop_loss", l11.get("sl", 0.0))
        take_profit_1 = l11.get("take_profit_1", l11.get("tp1", l11.get("tp", 0.0)))
        rr_ratio = l11.get("rr", 0.0)
        battle_strategy = l11.get("battle_strategy", "SHADOW_STRIKE")
        entry_zone = l11.get("entry_zone", "")
        if not entry_zone and entry_price > 0:
            if direction == "BUY":
                entry_zone = f"{entry_price - 0.0010:.5f}-{entry_price:.5f}"
            else:
                entry_zone = f"{entry_price:.5f}-{entry_price + 0.0010:.5f}"

        # ── Risk (from L10/dashboard - placeholders) ──
        lot_size = l10.get("final_lot_size", 0.01)
        risk_percent = l10.get("adjusted_risk_pct", 1.0)
        risk_amount = l10.get("adjusted_risk_amount", 0.0)

        # ── Metrics ──
        tii_sym = l8.get("tii_sym", 0.0)
        integrity = l8.get("integrity", 0.0)
        conf12 = l2.get("conf12", (tii_sym + integrity) / 2.0)
        current_drawdown = l5.get("current_drawdown", 0.0)
        prop_compliant = l6.get("propfirm_compliant", True)
        psychology_score = l5.get("psychology_score", 0)
        eaf_score = l5.get("eaf_score", 0.0)

        vix_regime_state = macro_vix_state.get("regime_state", 1)

        return {
            "pair": symbol,
            "scores": {
                "wolf_30_point": wolf_30_point,
                "f_score": f_score,
                "t_score": t_score,
                "fta_score": fta_score,
                "fta_multiplier": fta_multiplier,
                "exec_score": exec_score,
                "psychology_score": psychology_score,
                "technical_score": l4.get("technical_score", 0),
            },
            "layers": {
                "L1_context_coherence": l1.get("regime_confidence", 0.0),
                "L2_reflex_coherence": l2.get("reflex_coherence", 0.0),
                "L3_trq3d_energy": l3.get("trq3d_energy", 0.0),
                "L7_monte_carlo_win": l7.get("win_probability", 0.0) / 100.0
                if l7.get("win_probability", 0.0) > 1.0
                else l7.get("win_probability", 0.0),
                "L8_tii_sym": tii_sym,
                "L8_integrity_index": integrity,
                "L9_dvg_confidence": l9.get("dvg_confidence", 0.0),
                "L9_liquidity_score": l9.get("liquidity_score", 0.0),
                "conf12": conf12,
            },
            "execution": {
                "direction": direction,
                "entry_price": entry_price,
                "entry_zone": entry_zone,
                "stop_loss": stop_loss,
                "take_profit_1": take_profit_1,
                "execution_mode": "TP1_ONLY",
                "battle_strategy": battle_strategy,
                "rr_ratio": rr_ratio,
                "lot_size": lot_size,
                "risk_percent": risk_percent,
                "risk_amount": risk_amount,
                "slippage_estimate": 0.0,
                "optimal_timing": "",
            },
            "risk": {
                "current_drawdown": current_drawdown,
                "drawdown_level": l6.get("drawdown_level", "LEVEL_0"),
                "risk_multiplier": l6.get("risk_multiplier", 1.0),
                "risk_status": l6.get("risk_status", "ACCEPTABLE"),
                "lrce": l6.get("lrce", 0.0),
            },
            "propfirm": {
                "compliant": prop_compliant,
                "daily_loss_status": "OK",
                "max_drawdown_status": "OK",
                "profit_target_progress": 0.0,
            },
            "bias": {
                "fundamental": "NEUTRAL" if not l1.get("valid") else trend,
                "technical": trend,
                "macro": macro.get("regime", "UNKNOWN"),
            },
            "cognitive": {
                "regime": l1.get("regime", "TREND"),
                "dominant_force": l1.get("dominant_force", "NEUTRAL"),
                "cbv": l1.get("csi", 0.0),
                "csi": l1.get("regime_confidence", 0.0),
            },
            "fusion_frpc": {
                "conf12": conf12,
                "frpc_energy": l2.get("frpc_energy", 0.0),
                "lambda_esi": 0.003,
                "integrity": integrity,
            },
            "trq3d": {
                "alpha": 0.0,
                "beta": 0.0,
                "gamma": 0.0,
                "drift": l3.get("drift", 0.0),
                "mean_energy": l3.get("trq3d_energy", 0.0),
                "intensity": 0.0,
            },
            "smc": {
                "structure": "RANGE",
                "smart_money_signal": l9.get("smart_money_signal", "NEUTRAL"),
                "liquidity_zone": "0.00000",
                "ob_present": l9.get("ob_present", False),
                "fvg_present": l9.get("fvg_present", False),
                "sweep_detected": l9.get("sweep_detected", False),
                "bias": l9.get("smart_money_bias", "NEUTRAL"),
            },
            "wolf_discipline": {
                "score": wolf_30_point / 30.0 if wolf_30_point else 0.0,
                "polarity_deviation": l5.get("emotion_delta", 0.0),
                "lambda_balance": "ACTIVE",
                "bias_symmetry": "NEUTRAL",
                "eaf_score": eaf_score,
                "emotional_state": "CALM",
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
                "latency_ms": 0,
            },
        }

    # ══════════════════════════════════════════════════════════════
    #  9-GATE CONSTITUTIONAL CHECK
    # ══════════════════════════════════════════════════════════════

    def _evaluate_9_gates(
        self,
        synthesis: dict[str, Any],
        l8: dict[str, Any],
        l7: dict[str, Any],
        l2: dict[str, Any],
        l6: dict[str, Any],
        l9: dict[str, Any],
        l11: dict[str, Any],
        start_time: float,
    ) -> dict[str, Any]:
        """
        9-Gate Constitutional Check for L12.

        GATE 1: TIIₛᵧₘ ≥ 0.93
        GATE 2: Monte Carlo ≥ 60%
        GATE 3: FRPC State = SYNC
        GATE 4: CONF₁₂ ≥ 0.75
        GATE 5: RR ≥ 1:2.0
        GATE 6: Integrity ≥ 0.97
        GATE 7: PropFirm Compliant
        GATE 8: Drawdown ≤ 2.5%
        GATE 9: Latency ≤ 250ms
        """
        tii = l8.get("tii_sym", 0.0)
        win_pct = l7.get("win_probability", 0.0)
        frpc_state = l2.get("frpc_state", "DESYNC")
        conf12 = synthesis.get("layers", {}).get("conf12", 0.0)
        rr = l11.get("rr", 0.0)
        integrity = l8.get("integrity", 0.0)
        compliant = l6.get("propfirm_compliant", True)
        drawdown = synthesis.get("risk", {}).get("current_drawdown", 0.0)
        latency = (time.time() - start_time) * 1000

        g1 = tii >= get_tii_min()
        g2 = win_pct >= (get_monte_min() * 100)
        g3 = frpc_state == "SYNC"
        g4 = conf12 >= get_conf12_min()
        g5 = rr >= get_rr_min()
        g6 = integrity >= get_integrity_min()
        g7 = bool(compliant)
        g8 = drawdown <= get_max_drawdown()
        g9 = latency <= get_max_latency_ms()

        passed = sum([g1, g2, g3, g4, g5, g6, g7, g8, g9])

        return {
            "total_passed": passed,
            "total_gates": 9,
            "gate_1_tii": "PASS" if g1 else "FAIL",
            "gate_2_montecarlo": "PASS" if g2 else "FAIL",
            "gate_3_frpc": "PASS" if g3 else "FAIL",
            "gate_4_conf12": "PASS" if g4 else "FAIL",
            "gate_5_rr": "PASS" if g5 else "FAIL",
            "gate_6_integrity": "PASS" if g6 else "FAIL",
            "gate_7_propfirm": "PASS" if g7 else "FAIL",
            "gate_8_drawdown": "PASS" if g8 else "FAIL",
            "gate_9_latency": "PASS" if g9 else "FAIL",
        }

    # ══════════════════════════════════════════════════════════════
    #  L13 - REFLECTIVE EXECUTION STRATEGY
    # ══════════════════════════════════════════════════════════════

    def _run_reflective_pass(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        """
        L13: Reflective Execution Strategy.

        TRQ-3D energy field (αβγ), LFS, FRPC synchronization.
        Only runs if L12 verdict is EXECUTE.

        Sources:
            core_quantum_unified.py    → QuantumExecutionOptimizer
            core_reflective_unified.py → ReflectiveTradePipelineController
        """
        lrce_score = self._compute_lrce(synthesis)
        frpc_score = self._compute_frpc(synthesis, l12_verdict)

        # αβγ from TRQ-3D (placeholder - will use core modules when populated)
        alpha = lrce_score
        beta = frpc_score
        gamma = 1.0

        abg_score = alpha * 0.40 + beta * 0.30 + gamma * 0.30

        drift = synthesis.get("trq3d", {}).get("drift", 0.0)
        lrce_field = synthesis.get("risk", {}).get("lrce", 0.0)

        return {
            "lrce_score": lrce_score,
            "frpc_score": frpc_score,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "abg_score": abg_score,
            "drift": drift,
            "lrce_field": lrce_field,
            "field_state": "EXPANSION" if abg_score >= 0.80 else "COMPRESSION",
            "execution_window": "OPTIMAL" if abg_score >= 0.85 else "GOOD" if abg_score >= 0.70 else "POOR",
        }

    # ══════════════════════════════════════════════════════════════
    #  L14 - JSON OUTPUT & DATA EXPORT
    # ══════════════════════════════════════════════════════════════

    def _build_l14_json(  # noqa: PLR0913
        self,
        symbol: str,
        now: datetime,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective: dict[str, Any] | None,
        gates: dict[str, Any],
        l1: dict[str, Any],
        l2: dict[str, Any],
        l3: dict[str, Any],
        l5: dict[str, Any],
        l6: dict[str, Any],
        l8: dict[str, Any],
        l9: dict[str, Any],
        l10: dict[str, Any],
        l11: dict[str, Any],
        sovereignty: dict[str, Any],
        latency_ms: float,
    ) -> dict[str, Any]:
        """Build full L14 JSON export matching v7.4r∞ schema."""
        verdict_str = l12_verdict.get("verdict", "HOLD")
        confidence = l12_verdict.get("confidence", "LOW")
        wolf_status = l12_verdict.get("wolf_status", "NO_HUNT")

        return {
            "schema": self.VERSION,
            "pair": symbol,
            "timestamp": now.strftime("%Y-%m-%d %H:%M GMT+8"),
            "verdict": verdict_str,
            "confidence": confidence,
            "wolf_status": wolf_status,
            "battle_strategy": synthesis.get("execution", {}).get("battle_strategy", "SHADOW_STRIKE"),
            "modules": {
                "cognitive": "core_cognitive_unified.py",
                "fusion": "core_fusion_unified.py",
                "quantum": "core_quantum_unified.py",
                "reflective": "core_reflective_unified.py",
            },
            "scores": synthesis.get("scores", {}),
            "layers": synthesis.get("layers", {}),
            "cognitive": synthesis.get("cognitive", {}),
            "fusion_frpc": synthesis.get("fusion_frpc", {}),
            "trq3d": synthesis.get("trq3d", {}),
            "lfs": {
                "mean_energy": synthesis.get("trq3d", {}).get("mean_energy", 0.0),
                "lrce": synthesis.get("risk", {}).get("lrce", 0.0),
                "phase": "EXPANSION" if reflective and reflective.get("abg_score", 0) >= 0.80 else "STABILIZATION",
            },
            "smc": synthesis.get("smc", {}),
            "execution": synthesis.get("execution", {}),
            "gates": gates,
            "propfirm": synthesis.get("propfirm", {}),
            "meta16": {
                "meta_integrity": sovereignty.get("meta_integrity", 0.0),
                "reflective_coherence": reflective.get("frpc_score", 0.0) if reflective else 0.0,
                "vault_sync": sovereignty.get("vault_sync", 0.0),
                "evolution_drift": reflective.get("drift", 0.0) if reflective else 0.0,
                "meta_state": l10.get("meta_state", "STABLE"),
            },
            "wolf_discipline": synthesis.get("wolf_discipline", {}),
            "final_gate": "ALL_PASS" if gates.get("total_passed", 0) == 9 else f"GATE_{9 - gates.get('total_passed', 0)}_FAIL",
        }

    # ══════════════════════════════════════════════════════════════
    #  L15 - META SYNTHESIS (FULL UNITY STATE)
    # ══════════════════════════════════════════════════════════════

    def _build_l15_meta(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective: dict[str, Any] | None,
        sovereignty: dict[str, Any],
        gates: dict[str, Any],
    ) -> dict[str, Any]:
        """
        L15: Meta Synthesis - Full Unity State Analysis.

        Combines all 14 layers into a single reflective consciousness state.
        """
        integrity = synthesis.get("layers", {}).get("L8_integrity_index", 0.0)
        synthesis.get("layers", {}).get("L8_tii_sym", 0.0)
        rr = synthesis.get("execution", {}).get("rr_ratio", 0.0)
        wolf_score = synthesis.get("scores", {}).get("wolf_30_point", 0)

        # Zona health aggregation
        zona_1_pass = all([
            synthesis.get("layers", {}).get("L1_context_coherence", 0) >= 0.90,
            synthesis.get("layers", {}).get("L2_reflex_coherence", 0) >= 0.88,
            synthesis.get("layers", {}).get("L3_trq3d_energy", 0) >= 0.65,
        ])
        zona_2_pass = wolf_score >= 24
        zona_3_pass = all([
            gates.get("gate_1_tii") == "PASS",
            gates.get("gate_2_montecarlo") == "PASS",
        ])
        zona_4_pass = l12_verdict.get("verdict", "").startswith("EXECUTE")
        zona_5_pass = reflective is not None and reflective.get("abg_score", 0) >= 0.70

        all_harmonized = all([zona_1_pass, zona_2_pass, zona_3_pass, zona_4_pass, zona_5_pass])

        return {
            "meta_integrity": sovereignty.get("meta_integrity", 0.0),
            "reflective_coherence": reflective.get("frpc_score", 0.0) if reflective else 0.0,
            "vault_sync": sovereignty.get("vault_sync", 0.0),
            "evolution_drift": reflective.get("drift", 0.0) if reflective else 0.0,
            "conscious_phase": "EXPANSION" if all_harmonized else "STABILIZATION",
            "wolf_discipline_score": wolf_score / 30.0 if wolf_score else 0.0,
            "zona_health": {
                "perception_context": {"layers": "L1-L3", "status": "PASS" if zona_1_pass else "FAIL"},
                "confluence_scoring": {"layers": "L4-L6", "status": "PASS" if zona_2_pass else "FAIL"},
                "probability_validation": {"layers": "L7-L9", "status": "PASS" if zona_3_pass else "FAIL"},
                "execution_decision": {"layers": "L10-L12", "status": "PASS" if zona_4_pass else "FAIL"},
                "meta_reflective": {"layers": "L13-L15", "status": "PASS" if zona_5_pass else "FAIL"},
            },
            "full_reflective_state": {
                "all_harmonized": all_harmonized,
                "integrity_check": integrity >= 0.97,
                "rr_check": rr >= 2.0,
                "constitutional_clear": l12_verdict.get("verdict", "").startswith("EXECUTE"),
                "achieved": all_harmonized and integrity >= 0.97 and rr >= 2.0,
            },
        }

    # ══════════════════════════════════════════════════════════════
    #  HELPER - direction / bias alignment
    # ══════════════════════════════════════════════════════════════

    def _is_direction_aligned_with_bias(self, direction: str, technical_bias: str) -> bool:
        """Check if direction is aligned with technical bias."""
        if direction == "BUY" and technical_bias == "BULLISH":
            return True
        if direction == "SELL" and technical_bias == "BEARISH":
            return True
        return False

    def _compute_lrce(self, synthesis: dict[str, Any]) -> float:
        """Compute Layer Recursive Coherence (directional alignment)."""
        direction = synthesis.get("execution", {}).get("direction")
        technical_bias = synthesis.get("bias", {}).get("technical", "NEUTRAL")

        if not direction or direction == "HOLD":
            return 0.5
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

        if verdict.startswith("EXECUTE"):
            if self._is_direction_aligned_with_bias(direction, technical_bias):
                return 1.0
            if technical_bias == "NEUTRAL":
                return 0.7
            return 0.3
        if verdict == "HOLD":
            return 0.8 if technical_bias == "NEUTRAL" else 0.5
        return 0.5

    # ══════════════════════════════════════════════════════════════
    #  L14 - VAULT SYNC + SOVEREIGNTY
    # ══════════════════════════════════════════════════════════════

    def _compute_sovereignty(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Compute vault sync (3-component) + sovereignty enforcement.

        Vault sync formula: feed × 0.50 + redis × 0.30 + integrity × 0.20
        """
        weights = get_vault_sync_weights()
        thresholds = get_vault_sync_thresholds()

        # TODO: Implement real health checks before production deployment
        feed_freshness = 1.0  # PLACEHOLDER - query LiveContextBus
        redis_health = 1.0  # PLACEHOLDER - check Redis health
        meta_integrity = 1.0  # PLACEHOLDER - compute from layer validity

        vault_sync = (
            feed_freshness * weights["feed"]
            + redis_health * weights["redis"]
            + meta_integrity * weights["integrity"]
        )

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

    # ══════════════════════════════════════════════════════════════
    #  EARLY EXIT - pipeline failure fallback
    # ══════════════════════════════════════════════════════════════

    def _early_exit(
        self,
        symbol: str,
        errors: list[str],
        latency_ms: float,
    ) -> dict[str, Any]:
        """Create early-exit result when pipeline fails."""
        empty_gates = {
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

        return {
            "schema": self.VERSION,
            "pair": symbol,
            "timestamp": datetime.now(_TZ_GMT8).isoformat(),
            "synthesis": {
                "pair": symbol,
                "scores": {
                    "wolf_30_point": 0, "f_score": 0, "t_score": 0,
                    "fta_score": 0.0, "fta_multiplier": 0.0, "exec_score": 0,
                    "psychology_score": 0, "technical_score": 0,
                },
                "layers": {
                    "L1_context_coherence": 0.0, "L2_reflex_coherence": 0.0,
                    "L3_trq3d_energy": 0.0, "L7_monte_carlo_win": 0.0,
                    "L8_tii_sym": 0.0, "L8_integrity_index": 0.0,
                    "L9_dvg_confidence": 0.0, "L9_liquidity_score": 0.0,
                    "conf12": 0.0,
                },
                "execution": {
                    "direction": "HOLD", "entry_price": 0.0,
                    "stop_loss": 0.0, "take_profit_1": 0.0,
                    "entry_zone": "0.00000-0.00000",
                    "execution_mode": "TP1_ONLY",
                    "battle_strategy": "SHADOW_STRIKE",
                    "rr_ratio": 0.0, "lot_size": 0.0,
                    "risk_percent": 0.0, "risk_amount": 0.0,
                    "slippage_estimate": 0.0, "optimal_timing": "",
                },
                "risk": {
                    "current_drawdown": 0.0, "drawdown_level": "LEVEL_0",
                    "risk_multiplier": 0.0, "risk_status": "CRITICAL",
                    "lrce": 0.0,
                },
                "propfirm": {
                    "compliant": False, "daily_loss_status": "OK",
                    "max_drawdown_status": "OK", "profit_target_progress": 0.0,
                },
                "bias": {"fundamental": "NEUTRAL", "technical": "NEUTRAL", "macro": "UNKNOWN"},
                "cognitive": {"regime": "RANGE", "dominant_force": "NEUTRAL", "cbv": 0.0, "csi": 0.0},
                "fusion_frpc": {"conf12": 0.0, "frpc_energy": 0.0, "lambda_esi": 0.003, "integrity": 0.0},
                "trq3d": {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "drift": 0.0, "mean_energy": 0.0, "intensity": 0.0},
                "smc": {
                    "structure": "RANGE", "smart_money_signal": "NEUTRAL",
                    "liquidity_zone": "0.00000", "ob_present": False,
                    "fvg_present": False, "sweep_detected": False, "bias": "NEUTRAL",
                },
                "wolf_discipline": {
                    "score": 0.0, "polarity_deviation": 0.0,
                    "lambda_balance": "INACTIVE", "bias_symmetry": "NEUTRAL",
                    "eaf_score": 0.0, "emotional_state": "CALM",
                },
                "macro": {
                    "regime": "UNKNOWN", "phase": "NEUTRAL",
                    "volatility_ratio": 1.0, "mn_aligned": False,
                    "liquidity": {}, "bias_override": {},
                },
                "system": {"latency_ms": latency_ms},
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
            "l14_json": None,
            "l15_meta": None,
            "sovereignty": {
                "execution_rights": "REVOKED",
                "lot_multiplier": 0.0,
                "vault_sync": 0.0,
            },
            "latency_ms": latency_ms,
            "errors": errors,
        }
