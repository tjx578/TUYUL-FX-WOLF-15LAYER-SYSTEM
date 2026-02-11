"""
Core Orchestrator Layer 12

Contains: CoreOrchestratorLayer12 with TII, FRPC, MC_FTTC gates.
"""

from typing import Any


class CoreOrchestratorLayer12:
    """
    Layer 12 Orchestrator - Constitutional Gatekeeper.

    Enforces all constitutional gates before allowing trade execution.
    """

    def __init__(self):
        self.gates_config = {
            "tii_min": 0.93,
            "integrity_min": 0.97,
            "frpc_min": 0.75,
            "mc_win_min": 55.0,
            "fta_min": 65.0,
            "conf12_min": 0.88,
            "rr_min": 2.0,
        }

    def validate_tii_gate(self, tii_score: float) -> dict[str, bool]:
        """
        Validate TII (Technical-Integrity Index) gate.

        Args:
            tii_score: TII score from L8

        Returns:
            Dictionary with gate status
        """
        passed = tii_score >= self.gates_config["tii_min"]

        return {
            "gate": "TII",
            "passed": passed,
            "score": tii_score,
            "threshold": self.gates_config["tii_min"],
        }

    def validate_integrity_gate(self, integrity_score: float) -> dict[str, bool]:
        """
        Validate Integrity gate.

        Args:
            integrity_score: Integrity index from L8

        Returns:
            Dictionary with gate status
        """
        passed = integrity_score >= self.gates_config["integrity_min"]

        return {
            "gate": "INTEGRITY",
            "passed": passed,
            "score": integrity_score,
            "threshold": self.gates_config["integrity_min"],
        }

    def validate_frpc_gate(self, frpc_score: float) -> dict[str, bool]:
        """
        Validate FRPC (Field-Risk-Probability-Confidence) gate.

        Args:
            frpc_score: FRPC composite score

        Returns:
            Dictionary with gate status
        """
        passed = frpc_score >= self.gates_config["frpc_min"]

        return {
            "gate": "FRPC",
            "passed": passed,
            "score": frpc_score,
            "threshold": self.gates_config["frpc_min"],
        }

    def validate_mc_fttc_gate(
        self,
        mc_win_probability: float,
        fta_score: float,
    ) -> dict[str, bool]:
        """
        Validate MC_FTTC (Monte Carlo + FTA) gate.

        Args:
            mc_win_probability: Monte Carlo win probability (%)
            fta_score: Fundamental-Technical Alignment score

        Returns:
            Dictionary with gate status
        """
        mc_passed = mc_win_probability >= self.gates_config["mc_win_min"]
        fta_passed = fta_score >= self.gates_config["fta_min"]
        passed = mc_passed and fta_passed

        return {
            "gate": "MC_FTTC",
            "passed": passed,
            "mc_win_probability": mc_win_probability,
            "fta_score": fta_score,
            "mc_threshold": self.gates_config["mc_win_min"],
            "fta_threshold": self.gates_config["fta_min"],
        }

    def validate_conf12_gate(self, conf12: float) -> dict[str, bool]:
        """
        Validate CONF12 (Layer 12 Confidence) gate.

        Args:
            conf12: Confidence score from L9 or composite

        Returns:
            Dictionary with gate status
        """
        passed = conf12 >= self.gates_config["conf12_min"]

        return {
            "gate": "CONF12",
            "passed": passed,
            "score": conf12,
            "threshold": self.gates_config["conf12_min"],
        }

    def validate_rr_gate(self, rr_ratio: float) -> dict[str, bool]:
        """
        Validate Risk-Reward ratio gate.

        Args:
            rr_ratio: Risk-reward ratio

        Returns:
            Dictionary with gate status
        """
        passed = rr_ratio >= self.gates_config["rr_min"]

        return {
            "gate": "RR_RATIO",
            "passed": passed,
            "score": rr_ratio,
            "threshold": self.gates_config["rr_min"],
        }

    def orchestrate(self, synthesis: dict[str, Any]) -> dict[str, Any]:
        """
        Orchestrate all Layer 12 gates.

        Args:
            synthesis: Complete synthesis output with all layer data

        Returns:
            Dictionary with orchestration verdict
        """
        layers = synthesis.get("layers", {})
        scores = synthesis.get("scores", {})
        execution = synthesis.get("execution", {})

        # Run all gates
        gates = []

        # TII Gate
        tii_result = self.validate_tii_gate(layers.get("L8_tii_sym", 0.0))
        gates.append(tii_result)

        # Integrity Gate
        integrity_result = self.validate_integrity_gate(layers.get("L8_integrity_index", 0.0))
        gates.append(integrity_result)

        # MC_FTTC Gate
        mc_fttc_result = self.validate_mc_fttc_gate(
            layers.get("L7_monte_carlo_win", 0.0),
            scores.get("fta_score", 0.0),
        )
        gates.append(mc_fttc_result)

        # CONF12 Gate
        conf12_result = self.validate_conf12_gate(layers.get("conf12", 0.0))
        gates.append(conf12_result)

        # RR Gate
        rr_result = self.validate_rr_gate(execution.get("rr_ratio", 0.0))
        gates.append(rr_result)

        # Determine final verdict
        all_passed = all(gate["passed"] for gate in gates)
        verdict = "APPROVED" if all_passed else "REJECTED"

        # Count violations
        violations = [gate["gate"] for gate in gates if not gate["passed"]]

        return {
            "verdict": verdict,
            "gates_checked": len(gates),
            "gates_passed": sum(1 for g in gates if g["passed"]),
            "gates_failed": len(violations),
            "violations": violations,
            "gate_results": gates,
            "valid": True,
        }
