"""
Wolf 15-Layer Reasoning Engine

Main orchestration engine that calls real analyzers while providing:
- Sequential halt on failure
- Typed context (WolfContext)
- Execution logging
- Template population support

This engine wraps the real L1-L11 analyzers and integrates with the
constitutional verdict engine (L12).
"""

from loguru import logger

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
from reasoning.actions import WolfActions
from reasoning.conditions import WolfConditions
from reasoning.context import LayerResult, LayerState, Verdict, WolfContext, WolfStatus


class Wolf15LayerEngine:
    """
    Main Reasoning Engine untuk Wolf 15-Layer Analysis.

    Pipeline:
    L1 → L2 → L3 → L4 → L5 → L6 → L7 → L8 → L9 → L10 → L11 → L12 → L13

    Setiap layer harus PASS sebelum lanjut ke layer berikutnya.
    Layer 12 adalah SOLE AUTHORITY untuk final decision.
    """

    def __init__(self):
        # Initialize real analyzers
        self.l1 = L1ContextAnalyzer()
        self.l2 = L2MTAAnalyzer()
        self.l3 = L3TechnicalAnalyzer()
        self.l4 = L4ScoringEngine()
        self.l5 = L5PsychologyAnalyzer()
        self.l6 = L6RiskAnalyzer()
        self.l7 = L7ProbabilityAnalyzer()
        self.l8 = L8TIIIntegrityAnalyzer()
        self.l9 = L9SMCAnalyzer()
        self.l10 = L10PositionAnalyzer()
        self.l11 = L11RRAnalyzer()
        
        # Context and logging
        self.context = WolfContext()
        self.layer_results: list[LayerResult] = []
        self.execution_log: list[str] = []

    def reset(self):
        """Reset engine untuk analisis baru"""
        self.context = WolfContext()
        self.layer_results = []
        self.execution_log = []

    def log(self, message: str):
        """Log execution step"""
        self.execution_log.append(message)
        logger.debug(f"[Wolf15LayerEngine] {message}")

    # ═══════════════════════════════════════════════════════════════
    # LAYER PROCESSORS (Calling Real Analyzers)
    # ═══════════════════════════════════════════════════════════════

    def process_layer_1(self, symbol: str) -> LayerResult:
        """L1: Market Context Overview - calls real L1ContextAnalyzer"""
        self.log("Processing L1: Market Context Overview")

        # Call real analyzer
        l1_output = self.l1.analyze(symbol)
        
        # Extract context_coherence from CSI score
        csi = l1_output.get("csi", 0.90)
        context_coherence = csi * 0.95  # Simplified mapping

        # Store output
        self.context.layer_outputs["L1"] = {
            **l1_output,
            "context_coherence": context_coherence,
        }

        passed = WolfConditions.context_coherence_check(0.90)(self.context)

        result = LayerResult(
            layer_name="L1_Market_Context",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=context_coherence,
            passed_threshold=passed,
            details=self.context.layer_outputs["L1"],
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L1"] = result.state

        return result

    def process_layer_2(self, symbol: str) -> LayerResult:
        """L2: MTA Hierarchy Analysis - calls real L2MTAAnalyzer"""
        self.log("Processing L2: MTA Hierarchy Analysis")

        # Call real analyzer
        l2_output = self.l2.analyze(symbol)
        
        # Extract reflex_coherence from alignment strength
        alignment_strength = l2_output.get("alignment_strength", 0.88)
        reflex_coherence = alignment_strength

        # Store output
        self.context.layer_outputs["L2"] = {
            **l2_output,
            "reflex_coherence": reflex_coherence,
        }

        passed = WolfConditions.reflex_coherence_check(0.88)(self.context)

        result = LayerResult(
            layer_name="L2_MTA_Hierarchy",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=reflex_coherence,
            passed_threshold=passed,
            details=self.context.layer_outputs["L2"],
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L2"] = result.state

        return result

    def process_layer_3(self, symbol: str) -> LayerResult:
        """L3: Technical Analysis - calls real L3TechnicalAnalyzer"""
        self.log("Processing L3: Technical Analysis")

        # Call real analyzer
        l3_output = self.l3.analyze(symbol)

        # Store output
        self.context.layer_outputs["L3"] = l3_output

        # L3 doesn't have a hard threshold, always proceeds
        result = LayerResult(
            layer_name="L3_Technical",
            state=LayerState.PASSED if l3_output.get("valid", True) else LayerState.FAILED,
            score=l3_output.get("technical_score", 0),
            passed_threshold=l3_output.get("valid", True),
            details=l3_output,
            proceed_to_next=l3_output.get("valid", True),
        )

        self.layer_results.append(result)
        self.context.layer_states["L3"] = result.state

        return result

    def process_layer_4(self, l1_output: dict, l2_output: dict, l3_output: dict) -> LayerResult:
        """L4: Wolf 30-Point Confluence Score - calls real L4ScoringEngine"""
        self.log("Processing L4: Wolf 30-Point Confluence Score")

        # Call real analyzer
        l4_output = self.l4.score(l1_output, l2_output, l3_output)

        # Use real wolf_30_point breakdown if available, otherwise map from bool checklists
        action = WolfActions.calculate_wolf_30_score(l4_output=l4_output)
        result = action(self.context)

        self.context.layer_outputs["L4"] = {**l4_output, **result.details}
        self.layer_results.append(result)
        self.context.layer_states["L4"] = result.state

        return result

    def process_layer_5(self, symbol: str, volatility_profile: dict) -> LayerResult:
        """L5: Psychology Gates Assessment - calls real L5PsychologyAnalyzer"""
        self.log("Processing L5: Psychology Gates Assessment")

        # Call real analyzer
        l5_output = self.l5.analyze(symbol, volatility_profile=volatility_profile)

        # Extract gate scores if available, otherwise use simplified score
        psychology_score = l5_output.get("psychology_score", 70)
        gate_scores = l5_output.get("gate_scores", [7] * 10)

        action = WolfActions.calculate_psychology_score(gate_scores)
        result = action(self.context)

        self.context.layer_outputs["L5"] = {**l5_output, **result.details}
        self.layer_results.append(result)
        self.context.layer_states["L5"] = result.state

        return result

    def process_layer_6(self, rr: float) -> LayerResult:
        """L6: Risk Management - calls real L6RiskAnalyzer"""
        self.log("Processing L6: Risk Management")

        # Call real analyzer
        l6_output = self.l6.analyze(rr=rr)

        # Store output
        self.context.layer_outputs["L6"] = l6_output

        # L6 doesn't have a hard threshold, store for gate validation
        result = LayerResult(
            layer_name="L6_Risk",
            state=LayerState.PASSED if l6_output.get("risk_ok", True) else LayerState.FAILED,
            score=1.0 if l6_output.get("risk_ok", True) else 0.0,
            passed_threshold=l6_output.get("risk_ok", True),
            details=l6_output,
            proceed_to_next=True,  # L6 doesn't halt pipeline
        )

        self.layer_results.append(result)
        self.context.layer_states["L6"] = result.state

        return result

    def process_layer_7(self, symbol: str, technical_score: float, rr: float = 2.0) -> LayerResult:
        """L7: Monte Carlo FTTC Validation - calls real L7ProbabilityAnalyzer"""
        self.log("Processing L7: Monte Carlo FTTC Validation")

        # Call real analyzer
        l7_output = self.l7.analyze(symbol, technical_score, rr)

        # Store output
        self.context.layer_outputs["L7"] = l7_output

        # Check Monte Carlo threshold (68% for constitutional gate)
        win_prob = l7_output.get("win_probability", 0)
        # Convert to decimal if needed
        if win_prob > 1.0:
            win_prob = win_prob / 100.0
        
        passed = win_prob >= 0.60  # Layer-level minimum is 60%

        result = LayerResult(
            layer_name="L7_Probability",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=win_prob,
            passed_threshold=passed,
            details=l7_output,
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L7"] = result.state

        return result

    def process_layer_8(self, layers: dict) -> LayerResult:
        """L8: TII Integrity Analysis - calls real L8TIIIntegrityAnalyzer"""
        self.log("Processing L8: TII Integrity Analysis")

        # Call real analyzer
        l8_output = self.l8.analyze(layers)

        # Store output
        self.context.layer_outputs["L8"] = l8_output

        # Check TII threshold
        tii_sym = l8_output.get("tii_sym", 0)
        passed = tii_sym >= 0.93

        result = LayerResult(
            layer_name="L8_TII_Integrity",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=tii_sym,
            passed_threshold=passed,
            details=l8_output,
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L8"] = result.state

        return result

    def process_layer_9(self, symbol: str, structure: dict) -> LayerResult:
        """L9: SMC Integration - calls real L9SMCAnalyzer"""
        self.log("Processing L9: SMC Integration")

        # Call real analyzer
        l9_output = self.l9.analyze(symbol, structure)

        # Store output (map DVG/liquidity from L7 structural edge)
        self.context.layer_outputs["L9"] = l9_output

        # L9 doesn't have a hard threshold
        result = LayerResult(
            layer_name="L9_SMC",
            state=LayerState.PASSED if l9_output.get("valid", True) else LayerState.FAILED,
            score=l9_output.get("confidence", 0),
            passed_threshold=l9_output.get("valid", True),
            details=l9_output,
            proceed_to_next=True,  # L9 doesn't halt pipeline
        )

        self.layer_results.append(result)
        self.context.layer_states["L9"] = result.state

        return result

    def process_layer_10_fta(self) -> LayerResult:
        """L10: Position Sizing (FTA Score calculation)"""
        self.log("Processing L10: FTA Score")

        # Calculate FTA score using f_score, t_score, TII, and Monte Carlo
        fta_action = WolfActions.calculate_fta_score(
            self.context.f_score,
            self.context.t_score,
            self.context.layer_outputs.get("L8", {}).get("tii_sym", 0),
            self.context.layer_outputs.get("L7", {}).get("win_probability", 0),
        )
        result = fta_action(self.context)

        self.context.layer_outputs["L10"] = result.details
        self.layer_results.append(result)

        return result

    def process_layer_11(self, symbol: str, direction: str) -> LayerResult:
        """L11: RR Optimization (TP1 ONLY) - calls real L11RRAnalyzer"""
        self.log("Processing L11: RR Optimization")

        # Call real analyzer
        l11_output = self.l11.calculate_rr(symbol, direction)

        # Extract execution parameters
        entry = l11_output.get("entry", l11_output.get("entry_price", 1.1000))
        sl = l11_output.get("stop_loss", l11_output.get("sl", 1.0950))
        tp1 = l11_output.get("take_profit_1", l11_output.get("tp1", l11_output.get("tp", 1.1100)))
        
        # Calculate RR using WolfActions
        rr_action = WolfActions.calculate_rr_optimization(entry, sl, tp1, direction)
        result = rr_action(self.context)

        self.context.layer_outputs["L11"] = {**l11_output, **result.details}
        self.layer_results.append(result)

        return result

    def process_layer_12(self, use_real_verdict: bool = False, synthesis: dict | None = None) -> LayerResult:
        """L12: Constitutional Verdict"""
        self.log("Processing L12: Constitutional Verdict")

        # Generate verdict
        verdict_action = WolfActions.generate_verdict(
            use_real_verdict_engine=use_real_verdict,
            synthesis=synthesis
        )
        result = verdict_action(self.context)

        self.context.layer_outputs["L12"] = result.details
        self.layer_results.append(result)

        return result

    def process_layer_13(self, frpc: float = 0.96, lrce: float = 0.96, field_energy: float = 0.85) -> None:
        """L13: FRPC/LRCE/Field Energy (placeholder until real implementation)"""
        self.log("Processing L13: FRPC/LRCE/Field Energy")

        # For now, accept pre-computed values
        # TODO: Implement real L13 analyzer
        self.context.layer_outputs["L13"] = {
            "frpc": frpc,
            "lrce": lrce,
            "field_energy": field_energy,
        }

    # ═══════════════════════════════════════════════════════════════
    # EXECUTION MODES
    # ═══════════════════════════════════════════════════════════════

    def execute_full_pipeline(self, symbol: str, use_real_verdict: bool = True) -> dict:
        """
        Execute full pipeline with real analyzers
        
        Args:
            symbol: Trading pair symbol (e.g., "EURUSD")
            use_real_verdict: If True, uses real verdict_engine.py for L12
        
        Returns:
            Dictionary with all layer results and final verdict
        """
        self.log(f"=== WOLF 15-LAYER REASONING ENGINE START: {symbol} ===")
        self.reset()

        self.context.pair = symbol

        try:
            # L1: Market Context
            l1_result = self.process_layer_1(symbol)
            if not l1_result.proceed_to_next:
                self.log("Pipeline stopped at L1")
                return self._generate_output()

            # L2: MTA Hierarchy
            l2_result = self.process_layer_2(symbol)
            if not l2_result.proceed_to_next:
                self.log("Pipeline stopped at L2")
                return self._generate_output()

            # L3: Technical Analysis
            l3_result = self.process_layer_3(symbol)
            if not l3_result.proceed_to_next:
                self.log("Pipeline stopped at L3")
                return self._generate_output()

            # L4: Wolf 30-Point
            l4_result = self.process_layer_4(
                self.context.layer_outputs["L1"],
                self.context.layer_outputs["L2"],
                self.context.layer_outputs["L3"]
            )
            if not l4_result.proceed_to_next:
                self.log("Pipeline stopped at L4")
                return self._generate_output()

            # L5: Psychology
            l5_result = self.process_layer_5(symbol, self.context.layer_outputs["L2"])
            if not l5_result.proceed_to_next:
                self.log("Pipeline stopped at L5")
                return self._generate_output()

            # Determine direction from L3 trend
            trend = self.context.layer_outputs["L3"].get("trend", "NEUTRAL")
            direction = None
            if trend == "BULLISH":
                direction = "BUY"
            elif trend == "BEARISH":
                direction = "SELL"

            # L11: RR Optimization (before L6/L7 to get RR value)
            if direction:
                l11_result = self.process_layer_11(symbol, direction)
                rr_value = self.context.rr_ratio
            else:
                # No clear direction, use default
                rr_value = 2.0
                self.log("No clear direction - using default RR")

            # L6: Risk Management
            l6_result = self.process_layer_6(rr=rr_value)

            # L7: Probability
            technical_score = self.context.layer_outputs["L4"].get("technical_score", 0)
            l7_result = self.process_layer_7(symbol, technical_score, rr_value)
            if not l7_result.proceed_to_next:
                self.log("Pipeline stopped at L7")
                return self._generate_output()

            # L8: TII Integrity
            l8_result = self.process_layer_8({
                "l1": self.context.layer_outputs["L1"],
                "l2": self.context.layer_outputs["L2"],
                "l3": self.context.layer_outputs["L3"],
                "l4": self.context.layer_outputs["L4"],
                "l7": self.context.layer_outputs["L7"],
            })
            if not l8_result.proceed_to_next:
                self.log("Pipeline stopped at L8")
                return self._generate_output()

            # L9: SMC Integration
            structure = self.l3.structure.analyze(symbol)
            l9_result = self.process_layer_9(symbol, structure)

            # L10: FTA Score calculation
            l10_result = self.process_layer_10_fta()
            if not l10_result.proceed_to_next:
                self.log("Pipeline stopped at L10")
                return self._generate_output()

            # L13: FRPC/LRCE/Field Energy (BEFORE L12 to fix timing bug)
            # TODO: Call real L13 analyzer when implemented
            self.process_layer_13()

            # L12: Constitutional Verdict
            synthesis = None
            if use_real_verdict:
                # Build synthesis dict for real verdict engine
                from analysis.synthesis import build_synthesis
                synthesis = build_synthesis(symbol)
            
            l12_result = self.process_layer_12(
                use_real_verdict=use_real_verdict,
                synthesis=synthesis
            )

            self.log("=== WOLF 15-LAYER REASONING ENGINE COMPLETE ===")

        except Exception as e:
            self.log(f"ERROR in pipeline: {str(e)}")
            logger.exception("Wolf15LayerEngine pipeline error")

        return self._generate_output()

    def execute_from_precomputed(self, analysis_data: dict) -> dict:
        """
        Execute pipeline from pre-computed layer data (for testing)
        
        Args:
            analysis_data: Dictionary containing all layer inputs
        
        Returns:
            Dictionary with all layer results and final verdict
        """
        self.log("=== WOLF 15-LAYER REASONING ENGINE START (PRECOMPUTED) ===")
        self.reset()

        self.context.pair = analysis_data.get("pair", "UNKNOWN")
        self.context.timestamp = analysis_data.get("timestamp", "")
        self.context.current_price = analysis_data.get("current_price", 0.0)

        # Store technical bias early
        self.context.layer_outputs["L3"] = {
            "technical_bias": analysis_data.get("technical_bias", "NEUTRAL")
        }

        # Process layers sequentially with pre-computed data
        # This maintains the original sandbox behavior for testing
        # (Implementation would mirror the sandbox version but is simplified here)
        
        self.log("Precomputed mode - using analysis_data directly")
        
        # For now, just return a basic output
        # Full implementation would process each layer from analysis_data
        return self._generate_output()

    def _generate_output(self) -> dict:
        """Generate final output dictionary for template population"""
        return {
            "pair": self.context.pair,
            "timestamp": self.context.timestamp,
            "current_price": self.context.current_price,
            "verdict": self.context.verdict.value if self.context.verdict else "NO_TRADE",
            "confidence": self.context.confidence or "LOW",
            "wolf_status": self.context.wolf_status.value if self.context.wolf_status else "NO_HUNT",
            "scores": {
                "wolf_30": self.context.wolf_30_score,
                "f_score": self.context.f_score,
                "t_score": self.context.t_score,
                "fta_score": self.context.fta_score,
                "fta_score_int": self.context.fta_score_int,
                "psychology": self.context.psychology_score,
            },
            "gates": {
                "passed": self.context.gates_passed,
                "total": self.context.total_gates,
            },
            "execution": {
                "entry": self.context.entry_price,
                "stop_loss": self.context.stop_loss,
                "take_profit_1": self.context.take_profit_1,
                "rr_ratio": self.context.rr_ratio,
                "lot_size": self.context.lot_size,
                "execution_mode": "TP1_ONLY",
            },
            "layer_outputs": self.context.layer_outputs,
            "layer_states": {k: v.value for k, v in self.context.layer_states.items()},
            "layer_results": [
                {
                    "name": r.layer_name,
                    "state": r.state.value,
                    "score": r.score,
                    "passed": r.passed_threshold,
                }
                for r in self.layer_results
            ],
            "execution_log": self.execution_log,
        }
