"""
Condition checks for Wolf 15-Layer Reasoning Engine

Thresholds are aligned with:
- L4_scoring.py: WOLF_MIN_SCORE = 22
- constitution.yaml: monte_min = 0.68 (68%)
- Whitepaper specifications
"""

from collections.abc import Callable

from reasoning.context import WolfContext


class WolfConditions:
    """
    Kondisi-kondisi untuk Wolf 15-Layer reasoning.
    Adapted from AdvancedConditions untuk trading context.
    """

    # ═══════════════════════════════════════════════════════════════
    # THRESHOLD CONDITIONS (Audit-Verified)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def context_coherence_check(threshold: float = 0.90) -> Callable:
        """L1: Context Coherence ≥ 0.90"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L1", {}).get("context_coherence", 0)
            return value >= threshold

        return condition

    @staticmethod
    def reflex_coherence_check(threshold: float = 0.88) -> Callable:
        """L2: Reflex Coherence ≥ 0.88"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L2", {}).get("reflex_coherence", 0)
            return value >= threshold

        return condition

    @staticmethod
    def wolf_30_check(threshold: int = 22) -> Callable:
        """
        L4: Wolf 30-Point ≥ 22 (matches L4_scoring.py:WOLF_MIN_SCORE)
        Note: SCOUT classification uses ≥24, but layer-level pass is ≥22
        """

        def condition(ctx: WolfContext) -> bool:
            return ctx.wolf_30_score >= threshold

        return condition

    @staticmethod
    def psychology_check(threshold: int = 70) -> Callable:
        """L5: Psychology Score ≥ 70"""

        def condition(ctx: WolfContext) -> bool:
            return ctx.psychology_score >= threshold

        return condition

    @staticmethod
    def monte_carlo_check(threshold: float = 0.68) -> Callable:
        """
        L7: Monte Carlo Win% ≥ 68% (matches Whitepaper + constitution.yaml)
        Note: Layer-level minimum can be 60%, but constitutional gate is 68%
        """

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L7", {}).get("win_probability", 0)
            # Convert to decimal if needed (80.0 -> 0.80)
            if value > 1.0:
                value = value / 100.0
            return value >= threshold

        return condition

    @staticmethod
    def tii_check(threshold: float = 0.93) -> Callable:
        """L8: TIIₛᵧₘ ≥ 0.93"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L8", {}).get("tii_sym", 0)
            return value >= threshold

        return condition

    @staticmethod
    def integrity_check(threshold: float = 0.97) -> Callable:
        """L8: Integrity Index ≥ 0.97"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L8", {}).get("integrity_index", 0)
            return value >= threshold

        return condition

    @staticmethod
    def dvg_confidence_check(threshold: float = 0.70) -> Callable:
        """L9: DVG Confidence ≥ 0.70 (Audit Adjusted)"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L9", {}).get("dvg_confidence", 0)
            return value >= threshold

        return condition

    @staticmethod
    def liquidity_score_check(threshold: float = 0.65) -> Callable:
        """L9: Liquidity Score ≥ 0.65 (Audit Adjusted)"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L9", {}).get("liquidity_score", 0)
            return value >= threshold

        return condition

    @staticmethod
    def fta_check(threshold: float = 0.65) -> Callable:
        """L10: FTA Score ≥ 65%"""

        def condition(ctx: WolfContext) -> bool:
            return ctx.fta_score >= threshold

        return condition

    @staticmethod
    def rr_check(threshold: float = 2.0) -> Callable:
        """L11: RR Ratio ≥ 1:2.0"""

        def condition(ctx: WolfContext) -> bool:
            return ctx.rr_ratio >= threshold

        return condition

    @staticmethod
    def frpc_check(threshold: float = 0.96) -> Callable:
        """L13: FRPC ≥ 0.96"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L13", {}).get("frpc", 0)
            return value >= threshold

        return condition

    # ═══════════════════════════════════════════════════════════════
    # CHAIN VALIDATION (9-Gate System)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def nine_gate_validation() -> Callable:
        """
        9-Gate Constitutional Check - ALL gates must pass
        
        Gate ordering matches Constitutional Cascade (CRITICAL vs non-critical):
        - Critical gates (1-5): TII, FRPC, RR, Integrity, Monte Carlo
        - Risk gates (6-7): Propfirm, Drawdown
        - System gates (8-9): Latency, Conf12
        """

        def condition(ctx: WolfContext) -> bool:
            # Gate 6: Propfirm compliance - use bool() to avoid identity check
            propfirm_compliant = bool(
                ctx.layer_outputs.get("L6", {}).get("propfirm_compliant", False)
            )
            
            gates = [
                WolfConditions.tii_check(0.93)(ctx),  # Gate 1
                WolfConditions.frpc_check(0.96)(ctx),  # Gate 2
                WolfConditions.rr_check(2.0)(ctx),  # Gate 3
                WolfConditions.integrity_check(0.97)(ctx),  # Gate 4
                WolfConditions.monte_carlo_check(0.68)(ctx),  # Gate 5 (constitutional 68%)
                propfirm_compliant,  # Gate 6
                ctx.layer_outputs.get("L6", {}).get("drawdown", 100) <= 2.5,  # Gate 7
                True,  # Gate 8: Latency (always pass for non-automated)
                ctx.layer_outputs.get("L7", {}).get("conf12", 0) >= 0.75,  # Gate 9
            ]
            ctx.gates_passed = sum(gates)
            return all(gates)

        return condition

    # ═══════════════════════════════════════════════════════════════
    # F-T ALIGNMENT CHECK (Gerbang Akhir Kondisi 1)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def ft_alignment_check() -> Callable:
        """Check F (Fundamental) dan T (Technical) tidak conflict"""

        def condition(ctx: WolfContext) -> bool:
            f_bias = ctx.layer_outputs.get("L1", {}).get("cognitive_bias", "NEUTRAL")
            t_bias = ctx.layer_outputs.get("L3", {}).get("technical_bias", "NEUTRAL")

            # NEUTRAL aligned dengan apapun
            if f_bias == "NEUTRAL" or t_bias == "NEUTRAL":
                return True

            # Must be same direction
            return f_bias == t_bias

        return condition
