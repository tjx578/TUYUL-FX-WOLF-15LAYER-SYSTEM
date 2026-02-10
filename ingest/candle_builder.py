import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Union

from loguru import logger

from context.live_context_bus import LiveContextBus


class CandleBuilder:
    """
    Tick → M15 / H1 candle builder.
    
    Pure data aggregation. Handles both Unix timestamps (float)
    and datetime objects.
    """

    def __init__(self) -> None:
        self.context_bus = LiveContextBus()
        self.buffers = defaultdict(list)

    async def run(self) -> None:
        """Main candle building loop."""
        logger.info("CandleBuilder started (M15 / H1)")
        while True:
            await self.process_ticks()
            await asyncio.sleep(1)

    async def process_ticks(self) -> None:
        """Process ticks and build candles."""
        ticks = self.context_bus.consume_ticks()

        for tick in ticks:
            symbol = tick["symbol"]
            self.buffers[symbol].append(tick)

            self._try_build(symbol, "M15", minutes=15)
            self._try_build(symbol, "H1", minutes=60)

    def _try_build(self, symbol: str, tf: str, minutes: int) -> None:
        """
        Try to build a candle for the given symbol and timeframe.
        
        Args:
            symbol: Trading pair symbol
            tf: Timeframe (M15 or H1)
            minutes: Number of minutes for the timeframe
        """
        buffer = self.buffers[symbol]
        if not buffer:
            return

        # Convert timestamp to datetime if needed
        first_ts = self._normalize_timestamp(buffer[0]["timestamp"])
        start_time = self._floor_time(first_ts, minutes)
        end_time = start_time + timedelta(minutes=minutes)

        # Filter ticks for this candle period
        candles = []
        for t in buffer:
            tick_ts = self._normalize_timestamp(t["timestamp"])
            if start_time <= tick_ts < end_time:
                candles.append(t)
        
        if not candles:
            return

        prices = [c["bid"] for c in candles if c["bid"] is not None]
        
        if not prices:
            return

        candle = {
            "symbol": symbol,
            "timeframe": tf,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "timestamp": end_time,
        }

        self.context_bus.update_candle(candle)
        
        # Clean buffer: keep only ticks after this candle
        self.buffers[symbol] = [
            t for t in buffer
            if self._normalize_timestamp(t["timestamp"]) >= end_time
        ]

        logger.debug(f"{symbol} {tf} candle built: O={candle['open']:.5f}")

    @staticmethod
    def _normalize_timestamp(ts: Union[float, datetime]) -> datetime:
        """
        Normalize timestamp to datetime object.
        
        Args:
            ts: Unix timestamp (float) or datetime object
            
        Returns:
            Timezone-aware datetime in UTC
        """
        if isinstance(ts, datetime):
            # Ensure timezone-aware
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)
        
        # Unix timestamp (float) - convert to datetime
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    @staticmethod
    def _floor_time(dt: datetime, minutes: int) -> datetime:
        """
        Floor datetime to the nearest interval.
        
        Args:
            dt: Datetime to floor
            minutes: Interval in minutes (15 or 60)
            
        Returns:
            Floored datetime
        """
        return dt - timedelta(
            minutes=dt.minute % minutes,
            seconds=dt.second,
            microseconds=dt.microsecond,
        )
