from datetime import datetime

from utils.timezone_utils import now_utc


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
        cls.last_tick_at[pair] = now_utc()
