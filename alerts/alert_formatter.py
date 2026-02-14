"""
Alert Formatter
Produces human-readable alerts (GBPJPY style).
"""

from utils.timezone_utils import format_dual_timezone, now_utc


class AlertFormatter:
    @staticmethod
    def format_l12_verdict(verdict: dict) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
🐺 WOLF 15-LAYER - L12 VERDICT
────────────────────────────
Symbol      : {verdict.get("symbol")}
Verdict    : {verdict.get("verdict")}
Confidence : {verdict.get("confidence")}
Mode       : {verdict.get("execution_mode")}
{ts}
────────────────────────────
"""

    @staticmethod
    def format_order_event(event: str, state: dict) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
📌 ORDER UPDATE - {event}
────────────────────────────
State     : {state.get("state")}
Symbol    : {state.get("order", {}).get("symbol")}
Direction : {state.get("order", {}).get("direction")}
Entry     : {state.get("order", {}).get("entry")}
SL        : {state.get("order", {}).get("sl")}
TP        : {state.get("order", {}).get("tp")}
{ts}
────────────────────────────
"""

    @staticmethod
    def format_violation(symbol: str, gate: str, reason: str) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
🚫 CONSTITUTION VIOLATION
────────────────────────────
Symbol : {symbol}
Gate   : {gate}
Reason : {reason}
{ts}
────────────────────────────
"""


# Placeholder
