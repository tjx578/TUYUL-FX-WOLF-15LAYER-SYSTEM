import asyncio
from collections import defaultdict
from datetime import timedelta
from loguru import logger

from context.live_context_bus import LiveContextBus


class CandleBuilder:
    """
    Tick → M15 / H1 candle builder
    Pure data aggregation
    """

    def __init__(self):
        self.context_bus = LiveContextBus()
        self.buffers = defaultdict(list)

    async def run(self):
        logger.info("CandleBuilder started (M15 / H1)")
        while True:
            await self.process_ticks()
            await asyncio.sleep(1)

    async def process_ticks(self):
        ticks = self.context_bus.consume_ticks()

        for tick in ticks:
            symbol = tick["symbol"]
            self.buffers[symbol].append(tick)

            self._try_build(symbol, "M15", minutes=15)
            self._try_build(symbol, "H1", minutes=60)

    def _try_build(self, symbol: str, tf: str, minutes: int):
        buffer = self.buffers[symbol]
        if not buffer:
            return

        start_time = self._floor_time(buffer[0]["timestamp"], minutes)
        end_time = start_time + timedelta(minutes=minutes)

        candles = [t for t in buffer if start_time <= t["timestamp"] < end_time]
        if not candles:
            return

        prices = [c["bid"] for c in candles if c["bid"] is not None]

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
        self.buffers[symbol] = [t for t in buffer if t["timestamp"] >= end_time]

        logger.debug(f"{symbol} {tf} candle built")

    @staticmethod
    def _floor_time(ts, minutes):
        return ts - timedelta(
            minutes=ts.minute % minutes,
            seconds=ts.second,
            microseconds=ts.microsecond,
        )
