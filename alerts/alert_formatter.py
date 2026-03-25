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

    @staticmethod
    def format_heartbeat_absent(age_seconds: float) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
💔 HEARTBEAT ABSENT
────────────────────────────
Last heartbeat seen : {age_seconds:.1f}s ago
Impact             : Operator dashboard may be stale
{ts}
────────────────────────────
"""

    @staticmethod
    def format_mass_staleness(stale_count: int, total_symbols: int, threshold_seconds: float) -> str:
        ts = format_dual_timezone(now_utc())

        return f"""
🧊 MASS FEED STALENESS
────────────────────────────
Stale symbols : {stale_count}/{total_symbols}
Threshold     : > {threshold_seconds:.0f}s
Impact        : Market feed likely degraded upstream
{ts}
────────────────────────────
"""

    # ═══════════════════════════════════════════════════════
    #  P2-8: Latency budget + anomaly rate formatters
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def format_v11_latency_budget(
        symbol: str,
        p95_ms: float,
        p99_ms: float,
        budget_ms: float,
        severity: str,
    ) -> str:
        ts = format_dual_timezone(now_utc())
        return f"""
⏱️ V11 LATENCY BUDGET — {severity}
────────────────────────────
Symbol  : {symbol}
p95     : {p95_ms:.1f}ms
p99     : {p99_ms:.1f}ms
Budget  : {budget_ms:.0f}ms
{ts}
────────────────────────────
"""

    @staticmethod
    def format_exec_latency_budget(
        stage: str,
        p95_ms: float,
        p99_ms: float,
        budget_ms: float,
    ) -> str:
        ts = format_dual_timezone(now_utc())
        return f"""
⏱️ EXECUTION LATENCY BUDGET BREACH
────────────────────────────
Stage   : {stage}
p95     : {p95_ms:.1f}ms
p99     : {p99_ms:.1f}ms
Budget  : {budget_ms:.0f}ms
{ts}
────────────────────────────
"""

    @staticmethod
    def format_anomaly_rate(
        metric_name: str,
        rate: float,
        threshold: float,
        severity: str,
        window_count: int,
    ) -> str:
        ts = format_dual_timezone(now_utc())
        return f"""
📊 ANOMALY RATE — {severity}
────────────────────────────
Metric    : {metric_name}
Rate      : {rate:.1%}
Threshold : {threshold:.1%}
Window    : last {window_count} samples
{ts}
────────────────────────────
"""

    @staticmethod
    def format_reconnect_storm() -> str:
        ts = format_dual_timezone(now_utc())
        return f"""
🌊 RECONNECT STORM DETECTED
────────────────────────────
Multiple rapid reconnects in short window.
Latency and data freshness may be degraded.
{ts}
────────────────────────────
"""

    @staticmethod
    def format_execute_signal(
        symbol: str,
        verdict: str,
        confidence: float,
        direction: str | None,
        entry_price: float | None,
        stop_loss: float | None,
        take_profit_1: float | None,
        risk_reward_ratio: float | None,
    ) -> str:
        ts = format_dual_timezone(now_utc())
        dir_arrow = "▲ BUY" if direction == "BUY" else "▼ SELL" if direction == "SELL" else "—"
        entry_str = f"{entry_price:.5f}" if entry_price else "—"
        sl_str = f"{stop_loss:.5f}" if stop_loss else "—"
        tp_str = f"{take_profit_1:.5f}" if take_profit_1 else "—"
        rr_str = f"1:{risk_reward_ratio:.1f}" if risk_reward_ratio else "—"
        return f"""
🐺🟢 EXECUTE SIGNAL — HIGH PROBABILITY
════════════════════════════════
Symbol     : <b>{symbol}</b>
Direction  : {dir_arrow}
Verdict    : {verdict}
Confidence : {confidence:.0%}
────────────────────────────
Entry      : {entry_str}
Stop Loss  : {sl_str}
TP-1       : {tp_str}
R:R        : {rr_str}
{ts}
════════════════════════════════
"""
