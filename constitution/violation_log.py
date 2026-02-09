import logging

logger = logging.getLogger("WOLF_CONSTITUTION")


def log_violation(pair: str, reason: str) -> None:
    logger.warning("[L12 VIOLATION] Pair=%s | Reason=%s", pair, reason)
