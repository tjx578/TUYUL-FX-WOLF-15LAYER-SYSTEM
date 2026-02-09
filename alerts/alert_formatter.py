"""
Alert Formatter
Produces human-readable alerts (GBPJPY style).
"""

from datetime import datetime


class AlertFormatter:
    @staticmethod
    def format_l12_verdict(verdict: dict) -> str:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        return f"""
🐺 WOLF 15-LAYER — L12 VERDICT
────────────────────────────
Symbol      : {verdict.get("symbol")}
Verdict    : {verdict.get("verdict")}
Confidence : {verdict.get("confidence")}
Mode       : {verdict.get("execution_mode")}
Time       : {ts}
────────────────────────────
"""

    @staticmethod
    def format_order_event(event: str, state: dict) -> str:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        return f"""
📌 ORDER UPDATE — {event}
────────────────────────────
State     : {state.get("state")}
Symbol    : {state.get("order", {}).get("symbol")}
Direction : {state.get("order", {}).get("direction")}
Entry     : {state.get("order", {}).get("entry")}
SL        : {state.get("order", {}).get("sl")}
TP        : {state.get("order", {}).get("tp")}
Time      : {ts}
────────────────────────────
"""

    @staticmethod
    def format_violation(symbol: str, gate: str, reason: str) -> str:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        return f"""
🚫 CONSTITUTION VIOLATION
────────────────────────────
Symbol : {symbol}
Gate   : {gate}
Reason : {reason}
Time   : {ts}
────────────────────────────
"""
