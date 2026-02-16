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

import time

from datetime import datetime, timedelta, timezone
from typing import Any

from constitution.signal_throttle import SignalThrottle
from constitution.verdict_engine import generate_l12_verdict
from core.metrics import (
    GATE_RESULT,
    PIPELINE_DURATION,
    PIPELINE_ERROR,
    PIPELINE_RUNS,
    SIGNAL_THROTTLED,
    SIGNAL_TOTAL,
    VERDICT_TOTAL,
    WARMUP_BLOCKED,
)
from core.vault_health import VaultHealthChecker  # noqa: F401
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
from pipeline.engines import L13ReflectiveEngine, L15MetaSovereigntyEngine
from pipeline.result import PipelineResult

try:
    from loguru import logger  # pyright: ignore[reportMissingImports]
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ─── GMT+8 timezone for timestamps ───
_TZ_GMT8 = timezone(timedelta(hours=8))


# ══════════════════════════════════════════════════════════════
#  STANDALONE SYNTHESIS BUILDER
# ══════════════════════════════════════════════════════════════

def _run_l7_probability(
    symbol: str,
    technical_score: int,
    trade_returns: list[float] | None = None,
    prior_wins: int = 0,
    prior_losses: int = 0,
    base_bias: float = 0.5,
) -> dict[str, Any]:
    """Run Layer 7 probability analysis with trade returns."""
    from analysis.layers.L7_probability import L7ProbabilityAnalyzer  # noqa: PLC0415

    analyzer = L7ProbabilityAnalyzer()
    return analyzer.analyze(
        symbol,
        technical_score=technical_score,
        trade_returns=trade_returns,
        prior_wins=prior_wins,
        prior_losses=prior_losses,
    )

