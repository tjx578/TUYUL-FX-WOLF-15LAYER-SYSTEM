from datetime import datetime
from typing import Optional

from utils.timezone_utils import now_utc


class RuntimeState:
    latency_ms: int = 0
    last_tick_at = {}
    last_candle_at = {}
    healthy: bool = True
    session_start: Optional[datetime] = None

    @classmethod
    def update_latency(cls, ms: int):
        cls.latency_ms = ms

    @classmethod
    def tick(cls, pair: str):
        cls.last_tick_at[pair] = now_utc()
    
    @classmethod
    def get_session_hours(cls) -> float:
        """
        Get hours since session start.
        
        Returns:
            Hours elapsed since session start (0.0 if not started)
        """
        if cls.session_start is None:
            cls.session_start = now_utc()
            return 0.0
        
        delta = now_utc() - cls.session_start
        return delta.total_seconds() / 3600.0
