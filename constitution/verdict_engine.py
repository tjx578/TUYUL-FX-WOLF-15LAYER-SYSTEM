

def meta_gate_structural_edge(exhaustion_conf: float, liquidity: float) -> bool:
    return min(exhaustion_conf, liquidity) >= 0.70

def meta_gate_model_integrity(tii: float, frpc: float, integrity: float, thresholds: dict[str, float]) -> str:
    pass_all = tii >= thresholds["tii"] and frpc >= thresholds["frpc"] and integrity >= thresholds["integrity"]
    conditional = (
        (thresholds["tii"] - 0.03 <= tii < thresholds["tii"])
        or (thresholds["frpc"] - 0.03 <= frpc < thresholds["frpc"])
        or (thresholds["integrity"] - 0.02 <= integrity < thresholds["integrity"])
    )
    if pass_all:
        return "PASS"
    elif conditional:
        return "CONDITIONAL"
    return "FAIL"

def meta_gate_statistical_edge(mc_win: float, mc_pf: float, rr: float, posterior: float, thresholds: dict[str, float]) -> bool:
    return (
        mc_win >= thresholds["mc_win"]
        and mc_pf >= thresholds["mc_pf"]
        and rr >= thresholds["rr"]
        and posterior >= thresholds["posterior"]
    )

def layer12_verdict_layer(meta_results: dict[str, str]) -> str:
    pass_count = sum(1 for v in meta_results.values() if v == "PASS")
    conditional_count = sum(1 for v in meta_results.values() if v == "CONDITIONAL")
    if pass_count == 3:
        return "EXECUTE"
    elif pass_count == 2 and conditional_count == 1:
        return "EXECUTE_REDUCED_RISK"
    return "HOLD"

    def evaluate(
        self,
        wolf_score: float,
        tii_score: float,
        frpc_score: float,
        exhaustion_input: ExhaustionLayerInput | None = None,  # noqa: F821
    ) -> dict[str, Any]:  # noqa: F821
        """
        Constitutional verdict evaluation.

        Returns:
            {
                "verdict": "EXECUTE" | "HOLD" | "NO_TRADE" | "ABORT",
                "confidence": float,
                "reason": str,
                "gate_results": dict,  # Per-layer pass/fail
            }
        """
        gate_results = {}
        rejection_reasons = []

        # Gate 1: Wolf (L1-L6 fusion)
        wolf_pass = wolf_score >= self.thresholds.wolf_min_score
        gate_results["wolf"] = {
            "pass": wolf_pass,
            "score": wolf_score,
            "threshold": self.thresholds.wolf_min_score,
        }
        if not wolf_pass:
            rejection_reasons.append(f"WOLF_WEAK: {wolf_score:.2f} < {self.thresholds.wolf_min_score}")

        # Gate 2: TII (L8)
        tii_pass = tii_score >= self.thresholds.tii_min_score
        gate_results["tii"] = {
            "pass": tii_pass,
            "score": tii_score,
            "threshold": self.thresholds.tii_min_score,
        }
        if not tii_pass:
            rejection_reasons.append(f"TII_WEAK: {tii_score:.2f} < {self.thresholds.tii_min_score}")

        # Gate 3: FRPC (L9)
        frpc_pass = frpc_score >= self.thresholds.frpc_min_score
        gate_results["frpc"] = {
            "pass": frpc_pass,
            "score": frpc_score,
            "threshold": self.thresholds.frpc_min_score,
        }
        if not frpc_pass:
            rejection_reasons.append(f"FRPC_WEAK: {frpc_score:.2f} < {self.thresholds.frpc_min_score}")

        # Gate 4: Exhaustion (L7) — ✅ NEW GATE
        exhaustion_pass = True  # Default if not provided
        if exhaustion_input:
            # Check for data availability FIRST
            if exhaustion_input.missing_tfs:
                exhaustion_pass = False
                gate_results["exhaustion"] = {
                    "pass": False,
                    "score": 0.0,
                    "confidence": 0.0,
                    "abort_reason": f"INSUFFICIENT_DATA: Missing {exhaustion_input.missing_tfs}",
                }
                return {
                    "verdict": "ABORT",
                    "confidence": 0.0,
                    "reason": f"EXHAUSTION_DATA_UNAVAILABLE: {', '.join(exhaustion_input.missing_tfs)}",
                    "gate_results": gate_results,
                }

            # Data is available, check thresholds
            exhaustion_pass = (
                exhaustion_input.confidence >= self.thresholds.exhaustion_min_confidence
                and exhaustion_input.score >= self.thresholds.exhaustion_min_score
            )
            gate_results["exhaustion"] = {
                "pass": exhaustion_pass,
                "score": exhaustion_input.score,
                "confidence": exhaustion_input.confidence,
                "threshold_confidence": self.thresholds.exhaustion_min_confidence,
                "threshold_score": self.thresholds.exhaustion_min_score,
                "reason": exhaustion_input.reason,
            }
            if not exhaustion_pass:
                rejection_reasons.append(
                    f"EXHAUSTION_WEAK: conf={exhaustion_input.confidence:.2f} < {self.thresholds.exhaustion_min_confidence} "
                    f"or score={exhaustion_input.score:.2f} < {self.thresholds.exhaustion_min_score}"
                )

        # Final verdict logic
        all_gates_pass = wolf_pass and tii_pass and frpc_pass and exhaustion_pass

        if all_gates_pass:
            # Calculate overall confidence (weighted average)
            weights = {"wolf": 0.3, "tii": 0.25, "frpc": 0.25, "exhaustion": 0.2}
            overall_confidence = (
                wolf_score * weights["wolf"]
                + tii_score * weights["tii"]
                + frpc_score * weights["frpc"]
                + (exhaustion_input.score if exhaustion_input else 0.0) * weights["exhaustion"]
            )

            return {
                "verdict": "EXECUTE",
                "confidence": round(overall_confidence, 3),
                "reason": "ALL_GATES_PASSED",
                "gate_results": gate_results,
            }

        # Some gates failed
        if rejection_reasons:
            return {
                "verdict": "NO_TRADE",
                "confidence": 0.0,
                "reason": " | ".join(rejection_reasons),
                "gate_results": gate_results,
            }

        # Fallback (should not reach here)
        return {
            "verdict": "HOLD",
            "confidence": 0.0,
            "reason": "EVALUATION_INCOMPLETE",
            "gate_results": gate_results,
        }