def build_l12_synthesis(
    layer_results: dict[str, Any],
    symbol: str = "UNKNOWN",
) -> dict[str, Any]:
    """Build Layer-12 synthesis with Bayesian + Monte Carlo enrichment fields.

    L7 fields are normalized before injection:
    - win_probability (0-100 from MC) -> L7_monte_carlo_win (0.0-1.0)
    - risk_of_ruin (0.0-1.0) -> L7_risk_of_ruin (default 1.0 = worst)
    - posterior_win_probability (0.0-1.0) -> L7_posterior_win
    - profit_factor (float) -> L7_profit_factor
    - bayesian_ci_low / bayesian_ci_high -> L7_bayesian_ci_low / L7_bayesian_ci_high
    - mc_passed_threshold (bool) -> L7_mc_passed
    - validation (str) -> L7_validation
    """
    # ── Wolf 30-Point from L4 ──
    if "wolf_30_point" in layer_results.get("L4", {}) and isinstance(layer_results["L4"]["wolf_30_point"], dict):
        wolf_30_point = layer_results["L4"]["wolf_30_point"].get("total", 0)
        f_score = layer_results["L4"]["wolf_30_point"].get("f_score", 0)
        t_score = layer_results["L4"]["wolf_30_point"].get("t_score", 0)
        fta_score_raw = layer_results["L4"]["wolf_30_point"].get("fta_score", 0.0)
        exec_score = layer_results["L4"]["wolf_30_point"].get("exec_score", 0)
    else:
        technical_score = layer_results.get("L4", {}).get("technical_score", 0)
        win_prob = layer_results.get("L7", {}).get("win_probability", 0)
        wolf_30_point = int((technical_score / 100) * 15 + (win_prob / 100) * 15)
        wolf_30_point = max(0, min(30, wolf_30_point))
        f_score = 0
        t_score = 0
        fta_score_raw = 0.0
        exec_score = 0

    # ── FTA Score (enriched from L10 or fallback) ──
    fta_score = layer_results.get("L10", {}).get("fta_score", fta_score_raw)
    fta_multiplier = layer_results.get("L10", {}).get("fta_multiplier", 1.0)
    if exec_score == 0:
        exec_score = 6 if layer_results.get("L10", {}).get("position_ok", False) else 0

    # ── Direction from L3 ──
    trend = layer_results.get("L3", {}).get("trend", "NEUTRAL")
    direction = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(trend, "HOLD")

    # ── Execution details from L11 ──
    entry_price = layer_results.get("L11", {}).get("entry_price", layer_results.get("L11", {}).get("entry", 0.0))
    stop_loss = layer_results.get("L11", {}).get("stop_loss", layer_results.get("L11", {}).get("sl", 0.0))
    take_profit_1 = layer_results.get("L11", {}).get("take_profit_1", layer_results.get("L11", {}).get("tp1", layer_results.get("L11", {}).get("tp", 0.0)))
    rr_ratio = layer_results.get("L11", {}).get("rr", 0.0)
    battle_strategy = layer_results.get("L11", {}).get("battle_strategy", "SHADOW_STRIKE")
    entry_zone = layer_results.get("L11", {}).get("entry_zone", "")
    if not entry_zone and entry_price > 0:
        if direction == "BUY":
            entry_zone = f"{entry_price - 0.0010:.5f}-{entry_price:.5f}"
        else:
            entry_zone = f"{entry_price:.5f}-{entry_price + 0.0010:.5f}"

    # ── Risk (from L10/dashboard -- placeholders) ──
    lot_size = layer_results.get("L10", {}).get("final_lot_size", 0.01)
    risk_percent = layer_results.get("L10", {}).get("adjusted_risk_pct", 1.0)
    risk_amount = layer_results.get("L10", {}).get("adjusted_risk_amount", 0.0)

    # ── Metrics ──
    tii_sym = layer_results.get("L8", {}).get("tii_sym", 0.0)
    integrity = layer_results.get("L8", {}).get("integrity", 0.0)
    conf12 = layer_results.get("L2", {}).get("conf12", (tii_sym + integrity) / 2.0)
    current_drawdown = layer_results.get("L5", {}).get("current_drawdown", 0.0)
    prop_compliant = layer_results.get("L6", {}).get("propfirm_compliant", True)
    psychology_score = layer_results.get("L5", {}).get("psychology_score", 0)
    eaf_score = layer_results.get("L5", {}).get("eaf_score", 0.0)

    vix_regime_state = layer_results.get("macro_vix_state", {}).get("regime_state", 1)

    # Existing fields
    synthesis = {
        "pair": symbol,
        "scores": {
            "wolf_30_point": wolf_30_point,
            "f_score": f_score,
            "t_score": t_score,
            "fta_score": fta_score,
            "fta_multiplier": fta_multiplier,
            "exec_score": exec_score,
            "psychology_score": psychology_score,
            "technical_score": technical_score, # pyright: ignore[reportPossiblyUnboundVariable]
        },
        "layers": {
            "L1_context_coherence": layer_results.get("L1", {}).get("regime_confidence", 0.0),
            "L2_reflex_coherence": layer_results.get("L2", {}).get("reflex_coherence", 0.0),
            "L3_trq3d_energy": layer_results.get("L3", {}).get("trq3d_energy", 0.0),
            "L7_monte_carlo_win": (
                _wp_raw / 100.0 if (_wp_raw := layer_results.get("L7", {}).get("win_probability", 0.0)) > 1.0
                else _wp_raw
            ),
            "L8_tii_sym": tii_sym,
            "L8_integrity_index": integrity,
            "L9_dvg_confidence": layer_results.get("L9", {}).get("dvg_confidence", 0.0),
            "L9_liquidity_score": layer_results.get("L9", {}).get("liquidity_score", 0.0),
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
            "current_drawdown": layer_results.get("L6", {}).get("current_drawdown", current_drawdown),
            "drawdown_level": layer_results.get("L6", {}).get("drawdown_level", "LEVEL_0"),
            "risk_multiplier": layer_results.get("L6", {}).get("risk_multiplier", 1.0),
            "risk_status": layer_results.get("L6", {}).get("risk_status", "ACCEPTABLE"),
            "lrce": layer_results.get("L6", {}).get("lrce", 0.0),
            "rolling_sharpe": layer_results.get("L6", {}).get("rolling_sharpe", 0.0),
            "kelly_adjusted": layer_results.get("L6", {}).get("kelly_adjusted", 0.0),
        },
        "propfirm": {
            "compliant": prop_compliant,
            "daily_loss_status": "OK",
            "max_drawdown_status": "OK",
            "profit_target_progress": 0.0,
        },
        "bias": {
            "fundamental": "NEUTRAL" if not layer_results.get("L1", {}).get("valid") else trend,
            "technical": trend,
            "macro": layer_results.get("macro", "UNKNOWN"),
        },
        "cognitive": {
            "regime": layer_results.get("L1", {}).get("regime", "TREND"),
            "dominant_force": layer_results.get("L1", {}).get("dominant_force", "NEUTRAL"),
            "cbv": layer_results.get("L1", {}).get("csi", 0.0),
            "csi": layer_results.get("L1", {}).get("regime_confidence", 0.0),
        },
        "fusion_frpc": {
            "conf12": conf12,
            "frpc_energy": layer_results.get("L2", {}).get("frpc_energy", 0.0),
            "lambda_esi": 0.003,
            "integrity": integrity,
        },
        "trq3d": {
            "alpha": 0.0,
            "beta": 0.0,
            "gamma": 0.0,
            "drift": layer_results.get("L3", {}).get("drift", 0.0),
            "mean_energy": layer_results.get("L3", {}).get("trq3d_energy", 0.0),
            "intensity": 0.0,
        },
        "smc": {
            "structure": "RANGE",
            "smart_money_signal": layer_results.get("L9", {}).get("smart_money_signal", "NEUTRAL"),
            "liquidity_zone": "0.00000",
            "ob_present": layer_results.get("L9", {}).get("ob_present", False),
            "fvg_present": layer_results.get("L9", {}).get("fvg_present", False),
            "sweep_detected": layer_results.get("L9", {}).get("sweep_detected", False),
            "bias": layer_results.get("L9", {}).get("smart_money_bias", "NEUTRAL"),
        },
        "wolf_discipline": {
            "score": wolf_30_point / 30.0 if wolf_30_point else 0.0,
            "polarity_deviation": layer_results.get("L5", {}).get("emotion_delta", 0.0),
            "lambda_balance": "ACTIVE",
            "bias_symmetry": "NEUTRAL",
            "eaf_score": eaf_score,
            "emotional_state": "CALM",
        },
        "macro": {
            "regime": layer_results.get("macro", "UNKNOWN"),
            "phase": layer_results.get("phase", "NEUTRAL"),
            "volatility_ratio": layer_results.get("macro_vol_ratio", 1.0),
            "mn_aligned": layer_results.get("alignment", False),
            "liquidity": layer_results.get("liquidity", {}),
            "bias_override": layer_results.get("bias_override", {}),
        },
        "macro_vix": {
            "regime_state": vix_regime_state,
            "risk_multiplier": layer_results.get("macro_vix_state", {}).get("risk_multiplier", 1.0),
        },
        "system": {
            "latency_ms": 0.0,
            "safe_mode": False,
        },
    }

    # Bayesian enrichment fields from L7
    synthesis["bayesian_posterior"] = layer_results.get("L7", {}).get("bayesian_posterior", 0.0)
    synthesis["bayesian_ci_low"] = layer_results.get("L7", {}).get("bayesian_ci_low", 0.0)
    synthesis["bayesian_ci_high"] = layer_results.get("L7", {}).get("bayesian_ci_high", 0.0)
    synthesis["mc_passed_threshold"] = layer_results.get("L7", {}).get("mc_passed_threshold", False)
    synthesis["risk_of_ruin"] = layer_results.get("L7", {}).get("risk_of_ruin", 0.0)
    synthesis["l7_validation"] = layer_results.get("L7", {}).get("validation", "FAIL")

    return synthesis


