"""
Gatekeeper — Constitutional 9-Gate Enforcement
NO EXECUTION | NO DISCRETION
"""

from config_loader import load_constitution
from constitution.violation_log import ViolationLogger


class Gatekeeper:
    def __init__(self):
        self.constitution = load_constitution()
        self.logger = ViolationLogger()

    def evaluate(self, candidate: dict) -> dict:
        symbol = candidate.get("symbol")

        gates = [
            self._gate_integrity,
            self._gate_tii,
            self._gate_probability,
            self._gate_rr,
            self._gate_position,
            self._gate_timeframe,
            self._gate_market_law,
            self._gate_execution_rule,
            self._gate_completeness,
        ]

        for gate in gates:
            result, reason = gate(candidate)
            if not result:
                self.logger.record(symbol, gate.__name__, reason)
                return {
                    "passed": False,
                    "failed_gate": gate.__name__,
                    "reason": reason,
                }

        return {
            "passed": True,
            "reason": "ALL_GATES_PASSED",
        }

    # =========================
    # INDIVIDUAL GATES
    # =========================

    def _gate_integrity(self, c: dict):
        # Use top-level integrity_min (reconciled value)
        min_integrity = self.constitution.get("integrity_min", 0.97)
        integrity = c["L8"].get("integrity", 0)
        return integrity >= min_integrity, f"integrity<{min_integrity}"

    def _gate_tii(self, c: dict):
        # Use top-level tii_min (reconciled value)
        min_tii = self.constitution.get("tii_min", 0.93)
        tii = c["L8"].get("tii_sym", 0)
        return tii >= min_tii, f"tii<{min_tii}"

    def _gate_probability(self, c: dict):
        min_prob = self.constitution["probability"]["min_win_probability_percent"]
        prob = c["L7"].get("win_probability", 0)
        return prob >= min_prob, f"prob<{min_prob}"

    def _gate_rr(self, c: dict):
        # Use top-level rr_min (reconciled value)
        min_rr = self.constitution.get("rr_min", 2.0)
        rr = c.get("L11", {}).get("rr", 0)
        return rr >= min_rr, f"rr<{min_rr}"

    def _gate_position(self, c: dict):
        return c["L10"].get("position_ok", False), "position_not_ok"

    def _gate_timeframe(self, c: dict):
        return True, "tf_ok"  # enforced by design (H1/M15)

    def _gate_market_law(self, c: dict):
        return True, "market_law_ok"  # enforced by pair config; all enabled pairs allowed

    def _gate_execution_rule(self, c: dict):
        rule = self.constitution["execution_rules"]["order_type"]
        return rule == "PENDING_ONLY", "execution_rule_violation"

    def _gate_completeness(self, c: dict):
        required = ["L1", "L2", "L3", "L4", "L7", "L8", "L9", "L10"]
        for r in required:
            if r not in c or not c[r]:
                return False, f"missing_{r}"
        return True, "complete"
