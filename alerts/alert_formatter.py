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

    @staticmethod
    def format_feed_stale(symbol: str, age_seconds: float) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
🔴 FEED STALE
────────────────────────────
Symbol   : {symbol}
Last Tick : {age_seconds:.1f}s ago
Severity : {"CRITICAL" if age_seconds > 30 else "WARNING"}
{ts}
────────────────────────────
"""

    @staticmethod
    def format_drawdown_alert(
        account_id: str,
        drawdown_percent: float,
        daily_loss_percent: float,
        severity: str,
    ) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
💰 DRAWDOWN ALERT — {severity}
────────────────────────────
Account     : {account_id}
Drawdown    : {drawdown_percent:.2f}%
Daily Loss  : {daily_loss_percent:.2f}%
{ts}
────────────────────────────
"""

    @staticmethod
    def format_kill_switch(reason: str) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
🛑 KILL SWITCH TRIPPED
════════════════════════════
ALL TRADING HALTED
Reason : {reason}
{ts}
════════════════════════════
"""

    @staticmethod
    def format_circuit_breaker(name: str, state: str, failures: int) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
⚡ CIRCUIT BREAKER — {state}
────────────────────────────
Service    : {name}
State      : {state}
Failures   : {failures}
{ts}
────────────────────────────
"""

    @staticmethod
    def format_pipeline_latency(
        latency_seconds: float,
        stage: str,
    ) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
⏱️ PIPELINE LATENCY HIGH
────────────────────────────
Stage    : {stage}
Latency  : {latency_seconds:.3f}s
{ts}
────────────────────────────
"""