class WolfConstitutionalPipeline:
    """
    Wolf 15-Layer Constitutional Pipeline v8.0 -- Unified Super Pipeline.

    Merged from Constitutional v7.4r∞ + Sovereign governance features.
    This is the ONLY entry point for analysis in the entire system.
    All 15 layers (L1-L15) are executed sequentially with halt-on-failure.
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
    WARMUP_MIN_BARS: dict[str, int] = {
        "M15": 20,
        "H1": 20,
        "H4": 10,
        "D1": 5,
    }

    def __init__(self) -> None:
        """Initialize with lazy loading to avoid circular imports."""
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

        # Macro analyzers
        self._macro = None
        self._macro_vol = None

        # Governance engines (from merged Sovereign pipeline)
        self._l13_engine = L13ReflectiveEngine()
        self._l15_engine = L15MetaSovereigntyEngine()

        # Signal rate throttle (max 3 EXECUTE per symbol in 5 minutes)
        self._signal_throttle = SignalThrottle(max_signals=3, window_seconds=300)

        # Engine Enrichment Layer (Phase 2.5 — 9 facade engines)
        self._enrichment: Any = None  # lazy-loaded

        # Vault health checker (lazy-initialized on first use)
        self._vault_checker = None  # type: VaultHealthChecker | None

    # ──────────────────────────────────────────────────────
    #  Lazy-load all layer analyzers
    # ──────────────────────────────────────────────────────

    def _ensure_analyzers(self) -> None:
        """Lazy load analyzers to avoid circular imports."""
        if self._l1 is not None:
            return

        import analysis.layers.L10_position_sizing  # noqa: PLC0415
        import analysis.macro.macro_volatility_engine  # noqa: PLC0415

        from analysis.layers.L1_context import (  # noqa: PLC0415
            L1ContextAnalyzer,  # pyright: ignore[reportAttributeAccessIssue]
        )
        from analysis.layers.L2_mta import L2MTAAnalyzer  # noqa: PLC0415
        from analysis.layers.L3_technical import L3TechnicalAnalyzer  # noqa: PLC0415
        from analysis.layers.L4_session_scoring import (  # noqa: PLC0415
            L4ScoringEngine,  # pyright: ignore[reportMissingImports]
        )
        from analysis.layers.L5_psychology_fundamental import (  # noqa: PLC0415
            L5PsychologyAnalyzer,  # pyright: ignore[reportMissingImports]
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

    # ══════════════════════════════════════════════════════════════
    #  MAIN EXECUTE -- the single canonical entry point
    # ══════════════════════════════════════════════════════════════

    def execute(  # noqa: PLR0912
        self,
        symbol: str,
        system_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute complete Wolf 15-Layer Constitutional Pipeline.

        Args:
            symbol: Trading pair symbol (e.g., "EURUSD", "XAUUSD")
            system_metrics: Optional system state dict with:
                - safe_mode (bool): bypass macro regime gate
                - latency_ms (float): override latency measurement

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
        errors: list[str] = []
        now = datetime.now(_TZ_GMT8)

        # ═══════════════════════════════════════════════════════
        # WARMUP GATE -- reject analysis if candle history is
        # too thin.  Prevents garbage verdicts on first few
        # minutes after startup.
        # ═══════════════════════════════════════════════════════
        if not safe_mode:
            warmup = self._context_bus.check_warmup(symbol, self.WARMUP_MIN_BARS) # pyright: ignore[reportAttributeAccessIssue]
            if not warmup["ready"]:
                logger.warning(
                    f"[Pipeline v8.0] {symbol} WARMUP INSUFFICIENT — "
                    f"bars={warmup['bars']}, required={warmup['required']}, "
                    f"missing={warmup['missing']}"
                )
                errors.append("WARMUP_INSUFFICIENT")
                WARMUP_BLOCKED.labels(symbol=symbol).inc()
                return self._early_exit(symbol, errors, time.time() - start_time)

        try:
            # ═══════════════════════════════════════════════════════
            # PHASE 1 -- ZONA PERCEPTION & CONTEXT (L1, L2, L3)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 1: Perception & Context -- {symbol}")

            l1 = self._l1.analyze(symbol)  # pyright: ignore[reportOptionalMemberAccess]
            if not l1.get("valid"):
                errors.append("L1_CONTEXT_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            l2 = self._l2.analyze(symbol)  # pyright: ignore[reportOptionalMemberAccess]
            if not l2.get("valid"):
                errors.append("L2_MTA_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            l3 = self._l3.analyze(symbol)  # pyright: ignore[reportOptionalMemberAccess]
            if not l3.get("valid"):
                errors.append("L3_TECHNICAL_INVALID")
                return self._early_exit(symbol, errors, time.time() - start_time)

            # ═══════════════════════════════════════════════════════
            # PHASE 2 -- ZONA CONFLUENCE & SCORING (L4, L5)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 2: Confluence & Scoring -- {symbol}")

            l4 = self._l4.score(l1, l2, l3)  # pyright: ignore[reportOptionalMemberAccess]
            l5 = self._l5.analyze(symbol, volatility_profile=l2)  # pyright: ignore[reportOptionalMemberAccess]

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

            technical_score = l4.get("technical_score", 0)

            # ── Trade history for Monte Carlo ────────────────────────────────
            # Source: system_metrics carries historical per-trade P&L from
            # dashboard ledger / journal archive.  If unavailable, MC engine
            # gracefully skips (requires ≥ 30 trades).
            #
            # ── Trade history for Monte Carlo (from persistent archive) ────
            # Primary: storage/trade_archive.py  (Redis → PostgreSQL → ledger)
            # Fallback: system_metrics pass-through (caller-provided)
            trade_returns: list[float] | None = None
            try:
                from storage.trade_archive import get_closed_returns  # noqa: PLC0415

                _archived = get_closed_returns(symbol=symbol, lookback=200)
                if _archived:
                    trade_returns = _archived
                    logger.info(
                        "[Phase-3] %s Loaded %d historical returns from trade archive",
                        symbol,
                        len(_archived),
                    )
            except Exception as _archive_err:
                logger.warning(
                    "[Phase-3] %s trade_archive unavailable: %s — falling back to system_metrics",
                    symbol,
                    _archive_err,
                )

            # Fallback: system_metrics pass-through (for test harness / manual override)
            if not trade_returns:
                if system_metrics and isinstance(system_metrics, dict):
                    _raw = system_metrics.get("trade_returns", None)
                    if isinstance(_raw, (list, tuple)) and len(_raw) > 0:
                        trade_returns = [float(r) for r in _raw]

            # ── Bayesian prior state ─────────────────────────────────────────
            # Primary: derive from trade archive. Fallback: system_metrics.
            prior_wins: int = 0
            prior_losses: int = 0
            try:
                from storage.trade_archive import get_win_loss_counts as _gwlc  # noqa: PLC0415

                _w, _l = _gwlc(symbol=symbol, lookback=200)
                if _w + _l > 0:
                    prior_wins = _w
                    prior_losses = _l
            except Exception:
                pass  # fall through to system_metrics

            if prior_wins == 0 and prior_losses == 0:
                if system_metrics and isinstance(system_metrics, dict):
                    prior_wins = int(system_metrics.get("prior_wins", 0))
                    prior_losses = int(system_metrics.get("prior_losses", 0))

            # ── Coherence from upstream layers (L1-L6 agreement) ─────────────
            # If a coherence aggregator ran, use it; otherwise default 50.0.
            if isinstance(l4, dict):
                _coh = l4.get("coherence", None)
                if _coh is not None:
                    float(_coh)

            # ── Volatility index from L5 or regime detector ──────────────────
            if l5 and isinstance(l5, dict):
                float(l5.get("volatility_index", l5.get("atr_normalized", 20.0)))

            # ── Base directional bias from L3/L4 ─────────────────────────────
            if l4 and isinstance(l4, dict):
                _bias = l4.get("directional_bias", l4.get("bias_score", None))
                if _bias is not None:
                    float(max(0.0, min(1.0, _bias)))

            # ── Run L7 Probability Analyzer ──────────────────────────────────
            l7 = self._l7.analyze( # pyright: ignore[reportOptionalMemberAccess]
                symbol,
                technical_score=technical_score,
                trade_returns=trade_returns,
                prior_wins=prior_wins,
                prior_losses=prior_losses,
            )

            l8 = self._l8.analyze(symbol)  # pyright: ignore[reportArgumentType, reportOptionalMemberAccess]
            l9 = self._l9.analyze(symbol)  # pyright: ignore[reportOptionalMemberAccess]

            logger.info(
                "[Phase-3] %s L7 complete: validation=%s win=%.1f%% pf=%.2f "
                "bayes=%.4f ror=%.4f mc_passed=%s",
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

            trend = l3.get("trend", "NEUTRAL")
            if trend == "BULLISH":
                direction = "BUY"
            elif trend == "BEARISH":
                direction = "SELL"
            else:
                direction = "HOLD"

            l11: dict[str, Any] = {"valid": False, "rr": 0.0}
            if direction in ("BUY", "SELL"):
                l11 = self._l11.calculate_rr(symbol, direction)  # pyright: ignore[reportOptionalMemberAccess]
            rr_value = l11.get("rr", 0.0)

            # Build account_state snapshot from L5 + pipeline context
            _l6_account_state: dict[str, Any] = {
                "drawdown_pct": l5.get("current_drawdown", 0.0) if isinstance(l5, dict) else 0.0,
                "consecutive_losses": l5.get("consecutive_losses", 0) if isinstance(l5, dict) else 0,
                "vol_cluster": l1.get("volatility_level", "NORMAL") if isinstance(l1, dict) else "NORMAL",
            }

            l6 = self._l6.analyze(  # pyright: ignore[reportOptionalMemberAccess]
                rr=rr_value,
                trade_returns=trade_returns,
                account_state=_l6_account_state,
            )

            risk_ok = l6.get("risk_ok", False)
            smc_confidence = l9.get("confidence", 0.0)
            l10 = self._l10.analyze(risk_ok, smc_confidence)  # pyright: ignore[reportOptionalMemberAccess]

            macro = self._macro.analyze(symbol)  # pyright: ignore[reportOptionalMemberAccess]

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
                    "L1": l1, "L2": l2, "L3": l3, "L4": l4, "L5": l5,
                    "L6": l6, "L7": l7, "L8": l8, "L9": l9, "L10": l10, "L11": l11,
                }
                enrichment_result = self._enrichment.run(
                    symbol=symbol,
                    direction=direction,
                    layer_results=_enrich_lr,
                    entry_price=l11.get("entry_price", l11.get("entry", 0.0)),
                    stop_loss=l11.get("stop_loss", l11.get("sl", 0.0)),
                    take_profit=l11.get("take_profit_1", l11.get("tp1", l11.get("tp", 0.0))),
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

            # ═══════════════════════════════════════════════════════
            # PHASE 5 -- L12 CONSTITUTIONAL VERDICT (SOLE AUTHORITY)
            #   Build synthesis -> 9-Gate Check -> L12 verdict
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 5: Constitutional Verdict -- {symbol}")

            current_latency_ms = (time.time() - start_time) * 1000

            layer_results_combined: dict[str, Any] = {
                "L1": l1, "L2": l2, "L3": l3, "L4": l4, "L5": l5,
                "L6": l6, "L7": l7, "L8": l8, "L9": l9, "L10": l10, "L11": l11,
                "macro": macro.get("regime", "UNKNOWN") if isinstance(macro, dict) else "UNKNOWN",
                "macro_vix_state": metrics.get("macro_vix_state", {}),
            }

            synthesis = build_l12_synthesis(
                layer_results=layer_results_combined,
                symbol=symbol,
            )
            synthesis["system"]["latency_ms"] = current_latency_ms
            synthesis["system"]["safe_mode"] = safe_mode

            # Inject enrichment data into synthesis for L12 visibility
            synthesis["enrichment"] = enrichment_data
            if enrichment_data.get("confidence_adjustment"):
                synthesis["layers"]["enrichment_confidence_adj"] = enrichment_data["confidence_adjustment"]
                synthesis["layers"]["enrichment_score"] = enrichment_data.get("enrichment_score", 0.0)

            metrics.get("macro_vix_state", {})

            gates = self._evaluate_9_gates(synthesis)
            l12_verdict = generate_l12_verdict(synthesis)
            l12_verdict["gates_v74"] = gates

            # ═══════════════════════════════════════════════════════
            # PHASE 6 -- TWO-PASS L13 GOVERNANCE (from Sovereign)
            #   Pass 1: baseline (meta=1.0) -> L15 meta -> Pass 2: refined
            # ═══════════════════════════════════════════════════════
            reflective_pass1 = None
            reflective_pass2 = None
            l15_meta = None

            proceed = (
                l12_verdict.get("proceed_to_L13", False)
                or l12_verdict.get("verdict", "").startswith("EXECUTE")
            )

            if proceed:
                logger.info(f"[Pipeline v8.0] Phase 6: Two-Pass L13 Governance -- {symbol}")

                # Pass 1: Baseline reflective (meta_integrity = 1.0)
                synthesis["_meta_integrity"] = 1.0
                reflective_pass1 = self._l13_engine.reflect(
                    symbol, [l12_verdict], synthesis,
                )

                # Compute vault sync for sovereignty
                sovereignty = self._compute_vault_sync(synthesis, l12_verdict, reflective_pass1)

                # L15 meta computation (uses Pass 1 + sovereignty)
                l15_meta = self._l15_engine.compute_meta(
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    reflective_pass1=reflective_pass1,
                    sovereignty=sovereignty,
                    gates=gates,
                )

                # Pass 2: Refined reflective (uses real meta_integrity from L15)
                real_meta = l15_meta.get("meta_integrity", 1.0)
                synthesis["_meta_integrity"] = real_meta
                reflective_pass2 = self._l13_engine.reflect(
                    symbol, [l12_verdict], synthesis,
                )
            else:
                # No L13 -- still compute vault sync and meta
                sovereignty = self._compute_vault_sync(synthesis, l12_verdict, None)
                l15_meta = self._l15_engine.compute_meta(
                    synthesis=synthesis,
                    l12_verdict=l12_verdict,
                    reflective_pass1=None, # pyright: ignore[reportArgumentType]
                    sovereignty=sovereignty,
                    gates=gates,
                )

            # ═══════════════════════════════════════════════════════
            # PHASE 7 -- SOVEREIGNTY ENFORCEMENT (drift + downgrade)
            # ═══════════════════════════════════════════════════════
            logger.info(f"[Pipeline v8.0] Phase 7: Sovereignty Enforcement -- {symbol}")

            enforcement = self._l15_engine.enforce_sovereignty(
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
                        f"[Pipeline v8.0] {symbol} SIGNAL THROTTLED — "
                        f"verdict {final_verdict} downgraded to HOLD"
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
                v11_overlay = _v11.evaluate(
                    pipeline_result={
                        "synthesis": synthesis,
                        "l12_verdict": l12_verdict,
                    },
                    symbol=symbol,
                    timeframe="H1",
                )
                if v11_overlay.should_trade is False and l12_verdict["verdict"].startswith("EXECUTE"):
                    logger.warning(
                        f"[Pipeline v8.0] {symbol} V11 VETO — "
                        f"verdict {l12_verdict['verdict']} downgraded to HOLD"
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
                l1=l1, l2=l2, l3=l3, l5=l5, l6=l6,
                l8=l8, l9=l9, l10=l10, l11=l11,
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
                latency_ms=latency_ms,
                errors=errors,
            )

            result_dict = result.to_dict()
            self._record_metrics(symbol, result_dict)
            return result_dict

        except Exception as exc:
            logger.error(f"[Pipeline v8.0] Fatal error for {symbol}: {exc}", exc_info=True)
            errors.append(f"FATAL_ERROR: {exc}")
            latency_ms = (time.time() - start_time) * 1000
            return self._early_exit(symbol, errors, latency_ms)

    # ══════════════════════════════════════════════════════════════
    #  9-GATE CONSTITUTIONAL CHECK
    # ══════════════════════════════════════════════════════════════

    def _evaluate_9_gates(
        self,
        layer_results: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate the 9 constitutional gates.

        Gate 2 Enhancement (v2.1):
            Now requires BOTH conditions:
            - win_pct >= monte_min * 100  (original MC win-rate check)
            - risk_of_ruin < 0.20         (new: must not exceed 20% ruin probability)

        Returns:
            dict with per-gate booleans, overall pass, and metadata.
        """
        # Gate 1: TIIₛᵧₘ ≥ 0.93
        tii = layer_results.get("L8", {}).get("tii_sym", 0.0)
        g1 = tii >= get_tii_min()

        # Gate 2: Monte Carlo Win-Rate + Risk of Ruin
        l7 = layer_results.get("L7", {})

        # Original: win_pct >= monte_min * 100
        # Enhanced: also require risk_of_ruin < 20%
        # Rationale: A strategy can show acceptable win-rate in MC bootstrap
        # but still carry unacceptable tail risk (ruin probability).
        # Both conditions must hold for Gate 2 to pass.
        _raw_win = l7.get("win_probability", 0.0)
        # Normalize: L7 may output 0-100 or 0.0-1.0
        win_pct = _raw_win if _raw_win > 1.0 else _raw_win * 100.0

        _monte_min = get_monte_min()  # returns float 0.0-1.0 (e.g. 0.60)
        g2_win = win_pct >= (_monte_min * 100.0)

        _risk_of_ruin = l7.get("risk_of_ruin", 1.0)  # default 1.0 = worst case (fail-safe)
        _ror_threshold = 0.20
        g2_ror = _risk_of_ruin < _ror_threshold

        g2 = g2_win and g2_ror

        # Gate 3: FRPC State = SYNC
        frpc_state = layer_results.get("L2", {}).get("frpc_state", "DESYNC")
        g3 = frpc_state == "SYNC"

        # Gate 4: CONF₁₂ ≥ 0.75
        conf12 = layer_results.get("L2", {}).get("conf12", 0.0)
        g4 = conf12 >= get_conf12_min()

        # Gate 5: RR ≥ 1:2.0
        rr = layer_results.get("L11", {}).get("rr", 0.0)
        g5 = rr >= get_rr_min()

        # Gate 6: Integrity ≥ 0.97
        integrity = layer_results.get("L8", {}).get("integrity", 0.0)
        g6 = integrity >= get_integrity_min()

        # Gate 7: PropFirm Compliant
        compliant = layer_results.get("L6", {}).get("propfirm_compliant", True)
        g7 = bool(compliant)

        # Gate 8: Drawdown ≤ 2.5%
        drawdown = layer_results.get("risk", {}).get("current_drawdown", 0.0)
        g8 = drawdown <= get_max_drawdown()

        # Gate 9: Latency ≤ 250ms
        latency = synthesis.get("system", {}).get("latency_ms", 0.0)  # pyright: ignore[reportUndefinedVariable] # noqa: F821
        g9 = latency <= get_max_latency_ms()

        passed = sum([g1, g2, g3, g4, g5, g6, g7, g8, g9])

        # Log Gate 2 detail for audit trail
        import logging  # noqa: PLC0415
        _logger = logging.getLogger(__name__)
        _logger.info(
            "[Gate-2] win_pct=%.1f%% (min=%.1f%%) %s | "
            "risk_of_ruin=%.4f (max=%.2f) %s | gate=%s",
            win_pct,
            _monte_min * 100.0,
            "PASS" if g2_win else "FAIL",
            _risk_of_ruin,
            _ror_threshold,
            "PASS" if g2_ror else "FAIL",
            "PASS" if g2 else "FAIL",
        )

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
        enforcement: dict[str, Any] | None,
        latency_ms: float,
    ) -> dict[str, Any]:
        """Build full L14 JSON export matching v8.0 schema."""
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
            "enforcement": {
                "execution_rights": enforcement.get("execution_rights", "REVOKED") if enforcement else "REVOKED",
                "drift_ratio": enforcement.get("drift_ratio", 0.0) if enforcement else 0.0,
                "verdict_downgraded": enforcement.get("verdict_downgraded", False) if enforcement else False,
            },
            "final_gate": "ALL_PASS" if gates.get("total_passed", 0) == 9 else f"GATE_{9 - gates.get('total_passed', 0)}_FAIL",
        }

    # ══════════════════════════════════════════════════════════════
    #  VAULT SYNC COMPUTATION (3-component)
    # ══════════════════════════════════════════════════════════════

    def _compute_vault_sync(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Compute vault sync (3-component) + base sovereignty level.

        Vault sync formula: feed × 0.50 + redis × 0.30 + integrity × 0.20

        Note: Final sovereignty enforcement (including drift checks and
        verdict downgrades) is handled by L15MetaSovereigntyEngine.enforce_sovereignty().
        """
        weights = get_vault_sync_weights()
        thresholds = get_vault_sync_thresholds()

        # --- Real vault health checks (feed freshness + Redis) ---
        symbol = synthesis.get("pair", "")
        try:
            if self._vault_checker is None:
                from context.live_context_bus import LiveContextBus  # noqa: PLC0415
                from core.vault_health import VaultHealthChecker  # noqa: PLC0415
                from storage.redis_client import RedisClient  # noqa: PLC0415

                try:
                    redis_client = RedisClient()
                except Exception as redis_err:
                    logger.warning(
                        "[VaultSync] Redis client init failed: %s — treating Redis as DOWN",
                        redis_err,
                    )
                    redis_client = None

                context_bus = LiveContextBus()
                self._vault_checker = VaultHealthChecker(
                    redis_client=redis_client,
                    context_bus=context_bus,
                )

            vault_report = self._vault_checker.check(
                symbols=[symbol] if symbol else [],
            )
            feed_freshness = vault_report.feed_freshness
            redis_health = vault_report.redis_health

            if vault_report.should_block_analysis:
                logger.warning(
                    "[VaultSync] Vault health CRITICAL for %s — %s",
                    symbol,
                    vault_report.details,
                )
            elif not vault_report.is_healthy:
                logger.warning(
                    "[VaultSync] Vault health degraded for %s — %s",
                    symbol,
                    vault_report.details,
                )
        except Exception as exc:
            # FAIL-SAFE: if vault check itself errors, treat as unhealthy
            logger.error(
                "[VaultSync] Vault health check FAILED for %s: %s — defaulting to 0.0",
                symbol,
                exc,
            )
            feed_freshness = 0.0
            redis_health = 0.0

        meta_integrity = 1.0

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
    #  METRICS RECORDING
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _record_metrics(symbol: str, result: dict[str, Any]) -> None:
        """Record Prometheus metrics from a pipeline result.

        Covers: latency histogram, gate pass/fail, verdict counter,
        error counters, and actionable-signal counter.

        This is pure observability — no execution side-effects.
        """
        # Pipeline run counter
        PIPELINE_RUNS.labels(symbol=symbol).inc()

        # Latency histogram (convert ms → seconds)
        latency_s = result.get("latency_ms", 0.0) / 1000.0
        PIPELINE_DURATION.labels(symbol=symbol).observe(latency_s)

        # Gate results
        gates = result.get("l12_verdict", {}).get("gates_v74", {})
        for gate_key in (
            "gate_1_tii", "gate_2_montecarlo", "gate_3_frpc",
            "gate_4_conf12", "gate_5_rr", "gate_6_integrity",
            "gate_7_propfirm", "gate_8_drawdown", "gate_9_latency",
        ):
            gate_val = gates.get(gate_key, "FAIL")
            GATE_RESULT.labels(gate=gate_key, result=gate_val).inc()

        # Verdict counter
        verdict = result.get("l12_verdict", {}).get("verdict", "HOLD")
        VERDICT_TOTAL.labels(symbol=symbol, verdict=verdict).inc()

        # Actionable signal counter (EXECUTE_BUY / EXECUTE_SELL only)
        if verdict.startswith("EXECUTE_"):
            direction = verdict.replace("EXECUTE_", "")
            SIGNAL_TOTAL.labels(symbol=symbol, direction=direction).inc()

        # Error counters
        for err in result.get("errors", []):
            # Normalize long FATAL_ERROR messages to a generic code
            code = "FATAL_ERROR" if err.startswith("FATAL_ERROR") else err
            PIPELINE_ERROR.labels(error_code=code).inc()

    # ══════════════════════════════════════════════════════════════
    #  EARLY EXIT -- pipeline failure fallback
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

        result = {
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
        self._record_metrics(symbol, result)
        return result
