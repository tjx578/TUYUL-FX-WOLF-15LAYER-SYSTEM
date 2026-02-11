import asyncio

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from loguru import logger

from context.live_context_bus import LiveContextBus

TICK_TIMEFRAMES: dict[str, int] = {"M15": 15}


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
        logger.info("CandleBuilder started (M15 only - monitoring/cancel trigger)")
        while True:
            await self.process_ticks()
            await asyncio.sleep(1)

    async def process_ticks(self) -> None:
        """Process ticks and build candles."""
        ticks = self.context_bus.consume_ticks()

        for tick in ticks:
            symbol = tick["symbol"]
            self.buffers[symbol].append(tick)

            # Try building M15 candles only
            for tf, minutes in TICK_TIMEFRAMES.items():
                self._try_build(symbol, tf, minutes=minutes)

    def _try_build(self, symbol: str, tf: str, minutes: int) -> None:
        """
        Try to build a candle for the given symbol and timeframe.

        Args:
            symbol: Trading pair symbol
            tf: Timeframe (M15 only)
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
        period_ticks = []
        for t in buffer:
            tick_ts = self._normalize_timestamp(t["timestamp"])
            if start_time <= tick_ts < end_time:
                period_ticks.append(t)

        if not period_ticks:
            return

        # Use mid price if available, fallback to bid
        prices = []
        total_volume = 0.0

        for tick in period_ticks:
            mid_price = self._calculate_mid_price(tick)
            if mid_price is not None:
                prices.append(mid_price)

            # Sum real volume
            volume = tick.get("volume", 0)
            total_volume += volume

        if not prices:
            return

        # Use tick count as volume if all volumes are 0
        if total_volume == 0:
            total_volume = len(period_ticks)

        candle = {
            "symbol": symbol,
            "timeframe": tf,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": total_volume,
            "timestamp": end_time,
            "source": "tick_aggregation",
        }

        self.context_bus.update_candle(candle)

        # Clean buffer: keep only ticks after this candle
        self.buffers[symbol] = [
            t for t in buffer if self._normalize_timestamp(t["timestamp"]) >= end_time
        ]

        logger.debug(f"{symbol} {tf} candle built: O={candle['open']:.5f}")

    @staticmethod
    def _calculate_mid_price(tick: dict) -> float | None:
        """
        Calculate mid price from tick data.

        Prefers 'mid' field, then calculates from bid/ask,
        falls back to bid, ask, or last price.

        Args:
            tick: Tick data dict

        Returns:
            Mid price or None if no price available
        """
        # Prefer mid price (Finnhub uses 'last' or calculate from bid/ask)
        mid = tick.get("mid")
        if mid is not None:
            return mid

        bid = tick.get("bid")
        ask = tick.get("ask")

        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        if bid is not None:
            return bid
        if ask is not None:
            return ask

        return tick.get("last")

    @staticmethod
    def _normalize_timestamp(ts: float | datetime) -> datetime:
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
                return ts.replace(tzinfo=UTC)
            return ts.astimezone(UTC)

        # Unix timestamp (float) - convert to datetime
        return datetime.fromtimestamp(ts, tz=UTC)

    @staticmethod
    def _floor_time(dt: datetime, minutes: int) -> datetime:
        """
        Floor datetime to the nearest interval.

        Args:
            dt: Datetime to floor
            minutes: Interval in minutes (15, 60, 240, 1440, or 10080)

        Returns:
            Floored datetime
        """
        if minutes >= 10080:  # W1 — align to Monday 00:00 UTC
            days_since_monday = dt.weekday()
            return dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
                days=days_since_monday
            )
        if minutes >= 1440:  # D1 — align to midnight UTC
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if minutes >= 60:  # H1, H4 — floor hours
            hours = minutes // 60
            return dt.replace(
                hour=(dt.hour // hours) * hours,
                minute=0,
                second=0,
                microsecond=0,
            )
        # M15 etc
        return dt - timedelta(
            minutes=dt.minute % minutes,
            seconds=dt.second,
            microseconds=dt.microsecond,
        )
