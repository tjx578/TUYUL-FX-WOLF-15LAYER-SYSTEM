from datetime import datetime

class RuntimeState:
    latency_ms: int = 0
    last_tick_at = {}
    last_candle_at = {}
    healthy: bool = True

    @classmethod
    def update_latency(cls, ms: int):
        cls.latency_ms = ms

    @classmethod
    def tick(cls, pair: str):
        cls.last_tick_at[pair] = datetime.utcnow()
