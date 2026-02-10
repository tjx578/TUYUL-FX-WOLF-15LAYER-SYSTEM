import time
from analysis.synthesis import build_synthesis   # L1–L11
from analysis.synthesis_adapter import adapt_synthesis
from constitution.verdict_engine import generate_l12_verdict
from storage.snapshot_store import save_snapshot
from storage.l12_cache import set_verdict
from context.runtime_state import RuntimeState
from config_loader import CONFIG

PAIRS = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

def main_loop():
    while True:
        for pair in PAIRS:
            try:
                # 1. Build analysis (L1-L11)
                raw_synthesis = build_synthesis(pair)

                # 2. Adapt contract
                synthesis = adapt_synthesis(raw_synthesis)

                # 3. Inject latency
                synthesis["system"]["latency_ms"] = RuntimeState.latency_ms

                # 4. L12 verdict
                l12 = generate_l12_verdict(synthesis)

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
