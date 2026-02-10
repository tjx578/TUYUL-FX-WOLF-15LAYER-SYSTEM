import asyncio
import os
import time
from analysis.synthesis import build_synthesis   # L1–L11
from analysis.synthesis_adapter import adapt_synthesis
from constitution.verdict_engine import generate_l12_verdict
from storage.snapshot_store import save_snapshot
from storage.l12_cache import set_verdict
from context.runtime_state import RuntimeState
from config_loader import CONFIG
from journal.journal_router import journal_router
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from utils.timezone_utils import now_utc, is_trading_session
from loguru import logger

PAIRS = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]


def _build_j1(pair: str, synthesis: dict) -> ContextJournal:
    """
    Build J1 ContextJournal from synthesis data.
    
    Args:
        pair: Trading pair symbol
        synthesis: Synthesis output from adapt_synthesis
        
    Returns:
        ContextJournal instance
    """
    # Extract context from synthesis layers
    layers = synthesis.get("layers", {})
    bias = synthesis.get("bias", {})
    
    # Get trading session
    session = is_trading_session()
    
    # Build J1
    return ContextJournal(
        timestamp=now_utc(),
        pair=pair,
        session=session,
        market_regime=synthesis.get("market_regime", "UNKNOWN"),
        news_lock=synthesis.get("news_lock", False),
        context_coherence=layers.get("conf12", 0.5),
        mta_alignment=synthesis.get("mta_alignment", True),
        technical_bias=bias.get("technical", "NEUTRAL"),
    )


def _build_j2(pair: str, synthesis: dict, l12: dict) -> DecisionJournal:
    """
    Build J2 DecisionJournal from synthesis and L12 verdict.
    
    Args:
        pair: Trading pair symbol
        synthesis: Synthesis output from adapt_synthesis
        l12: L12 verdict output from generate_l12_verdict
        
    Returns:
        DecisionJournal instance
    """
    scores = synthesis.get("scores", {})
    layers = synthesis.get("layers", {})
    gates = l12.get("gates", {})
    
    # Build setup_id from pair and timestamp
    timestamp_str = now_utc().strftime("%Y%m%d_%H%M%S")
    setup_id = f"{pair}_{timestamp_str}"
    
    # Extract failed gates
    failed_gates = [
        gate_name for gate_name, gate_value in gates.items()
        if gate_name not in ["passed", "total"] and gate_value == "FAIL"
    ]
    
    # Determine primary rejection reason
    primary_rejection_reason = None
    if l12["verdict"] in [VerdictType.HOLD.value, VerdictType.NO_TRADE.value]:
        if failed_gates:
            primary_rejection_reason = f"Failed gates: {', '.join(failed_gates)}"
        else:
            primary_rejection_reason = "Constitutional violation"
    
    # Map verdict string to VerdictType enum
    verdict_str = l12["verdict"]
    verdict_type = VerdictType(verdict_str)
    
    # Build J2
    return DecisionJournal(
        timestamp=now_utc(),
        pair=pair,
        setup_id=setup_id,
        wolf_30_score=int(scores.get("wolf_30_point", 0)),
        f_score=int(scores.get("f_score", 0)),
        t_score=int(scores.get("t_score", 0)),
        fta_score=int(scores.get("fta_score", 0) * 10),  # Convert fta_score from 0-1 scale to 0-10 scale
        exec_score=int(scores.get("exec_score", 0)),
        tii_sym=float(layers.get("L8_tii_sym", 0.0)),
        integrity_index=float(layers.get("L8_integrity_index", 0.0)),
        monte_carlo_win=float(layers.get("L7_monte_carlo_win", 0.0)),
        conf12=float(layers.get("conf12", 0.0)),
        verdict=verdict_type,
        confidence=l12.get("confidence", "LOW"),
        wolf_status=l12.get("wolf_status", "NO_HUNT"),
        gates_passed=gates.get("passed", 0),
        gates_total=gates.get("total", 9),
        failed_gates=failed_gates,
        violations=[],  # Would be populated if available in L12
        primary_rejection_reason=primary_rejection_reason,
    )


def main_loop():
    """
    Main trading loop.

    If CONTEXT_MODE=redis, spawns RedisConsumer as a background task to
    receive live data from the ingest container.
    """
    # Check if we need to start Redis consumer
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    redis_consumer = None

    if context_mode == "redis":
        logger.info("CONTEXT_MODE=redis detected, starting RedisConsumer...")
        try:
            from context.redis_consumer import RedisConsumer
            redis_consumer = RedisConsumer(symbols=PAIRS)

            # Start consumer in a background thread using asyncio.run
            import threading

            def run_consumer():
                asyncio.run(redis_consumer.start())

            consumer_thread = threading.Thread(
                target=run_consumer, daemon=True, name="RedisConsumer"
            )
            consumer_thread.start()
            logger.info("RedisConsumer started in background thread")

        except Exception as exc:
            logger.error(
                f"Failed to start RedisConsumer: {exc}. "
                "Continuing without Redis consumer."
            )

    while True:
        for pair in PAIRS:
            try:
                # 1. Build analysis (L1-L11)
                raw_synthesis = build_synthesis(pair)

                # 2. Adapt contract
                synthesis = adapt_synthesis(raw_synthesis)

                # 3. Inject latency
                synthesis["system"]["latency_ms"] = RuntimeState.latency_ms

                # === JOURNAL J1: Record context (BEFORE L12) ===
                try:
                    j1 = _build_j1(pair, synthesis)
                    journal_router.record_context(j1)
                except Exception as journal_exc:
                    logger.error(f"J1 journal failed for {pair}: {journal_exc}")
                    # Continue execution — journal failures must not break trading loop

                # 4. L12 verdict
                l12 = generate_l12_verdict(synthesis)

                # === JOURNAL J2: Record decision (AFTER L12) ===
                try:
                    j2 = _build_j2(pair, synthesis, l12)
                    journal_router.record_decision(j2)
                except Exception as journal_exc:
                    logger.error(f"J2 journal failed for {pair}: {journal_exc}")
                    # Continue execution — journal failures must not break trading loop

                # 5. Cache verdict for EA
                set_verdict(pair, l12)

                # 6. Snapshot L14
                save_snapshot(pair, l12)

                print(f"[L12] {pair} → {l12['verdict']}")

            except Exception as e:
                print(f"[ERROR] {pair} | {e}")

        time.sleep(CONFIG["settings"].get("loop_interval_sec", 60))

if __name__ == "__main__":
    main_loop()
