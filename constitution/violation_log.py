import logging

logger = logging.getLogger("WOLF_CONSTITUTION")


def log_violation(pair: str, reason: str) -> None:
    logger.warning("[L12 VIOLATION] Pair=%s | Reason=%s", pair, reason)
"""
Violation Log
All constitutional violations must be recorded here.
"""

from datetime import datetime

from loguru import logger


class ViolationLogger:
    def __init__(self):
        self._violations = []

    def record(self, symbol: str, gate: str, reason: str):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "gate": gate,
            "reason": reason,
        }
        self._violations.append(entry)
        logger.warning(f"🚫 CONSTITUTION VIOLATION [{symbol}] {gate} → {reason}")

    def all(self):
        return list(self._violations)
# Placeholder
