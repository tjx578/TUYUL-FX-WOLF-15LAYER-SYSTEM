"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    🐺 WOLF 15-LAYER REASONING ENGINE                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Version      : v7.4r∞                                                       ║
║  Purpose      : Backend reasoning untuk Wolf 15-Layer Analysis               ║
║  Output       : Data untuk mengisi Wolf 15-Layer Template                    ║
║  Integration  : Advanced Reasoning Framework                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
#                              ENUMS & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════


class LayerState(Enum):
    """State untuk setiap layer"""

    PENDING = "pending"
    PROCESSING = "processing"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Verdict(Enum):
    """Final verdict options"""

    EXECUTE_BUY = "EXECUTE_BUY"
    EXECUTE_SELL = "EXECUTE_SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class WolfStatus(Enum):
    """Wolf hunt classification"""

    ALPHA_HUNT = "ALPHA_HUNT"  # 30/30 Perfect
    PACK_HUNT = "PACK_HUNT"  # 27-29 Excellent
    SCOUT = "SCOUT"  # 24-26 Good
    NO_HUNT = "NO_HUNT"  # <24 Fail


# ═══════════════════════════════════════════════════════════════════════════════
#                              DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class WolfContext:
    """Context yang dibawa antar layer"""

    pair: str = ""
    timestamp: str = ""
    current_price: float = 0.0

    # Layer outputs
    layer_states: dict[str, LayerState] = field(default_factory=dict)
    layer_outputs: dict[str, dict] = field(default_factory=dict)

    # Scores
    f_score: int = 0
    t_score: int = 0
    fta_score: float = 0.0
    wolf_30_score: int = 0
    psychology_score: int = 0

    # Thresholds & Gates
    gates_passed: int = 0
    total_gates: int = 9

    # Final decision variables
    verdict: Verdict | None = None
    wolf_status: WolfStatus | None = None
    confidence: str = ""

    # Execution parameters (TP1 ONLY)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    lot_size: float = 0.0
    rr_ratio: float = 0.0


@dataclass
class LayerResult:
    """Result dari setiap layer processing"""

    layer_name: str
    state: LayerState
    score: float
    passed_threshold: bool
    details: dict[str, Any]
    proceed_to_next: bool
    error_message: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
