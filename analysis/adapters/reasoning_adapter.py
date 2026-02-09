"""
FILE: reasoning_adapter.py
ROLE: READ-ONLY ADAPTER
PURPOSE:
- Convert sandbox reasoning output into
  synthesis-compatible candidate structure

CONSTITUTIONAL NOTICE:
- This adapter does NOT make decisions
- This adapter does NOT evaluate gates
- This adapter does NOT execute trades
- Final authority remains in Layer-12
"""

from typing import Any, Dict


class ReasoningToSynthesisAdapter:
    """
    Adapter resmi untuk menghubungkan:
    sandbox/reasoning -> analysis/synthesis
    """

    REQUIRED_FIELDS = [
        "pair",
        "verdict",
        "confidence",
        "scores",
        "layers",
        "execution",
        "gates",
    ]

    def __init__(self) -> None:
        self.read_only = True

    def validate_input(self, reasoning_output: Dict[str, Any]) -> None:
        """
        Validasi ringan: memastikan struktur minimum ada.
        BUKAN validasi konstitusional.
        """
        for field in self.REQUIRED_FIELDS:
            if field not in reasoning_output:
                raise ValueError(
                    f"[ADAPTER ERROR] Missing required field: {field}"
                )

    def to_candidate_setup(self, reasoning_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Konversi output reasoning -> candidate setup
        yang bisa dibaca synthesis.py
        """
        self.validate_input(reasoning_output)

        candidate = {
            # Identity
            "symbol": reasoning_output["pair"],
            "confidence": reasoning_output.get("confidence"),
            # Aggregated scores (L1-L11 summary only)
            "scores": {
                "wolf_30": reasoning_output["scores"].get("wolf_30_point"),
                "f_score": reasoning_output["scores"].get("f_score"),
                "t_score": reasoning_output["scores"].get("t_score"),
                "fta_score": reasoning_output["scores"].get("fta_score"),
                "technical_score": reasoning_output["scores"].get("technical_score"),
            },
            # Key validation metrics
            "metrics": {
                "tii": reasoning_output["layers"].get("L8_tii_sym"),
                "integrity": reasoning_output["layers"].get("L8_integrity_index"),
                "monte_carlo_win": reasoning_output["layers"].get("L7_monte_carlo_win"),
                "rr_ratio": reasoning_output["execution"].get("rr_ratio"),
            },
            # Execution PLAN (NOT execution)
            "execution_plan": {
                "entry_zone": reasoning_output["execution"].get("entry_zone"),
                "entry_price": reasoning_output["execution"].get("entry_price"),
                "stop_loss": reasoning_output["execution"].get("stop_loss"),
                "take_profit_1": reasoning_output["execution"].get("take_profit_1"),
                "lot_size": reasoning_output["execution"].get("lot_size"),
                "mode": reasoning_output["execution"].get("execution_mode"),
            },
            # Gate snapshot (READ ONLY)
            "gate_snapshot": {
                "passed": reasoning_output["gates"].get("total_passed"),
                "total": reasoning_output["gates"].get("total_gates"),
                "final_gate": reasoning_output.get("final_gate"),
            },
            # Traceability
            "source": "sandbox_reasoning_adapter",
            "read_only": True,
        }

        return candidate
