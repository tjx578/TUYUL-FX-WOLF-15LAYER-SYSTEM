"""
Execution Guard
Final safety layer before any execution.
"""


class ExecutionGuard:
    def allow_execution(self, verdict: dict) -> bool:
        if not verdict:
            return False

        if verdict.get("verdict") not in ("EXECUTE_BUY", "EXECUTE_SELL"):
            return False

        if verdict.get("execution_mode") != "TP1_ONLY":
            return False

        # Hard lock: no market execution
        if verdict.get("order_type", "PENDING_ONLY") != "PENDING_ONLY":
            return False

        return True


# Placeholder