#                           WOLF CONDITIONS (Chain Validation)
# ═══════════════════════════════════════════════════════════════════════════════


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
    def wolf_30_check(threshold: int = 24) -> Callable:
        """L4: Wolf 30-Point ≥ 24"""

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
    def monte_carlo_check(threshold: float = 0.60) -> Callable:
        """L7: Monte Carlo Win% ≥ 60%"""

        def condition(ctx: WolfContext) -> bool:
            value = ctx.layer_outputs.get("L7", {}).get("win_probability", 0)
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
        """9-Gate Constitutional Check - ALL gates must pass"""

        def condition(ctx: WolfContext) -> bool:
            gates = [
                WolfConditions.tii_check(0.93)(ctx),  # Gate 1
                WolfConditions.frpc_check(0.96)(ctx),  # Gate 2
                WolfConditions.rr_check(2.0)(ctx),  # Gate 3
                WolfConditions.integrity_check(0.97)(ctx),  # Gate 4
                WolfConditions.monte_carlo_check(0.60)(ctx),  # Gate 5
                ctx.layer_outputs.get("L6", {}).get("propfirm_compliant", False),  # Gate 6
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


# ═══════════════════════════════════════════════════════════════════════════════
#                           WOLF ACTIONS (Scoring & Processing)
# ═══════════════════════════════════════════════════════════════════════════════


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
        f_checklist: list[bool],
        t_checklist: list[bool],
        fta_checklist: list[bool],
        exec_checklist: list[bool],
    ) -> Callable:
        """Calculate Wolf 30-Point Score"""

        def action(ctx: WolfContext) -> LayerResult:
            f_score = sum(f_checklist)
            t_score = sum(t_checklist)
            fta_score = sum(fta_checklist)
            exec_score = sum(exec_checklist)

            total = f_score + t_score + fta_score + exec_score

            ctx.f_score = f_score
            ctx.t_score = t_score
            ctx.wolf_30_score = total

            # Determine Wolf Status
            if total == 30:
                ctx.wolf_status = WolfStatus.ALPHA_HUNT
            elif total >= 27:
                ctx.wolf_status = WolfStatus.PACK_HUNT
            elif total >= 24:
                ctx.wolf_status = WolfStatus.SCOUT
            else:
                ctx.wolf_status = WolfStatus.NO_HUNT

            passed = total >= 24

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
                    "wolf_status": ctx.wolf_status.value,
                },
                proceed_to_next=passed,
            )

        return action

    @staticmethod
    def calculate_fta_score(
        f_score: int, t_score: int, tii_sym: float, monte_carlo: float
    ) -> Callable:
        """Calculate FTA Confidence Score"""

        def action(ctx: WolfContext) -> LayerResult:
            # FTA = (F/7 × 0.20) + (T/13 × 0.40) + (TII × 0.25) + (MC × 0.15)
            fta = (
                (f_score / 7) * 0.20 + (t_score / 13) * 0.40 + tii_sym * 0.25 + monte_carlo * 0.15
            ) * 100  # Convert to percentage

            ctx.fta_score = fta

            # Calculate multiplier
            if fta >= 65:
                multiplier = 1 + ((fta - 65) / 100)
            else:
                multiplier = 0.0  # No trade

            passed = fta >= 65

            return LayerResult(
                layer_name="L10_Position_Sizing",
                state=LayerState.PASSED if passed else LayerState.FAILED,
                score=fta,
                passed_threshold=passed,
                details={
                    "fta_score": round(fta, 2),
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
    def generate_verdict() -> Callable:
        """Generate Final Constitutional Verdict"""

        def action(ctx: WolfContext) -> LayerResult:
            # Check 3 Absolute Conditions
            ft_aligned = WolfConditions.ft_alignment_check()(ctx)
            fta_passed = ctx.fta_score >= 65
            exec_passed = ctx.wolf_30_score >= 24  # Simplified

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
                reason = f"Wolf Score < 24 ({ctx.wolf_30_score}/30)"
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
            elif ctx.wolf_30_score >= 21 and ctx.gates_passed >= 6:
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
                    "verdict": verdict.value,
                    "confidence": ctx.confidence,
                    "wolf_status": ctx.wolf_status.value if ctx.wolf_status else "UNKNOWN",
                    "gates_passed": ctx.gates_passed,
                    "reason": reason,
                    "checks": {
                        "ft_aligned": ft_aligned,
                        "fta_passed": fta_passed,
                        "exec_passed": exec_passed,
                        "nine_gate_passed": nine_gate_passed,
                    },
                },
                proceed_to_next=verdict in [Verdict.EXECUTE_BUY, Verdict.EXECUTE_SELL],
            )

        return action


