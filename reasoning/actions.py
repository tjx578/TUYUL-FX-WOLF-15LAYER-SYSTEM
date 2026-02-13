"""
Action functions for Wolf 15-Layer Reasoning Engine

Includes scoring calculations and verdict generation.
"""

from collections.abc import Callable

from reasoning.conditions import WolfConditions
from reasoning.context import LayerResult, LayerState, Verdict, WolfContext, WolfStatus


class WolfActions:
    """
    Aksi-aksi untuk Wolf 15-Layer reasoning.
    Adapted from AdvancedActions untuk trading context.
    """

    # ═══════════════════════════════════════════════════════════════
    # SCORING ACTIONS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def calculate_wolf_30_score(
        f_checklist: list[bool] | None = None,
        t_checklist: list[bool] | None = None,
        fta_checklist: list[bool] | None = None,
        exec_checklist: list[bool] | None = None,
        l4_output: dict | None = None,
    ) -> Callable:
        """
        Calculate Wolf 30-Point Score
        
        Can accept either:
        - bool checklists (legacy/testing mode)
        - l4_output dict from real L4ScoringEngine
        """

        def action(ctx: WolfContext) -> LayerResult:
            # If L4 output is provided, use real breakdown
            if l4_output and "wolf_30_point" in l4_output:
                breakdown = l4_output.get("wolf_30_point", {})
                f_score = breakdown.get("f_score", 0)
                t_score = breakdown.get("t_score", 0)
                fta_score = breakdown.get("fta_score", 0)
                exec_score = breakdown.get("exec_score", 0)
                total = breakdown.get("total", 0)
            else:
                # Fallback to checklist calculation
                f_score = sum(f_checklist) if f_checklist else 0
                t_score = sum(t_checklist) if t_checklist else 0
                fta_score = sum(fta_checklist) if fta_checklist else 0
                exec_score = sum(exec_checklist) if exec_checklist else 0
                total = f_score + t_score + fta_score + exec_score

            ctx.f_score = f_score
            ctx.t_score = t_score
            ctx.wolf_30_score = total

            # Determine Wolf Status (SCOUT ≥24, but layer pass is ≥22)
            if total == 30:
                ctx.wolf_status = WolfStatus.ALPHA_HUNT
            elif total >= 27:
                ctx.wolf_status = WolfStatus.PACK_HUNT
            elif total >= 24:
                ctx.wolf_status = WolfStatus.SCOUT
            else:
                ctx.wolf_status = WolfStatus.NO_HUNT

            # Layer-level pass is ≥22 (matches L4_scoring.py:WOLF_MIN_SCORE)
            passed = total >= 22

            return LayerResult(
                layer_name="L4_Confluence",
                state=LayerState.PASSED if passed else LayerState.FAILED,
                score=total,
                passed_threshold=passed,
                details={
                    "f_score": f_score,
                    "t_score": t_score,
                    "fta_score": fta_score,
                    "exec_score": exec_score,
                    "total": total,
                    "wolf_status": ctx.wolf_status.value if ctx.wolf_status else "NO_HUNT",
                },
                proceed_to_next=passed,
            )

        return action

    @staticmethod
    def calculate_fta_score(
        f_score: int, t_score: int, tii_sym: float, monte_carlo: float
    ) -> Callable:
        """
        Calculate FTA Confidence Score
        
        Computes BOTH:
        - Percentage (0-100, threshold ≥65%) for display/confidence
        - Integer 0-4 mapping for L10 compatibility
        
        Formula: FTA = (F/7 × 0.20) + (T/13 × 0.40) + (TII × 0.25) + (MC × 0.15) × 100
        """

        def action(ctx: WolfContext) -> LayerResult:
            # FTA = (F/7 × 0.20) + (T/13 × 0.40) + (TII × 0.25) + (MC × 0.15)
            fta_percentage = (
                (f_score / 7) * 0.20 + (t_score / 13) * 0.40 + tii_sym * 0.25 + monte_carlo * 0.15
            ) * 100  # Convert to percentage

            ctx.fta_score = fta_percentage

            # Map to 0-4 integer for L10 compatibility
            # 0-40% -> 0, 40-55% -> 1, 55-65% -> 2, 65-80% -> 3, 80-100% -> 4
            if fta_percentage >= 80:
                fta_int = 4
            elif fta_percentage >= 65:
                fta_int = 3
            elif fta_percentage >= 55:
                fta_int = 2
            elif fta_percentage >= 40:
                fta_int = 1
            else:
                fta_int = 0
            
            ctx.fta_score_int = fta_int

            # Calculate multiplier
            if fta_percentage >= 65:
                multiplier = 1 + ((fta_percentage - 65) / 100)
            else:
                multiplier = 0.0  # No trade

            passed = fta_percentage >= 65

            return LayerResult(
                layer_name="L10_Position_Sizing",
                state=LayerState.PASSED if passed else LayerState.FAILED,
                score=fta_percentage,
                passed_threshold=passed,
                details={
                    "fta_score": round(fta_percentage, 2),
                    "fta_score_int": fta_int,  # 0-4 integer for L10
                    "fta_multiplier": round(multiplier, 2),
                    "components": {
                        "f_contribution": round((f_score / 7) * 0.20 * 100, 2),
                        "t_contribution": round((t_score / 13) * 0.40 * 100, 2),
                        "tii_contribution": round(tii_sym * 0.25 * 100, 2),
                        "mc_contribution": round(monte_carlo * 0.15 * 100, 2),
                    },
                },
                proceed_to_next=passed,
            )

        return action

    @staticmethod
    def calculate_psychology_score(gate_scores: list[int]) -> Callable:
        """Calculate Psychology Score from 10 Gates"""

        def action(ctx: WolfContext) -> LayerResult:
            total = sum(gate_scores)
            ctx.psychology_score = total

            passed = total >= 70

            # Determine gate status
            critical_gates_passed = all(g >= 7 for g in gate_scores[7:10])  # Gates 8,9,10

            return LayerResult(
                layer_name="L5_Psychology",
                state=LayerState.PASSED if passed else LayerState.FAILED,
                score=total,
                passed_threshold=passed,
                details={
                    "total_score": total,
                    "gate_scores": gate_scores,
                    "critical_gates_passed": critical_gates_passed,
                    "emotion_delta": round(1 - (total / 100), 2),
                },
                proceed_to_next=passed and critical_gates_passed,
            )

        return action

    @staticmethod
    def calculate_rr_optimization(entry: float, sl: float, tp1: float, direction: str) -> Callable:
        """Calculate Risk-Reward Optimization (TP1 ONLY)"""

        def action(ctx: WolfContext) -> LayerResult:
            if direction == "BUY":
                risk_pips = entry - sl
                reward_tp1 = tp1 - entry
            else:  # SELL
                risk_pips = sl - entry
                reward_tp1 = entry - tp1

            # TP1 ONLY - Single target
            rr_ratio = reward_tp1 / risk_pips if risk_pips > 0 else 0

            ctx.entry_price = entry
            ctx.stop_loss = sl
            ctx.take_profit_1 = tp1
            ctx.rr_ratio = rr_ratio

            passed = rr_ratio >= 2.0

            return LayerResult(
                layer_name="L11_RR_Optimization",
                state=LayerState.PASSED if passed else LayerState.FAILED,
                score=rr_ratio,
                passed_threshold=passed,
                details={
                    "entry": entry,
                    "stop_loss": sl,
                    "tp1": tp1,
                    "execution_mode": "TP1_ONLY",
                    "risk_pips": round(risk_pips * 10000, 1),  # Convert to pips
                    "reward_pips": round(reward_tp1 * 10000, 1),
                    "rr_ratio": round(rr_ratio, 2),
                },
                proceed_to_next=passed,
            )

        return action

    # ═══════════════════════════════════════════════════════════════
    # DECISION ACTIONS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def generate_verdict(use_real_verdict_engine: bool = False, synthesis: dict | None = None) -> Callable:
        """
        Generate Final Constitutional Verdict
        
        Args:
            use_real_verdict_engine: If True, calls real constitutional_cascade from verdict_engine_patch.py
            synthesis: Required if use_real_verdict_engine is True
        """

        def action(ctx: WolfContext) -> LayerResult:
            if use_real_verdict_engine and synthesis:
                # Call real verdict engine
                from constitution.verdict_engine import generate_l12_verdict
                
                l12_result = generate_l12_verdict(synthesis)
                
                # Map verdict string to Verdict enum
                verdict_str = l12_result.get("verdict", "HOLD")
                if verdict_str == "EXECUTE_BUY":
                    verdict = Verdict.EXECUTE_BUY
                elif verdict_str == "EXECUTE_SELL":
                    verdict = Verdict.EXECUTE_SELL
                elif verdict_str == "NO_TRADE":
                    verdict = Verdict.NO_TRADE
                else:
                    verdict = Verdict.HOLD
                
                ctx.verdict = verdict
                ctx.confidence = l12_result.get("confidence", "LOW")
                ctx.gates_passed = l12_result.get("gates", {}).get("passed", 0)
                
                reason = "Real verdict engine used"
            else:
                # Simplified verdict logic
                # Check 3 Absolute Conditions
                ft_aligned = WolfConditions.ft_alignment_check()(ctx)
                fta_passed = ctx.fta_score >= 65
                exec_passed = ctx.wolf_30_score >= 22  # Layer-level pass threshold

                # Check 9-Gate
                nine_gate_passed = WolfConditions.nine_gate_validation()(ctx)

                # Determine verdict
                if not ft_aligned:
                    verdict = Verdict.NO_TRADE
                    reason = "F-T Conflict detected"
                elif not fta_passed:
                    verdict = Verdict.NO_TRADE
                    reason = f"FTA < 65% ({ctx.fta_score:.1f}%)"
                elif not exec_passed:
                    verdict = Verdict.NO_TRADE
                    reason = f"Wolf Score < 22 ({ctx.wolf_30_score}/30)"
                elif not nine_gate_passed:
                    verdict = Verdict.HOLD
                    reason = f"9-Gate incomplete ({ctx.gates_passed}/9)"
                else:
                    # Determine direction
                    bias = ctx.layer_outputs.get("L3", {}).get("technical_bias", "NEUTRAL")
                    if bias == "BULLISH":
                        verdict = Verdict.EXECUTE_BUY
                    elif bias == "BEARISH":
                        verdict = Verdict.EXECUTE_SELL
                    else:
                        verdict = Verdict.HOLD
                    reason = "All conditions met"

                ctx.verdict = verdict

                # Determine confidence
                if ctx.wolf_30_score >= 27 and ctx.gates_passed >= 8:
                    ctx.confidence = "VERY_HIGH"
                elif ctx.wolf_30_score >= 24 and ctx.gates_passed >= 7:
                    ctx.confidence = "HIGH"
                elif ctx.wolf_30_score >= 22 and ctx.gates_passed >= 6:
                    ctx.confidence = "MEDIUM"
                else:
                    ctx.confidence = "LOW"

            return LayerResult(
                layer_name="L12_Constitutional_Verdict",
                state=LayerState.PASSED
                if verdict in [Verdict.EXECUTE_BUY, Verdict.EXECUTE_SELL]
                else LayerState.FAILED,
                score=ctx.gates_passed,
                passed_threshold=verdict in [Verdict.EXECUTE_BUY, Verdict.EXECUTE_SELL],
                details={
                    "verdict": verdict.value if isinstance(verdict, Verdict) else verdict,
                    "confidence": ctx.confidence,
                    "gates_passed": ctx.gates_passed,
                    "total_gates": ctx.total_gates,
                    "reason": reason,
                },
                proceed_to_next=verdict in [Verdict.EXECUTE_BUY, Verdict.EXECUTE_SELL],
            )

        return action