# ═══════════════════════════════════════════════════════════════════════════════
#                        WOLF 15-LAYER REASONING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class Wolf15LayerEngine:
    """
    Main Reasoning Engine untuk Wolf 15-Layer Analysis.

    Pipeline:
    L1 → L2 → L3 → L4 → L5 → L6 → L7 → L8 → L9 → L10 → L11 → L12 → L13 → L14 → L15

    Setiap layer harus PASS sebelum lanjut ke layer berikutnya.
    Layer 12 adalah SOLE AUTHORITY untuk final decision.
    """

    def __init__(self):
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

    # ═══════════════════════════════════════════════════════════════
    # LAYER PROCESSORS
    # ═══════════════════════════════════════════════════════════════

    def process_layer_1(self, market_data: dict) -> LayerResult:
        """L1: Market Context Overview"""
        self.log("Processing L1: Market Context Overview")

        # Extract data
        regime = market_data.get("regime", "TRANSITIONAL")
        dominant_force = market_data.get("dominant_force", "MOMENTUM")
        cognitive_bias = market_data.get("cognitive_bias", "NEUTRAL")
        csi = market_data.get("csi", 0.90)

        # Calculate context coherence (simplified)
        context_coherence = csi * 0.95  # Weight by CSI

        # Store output
        self.context.layer_outputs["L1"] = {
            "regime": regime,
            "dominant_force": dominant_force,
            "cognitive_bias": cognitive_bias,
            "csi": csi,
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

    def process_layer_2(self, mta_data: dict) -> LayerResult:
        """L2: MTA Hierarchy Analysis"""
        self.log("Processing L2: MTA Hierarchy Analysis")

        # Extract MTA alignment
        mn_bias = mta_data.get("mn_bias", "NEUTRAL")
        w1_bias = mta_data.get("w1_bias", "NEUTRAL")
        d1_bias = mta_data.get("d1_bias", "NEUTRAL")
        h4_bias = mta_data.get("h4_bias", "NEUTRAL")
        h1_bias = mta_data.get("h1_bias", "NEUTRAL")

        biases = [mn_bias, w1_bias, d1_bias, h4_bias, h1_bias]

        # Calculate alignment score
        dominant = max(set(biases), key=biases.count)
        alignment_count = biases.count(dominant)
        alignment_score = alignment_count / 5

        # Calculate reflex coherence
        reflex_coherence = 0.70 + (alignment_score * 0.25)

        self.context.layer_outputs["L2"] = {
            "biases": {"MN": mn_bias, "W1": w1_bias, "D1": d1_bias, "H4": h4_bias, "H1": h1_bias},
            "alignment": f"{alignment_count}/5",
            "dominant_bias": dominant,
            "reflex_coherence": reflex_coherence,
            "phase": mta_data.get("phase", "EXPANSION"),
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

    def process_layer_4(self, checklist_data: dict) -> LayerResult:
        """L4: Wolf 30-Point Confluence Score"""
        self.log("Processing L4: Wolf 30-Point Confluence Score")

        f_checklist = checklist_data.get("fundamental", [True] * 7)
        t_checklist = checklist_data.get("technical", [True] * 13)
        fta_checklist = checklist_data.get("fta", [True] * 4)
        exec_checklist = checklist_data.get("execution", [True] * 6)

        action = WolfActions.calculate_wolf_30_score(
            f_checklist, t_checklist, fta_checklist, exec_checklist
        )
        result = action(self.context)

        self.context.layer_outputs["L4"] = result.details
        self.layer_results.append(result)
        self.context.layer_states["L4"] = result.state

        return result

    def process_layer_5(self, psychology_data: dict) -> LayerResult:
        """L5: Psychology Gates Assessment"""
        self.log("Processing L5: Psychology Gates Assessment")

        gate_scores = psychology_data.get("gate_scores", [8] * 10)

        action = WolfActions.calculate_psychology_score(gate_scores)
        result = action(self.context)

        self.context.layer_outputs["L5"] = result.details
        self.layer_results.append(result)
        self.context.layer_states["L5"] = result.state

        return result

    def process_layer_7(self, monte_carlo_data: dict) -> LayerResult:
        """L7: Monte Carlo FTTC Validation"""
        self.log("Processing L7: Monte Carlo FTTC Validation")

        win_prob = monte_carlo_data.get("win_probability", 0.65)
        profit_factor = monte_carlo_data.get("profit_factor", 1.8)
        conf12 = monte_carlo_data.get("conf12", 0.92)

        self.context.layer_outputs["L7"] = {
            "win_probability": win_prob,
            "profit_factor": profit_factor,
            "conf12": conf12,
            "validation": "PASS" if win_prob >= 0.60 else "FAIL",
        }

        passed = WolfConditions.monte_carlo_check(0.60)(self.context)

        result = LayerResult(
            layer_name="L7_Monte_Carlo",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=win_prob,
            passed_threshold=passed,
            details=self.context.layer_outputs["L7"],
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L7"] = result.state

        return result

    def process_layer_8(self, tii_data: dict) -> LayerResult:
        """L8: TIIₛᵧₘ Algo Precision Engine"""
        self.log("Processing L8: TIIₛᵧₘ Algo Precision Engine")

        tii_sym = tii_data.get("tii_sym", 0.93)
        integrity_index = tii_data.get("integrity_index", 0.97)
        twms_score = tii_data.get("twms_score", 10.5)

        self.context.layer_outputs["L8"] = {
            "tii_sym": tii_sym,
            "integrity_index": integrity_index,
            "twms_score": twms_score,
            "gate_status": "OPEN" if tii_sym >= 0.93 and integrity_index >= 0.97 else "CLOSED",
        }

        passed = WolfConditions.tii_check(0.93)(self.context) and WolfConditions.integrity_check(
            0.97
        )(self.context)

        result = LayerResult(
            layer_name="L8_TII_Validation",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=tii_sym,
            passed_threshold=passed,
            details=self.context.layer_outputs["L8"],
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L8"] = result.state

        return result

    def process_layer_9(self, smc_data: dict) -> LayerResult:
        """L9: SMC Integration Analysis"""
        self.log("Processing L9: SMC Integration Analysis")

        dvg_confidence = smc_data.get("dvg_confidence", 0.70)
        liquidity_score = smc_data.get("liquidity_score", 0.65)
        exhaustion_state = smc_data.get("exhaustion_state", "NEUTRAL")

        self.context.layer_outputs["L9"] = {
            "dvg_confidence": dvg_confidence,
            "liquidity_score": liquidity_score,
            "exhaustion_state": exhaustion_state,
            "smc_supports": "STRONGLY"
            if dvg_confidence >= 0.70 and liquidity_score >= 0.65
            else "WEAKLY",
        }

        passed = WolfConditions.dvg_confidence_check(0.70)(
            self.context
        ) and WolfConditions.liquidity_score_check(0.65)(self.context)

        result = LayerResult(
            layer_name="L9_SMC_Integration",
            state=LayerState.PASSED if passed else LayerState.FAILED,
            score=(dvg_confidence + liquidity_score) / 2,
            passed_threshold=passed,
            details=self.context.layer_outputs["L9"],
            proceed_to_next=passed,
        )

        self.layer_results.append(result)
        self.context.layer_states["L9"] = result.state

        return result

    def process_layer_12(self) -> LayerResult:
        """L12: Constitutional Verdict (SOLE AUTHORITY)"""
        self.log("Processing L12: Constitutional Verdict")

        action = WolfActions.generate_verdict()
        result = action(self.context)

        self.context.layer_outputs["L12"] = result.details
        self.layer_results.append(result)
        self.context.layer_states["L12"] = result.state

        return result

    # ═══════════════════════════════════════════════════════════════
    # FULL PIPELINE EXECUTION
    # ═══════════════════════════════════════════════════════════════

    def execute_full_pipeline(self, analysis_data: dict) -> dict:
        """
        Execute full 15-layer pipeline.

        Args:
            analysis_data: Dictionary containing all layer inputs

        Returns:
            Dictionary with all layer results and final verdict
        """
        self.log("=== WOLF 15-LAYER REASONING ENGINE START ===")
        self.reset()

        self.context.pair = analysis_data.get("pair", "UNKNOWN")
        self.context.timestamp = analysis_data.get("timestamp", "")
        self.context.current_price = analysis_data.get("current_price", 0.0)

        # Store technical bias early
        self.context.layer_outputs["L3"] = {
            "technical_bias": analysis_data.get("technical_bias", "NEUTRAL")
        }

        # Process layers sequentially
        # L1: Market Context
        l1_result = self.process_layer_1(analysis_data.get("L1", {}))
        if not l1_result.proceed_to_next:
            self.log("Pipeline stopped at L1")
            return self._generate_output()

        # L2: MTA Hierarchy
        l2_result = self.process_layer_2(analysis_data.get("L2", {}))
        if not l2_result.proceed_to_next:
            self.log("Pipeline stopped at L2")
            return self._generate_output()

        # L4: Wolf 30-Point
        l4_result = self.process_layer_4(analysis_data.get("L4", {}))
        if not l4_result.proceed_to_next:
            self.log("Pipeline stopped at L4")
            return self._generate_output()

        # L5: Psychology
        l5_result = self.process_layer_5(analysis_data.get("L5", {}))
        if not l5_result.proceed_to_next:
            self.log("Pipeline stopped at L5")
            return self._generate_output()

        # L6: Risk Management (simplified - store compliance)
        self.context.layer_outputs["L6"] = {
            "propfirm_compliant": analysis_data.get("L6", {}).get("propfirm_compliant", True),
            "drawdown": analysis_data.get("L6", {}).get("drawdown", 1.0),
        }

        # L7: Monte Carlo
        l7_result = self.process_layer_7(analysis_data.get("L7", {}))
        if not l7_result.proceed_to_next:
            self.log("Pipeline stopped at L7")
            return self._generate_output()

        # L8: TII
        l8_result = self.process_layer_8(analysis_data.get("L8", {}))
        if not l8_result.proceed_to_next:
            self.log("Pipeline stopped at L8")
            return self._generate_output()

        # L9: SMC Integration
        self.process_layer_9(analysis_data.get("L9", {}))

        # L10: Position Sizing (calculate FTA)
        fta_action = WolfActions.calculate_fta_score(
            self.context.f_score,
            self.context.t_score,
            self.context.layer_outputs["L8"]["tii_sym"],
            self.context.layer_outputs["L7"]["win_probability"],
        )
        l10_result = fta_action(self.context)
        self.context.layer_outputs["L10"] = l10_result.details
        self.layer_results.append(l10_result)

        # L11: RR Optimization (TP1 ONLY)
        execution_data = analysis_data.get("L11", {})
        direction = "BUY" if analysis_data.get("technical_bias", "BULLISH") == "BULLISH" else "SELL"
        rr_action = WolfActions.calculate_rr_optimization(
            execution_data.get("entry", 1.0850),
            execution_data.get("sl", 1.0820),
            execution_data.get("tp1", 1.0910),
            direction,
        )
        l11_result = rr_action(self.context)
        self.context.layer_outputs["L11"] = l11_result.details
        self.layer_results.append(l11_result)

        # L12: Constitutional Verdict
        self.process_layer_12()

        # L13-L15: Meta layers (simplified)
        self.context.layer_outputs["L13"] = {
            "frpc": analysis_data.get("L13", {}).get("frpc", 0.96),
            "lrce": analysis_data.get("L13", {}).get("lrce", 0.96),
            "field_energy": analysis_data.get("L13", {}).get("field_energy", 0.85),
        }

        self.log("=== WOLF 15-LAYER REASONING ENGINE COMPLETE ===")

        return self._generate_output()

    def _generate_output(self) -> dict:
        """Generate final output dictionary for template population"""
        return {
            "pair": self.context.pair,
            "timestamp": self.context.timestamp,
            "verdict": self.context.verdict.value if self.context.verdict else "NO_TRADE",
            "confidence": self.context.confidence,
            "wolf_status": self.context.wolf_status.value
            if self.context.wolf_status
            else "NO_HUNT",
            "scores": {
                "wolf_30": self.context.wolf_30_score,
                "f_score": self.context.f_score,
                "t_score": self.context.t_score,
                "fta_score": round(self.context.fta_score, 2),
                "psychology": self.context.psychology_score,
            },
            "gates": {"passed": self.context.gates_passed, "total": self.context.total_gates},
            "execution": {
                "entry": self.context.entry_price,
                "stop_loss": self.context.stop_loss,
                "take_profit_1": self.context.take_profit_1,
                "execution_mode": "TP1_ONLY",
                "rr_ratio": round(self.context.rr_ratio, 2),
                "lot_size": self.context.lot_size,
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


# ═══════════════════════════════════════════════════════════════════════════════
#                              TEMPLATE POPULATOR
# ═══════════════════════════════════════════════════════════════════════════════


class Wolf15LayerTemplatePopulator:
    """
    Mengisi Wolf 15-Layer Output Template dengan data dari Reasoning Engine.
    Format template TIDAK DIUBAH - hanya nilai yang diisi.
    """

    def __init__(self, engine_output: dict):
        self.data = engine_output

    def get_l4_scores(self) -> str:
        """Generate L4 score display"""
        scores = self.data["scores"]
        return f"""
F-Score: [{scores["f_score"]}/7] → F-Bias: [{"STRONG" if scores["f_score"] >= 5 else "WEAK"}]
T-Score: [{scores["t_score"]}/13] → T-Bias: [{"STRONG" if scores["t_score"] >= 9 else "WEAK"}]
Wolf 30: [{scores["wolf_30"]}/30] → Status: [{self.data["wolf_status"]}]
"""

    def get_l12_verdict(self) -> str:
        """Generate L12 verdict display"""
        return f"""
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║   ∴ FINAL VERDICT: {self.data["verdict"]:^40}   ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

CONFIDENCE : {self.data["confidence"]}
WOLF STATUS: {self.data["wolf_status"]}
GATES      : {self.data["gates"]["passed"]}/{self.data["gates"]["total"]}
"""

    def get_execution_table(self) -> str:
        """Generate execution parameters table (TP1 ONLY)"""
        exec_data = self.data["execution"]
        return f"""
┌─────────────────┬────────────────────┬────────────────────────────────┐
│ Entry           │ {exec_data["entry"]:<18} │ Constitutional entry          │
│ Stop Loss       │ {exec_data["stop_loss"]:<18} │ Structure invalidation        │
│ Take Profit 1   │ {exec_data["take_profit_1"]:<18} │ TP1_ONLY execution mode       │
│ RR Ratio        │ 1:{exec_data["rr_ratio"]:<16} │ {"≥ 1:2 PASS ✅" if exec_data["rr_ratio"] >= 2 else "< 1:2 FAIL ❌"}         │
│ Execution Mode  │ TP1_ONLY           │ Single target strategy        │
└─────────────────┴────────────────────┴────────────────────────────────┘
"""

    def to_json(self) -> str:
        """Export as JSON for L14"""
        return json.dumps(self.data, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
#                                   USAGE EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("🐺 WOLF 15-LAYER REASONING ENGINE - TEST RUN")
    print("=" * 70)

    # Create engine
    engine = Wolf15LayerEngine()

    # Sample analysis data
    sample_data = {
        "pair": "GBPUSD",
        "timestamp": "2025-02-06 15:30 GMT+8",
        "current_price": 1.2450,
        "technical_bias": "BULLISH",
        "L1": {
            "regime": "RISK_ON",
            "dominant_force": "MOMENTUM",
            "cognitive_bias": "BULLISH",
            "csi": 0.96,
        },
        "L2": {
            "mn_bias": "BULLISH",
            "w1_bias": "BULLISH",
            "d1_bias": "BULLISH",
            "h4_bias": "BULLISH",
            "h1_bias": "BULLISH",
            "phase": "EXPANSION",
        },
        "L4": {
            "fundamental": [True, True, True, True, True, True, False],  # 6/7
            "technical": [True] * 12 + [False],  # 12/13
            "fta": [True, True, True, True],  # 4/4
            "execution": [True] * 6,  # 6/6
        },
        "L5": {
            "gate_scores": [9, 8, 9, 8, 9, 8, 9, 8, 9, 8]  # 85/100
        },
        "L6": {"propfirm_compliant": True, "drawdown": 1.5},
        "L7": {"win_probability": 0.72, "profit_factor": 2.1, "conf12": 0.94},
        "L8": {"tii_sym": 0.95, "integrity_index": 0.98, "twms_score": 11.2},
        "L9": {
            "dvg_confidence": 0.75,
            "liquidity_score": 0.70,
            "exhaustion_state": "BUY_EXHAUSTION",
        },
        "L11": {"entry": 1.2450, "sl": 1.2410, "tp1": 1.2530},
        "L13": {"frpc": 0.97, "lrce": 0.96, "field_energy": 0.88},
    }

    # Execute pipeline
    result = engine.execute_full_pipeline(sample_data)

    # Display results
    print("\n" + "=" * 70)
    print("📊 EXECUTION RESULTS")
    print("=" * 70)

    print(f"\n🎯 VERDICT: {result['verdict']}")
    print(f"📈 CONFIDENCE: {result['confidence']}")
    print(f"🐺 WOLF STATUS: {result['wolf_status']}")
    print(f"🚪 GATES: {result['gates']['passed']}/{result['gates']['total']}")

    print("\n📊 SCORES:")
    print(f"   Wolf 30-Point: {result['scores']['wolf_30']}/30")
    print(f"   F-Score: {result['scores']['f_score']}/7")
    print(f"   T-Score: {result['scores']['t_score']}/13")
    print(f"   FTA Score: {result['scores']['fta_score']}%")
    print(f"   Psychology: {result['scores']['psychology']}/100")

    print("\n💹 EXECUTION (TP1_ONLY):")
    print(f"   Entry: {result['execution']['entry']}")
    print(f"   SL: {result['execution']['stop_loss']}")
    print(f"   TP1: {result['execution']['take_profit_1']}")
    print(f"   RR: 1:{result['execution']['rr_ratio']}")
    print(f"   Mode: {result['execution']['execution_mode']}")

    print("\n" + "=" * 70)
    print("✅ TEMPLATE POPULATION READY")
    print("=" * 70)

    # Create template populator
    populator = Wolf15LayerTemplatePopulator(result)
    print(populator.get_l12_verdict())
    print(populator.get_execution_table())
