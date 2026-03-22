"""Liquidity Zone Mapper -- SMC institutional level tracking."""

from datetime import UTC, datetime
from typing import Any

from ._types import (
    DEFAULT_EQUAL_LEVEL_TOLERANCE,
    DEFAULT_SWING_LOOKBACK,
    LiquidityMapResult,
    LiquidityStatus,
    LiquidityType,
    LiquidityZone,
)


class LiquidityZoneMapper:
    """Maps liquidity zones for smart money concept trading."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {
            "swing_lookback": DEFAULT_SWING_LOOKBACK,
            "equal_level_tolerance": DEFAULT_EQUAL_LEVEL_TOLERANCE,
            "min_touches_for_equal": 2,
            "zone_expiry_bars": 100,
            "strength_decay_rate": 0.95,
        }

    def map_liquidity(
        self, ohlcv_data: list[dict[str, Any]], pair: str, timeframe: str, current_price: float
    ) -> LiquidityMapResult:
        ts = datetime.now(UTC)
        sh = self._swing_highs(ohlcv_data)
        sl = self._swing_lows(ohlcv_data)
        eh = self._equal_levels(sh, "high")
        el = self._equal_levels(sl, "low")
        bsz = self._buy_zones(sh, eh, timeframe)
        ssz = self._sell_zones(sl, el, timeframe)
        return LiquidityMapResult(
            timestamp=ts,
            pair=pair,
            buy_side_zones=bsz,
            sell_side_zones=ssz,
            nearest_buy_liquidity=self._nearest(bsz, current_price, "above"),
            nearest_sell_liquidity=self._nearest(ssz, current_price, "below"),
            liquidity_imbalance=self._imbalance(bsz, ssz, current_price),
        )

    def _swing_highs(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._find_swings(data, "high", lambda a, b: a > b)

    def _swing_lows(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._find_swings(data, "low", lambda a, b: a < b)

    def _find_swings(self, data, key, compare_fn) -> list[dict[str, Any]]:
        lb = self.config["swing_lookback"]
        swings = []
        for i in range(lb, len(data) - lb):
            cur = data[i].get(key, 0)
            ok = True
            for j in range(i - lb, i + lb + 1):
                if j != i and compare_fn(data[j].get(key, 0), cur):
                    ok = False
                    break
            if ok:
                swings.append({"price": cur, "index": i})
        return swings

    def _equal_levels(self, swings: list[dict[str, Any]], level_type: str) -> list[dict[str, Any]]:
        tol = self.config["equal_level_tolerance"]
        mt = self.config["min_touches_for_equal"]
        used: set = set()
        levels = []
        for i, s in enumerate(swings):
            if i in used:
                continue
            sim = [s]
            for j, o in enumerate(swings):
                if j != i and j not in used and s["price"] != 0:
                    if abs(s["price"] - o["price"]) / s["price"] < tol:
                        sim.append(o)
                        used.add(j)
            if len(sim) >= mt:
                levels.append({"price": sum(x["price"] for x in sim) / len(sim), "touches": len(sim)})
                used.add(i)
        return levels

    def _buy_zones(self, sh, eh, tf) -> list[LiquidityZone]:
        ts = datetime.now(UTC)
        zones = []
        for s in sh:
            zones.append(
                LiquidityZone(
                    zone_type=LiquidityType.SWING_HIGH,
                    status=LiquidityStatus.UNTAPPED,
                    price_level=s["price"],
                    price_range=(s["price"], s["price"] * 1.001),
                    strength=60.0,
                    touch_count=1,
                    created_at=ts,
                    last_tested=None,
                    timeframe=tf,
                )
            )
        for e in eh:
            zones.append(
                LiquidityZone(
                    zone_type=LiquidityType.EQUAL_HIGHS,
                    status=LiquidityStatus.UNTAPPED,
                    price_level=e["price"],
                    price_range=(e["price"], e["price"] * 1.001),
                    strength=80.0 + min(20, e["touches"] * 5),
                    touch_count=e["touches"],
                    created_at=ts,
                    last_tested=None,
                    timeframe=tf,
                )
            )
        return zones

    def _sell_zones(self, sl, el, tf) -> list[LiquidityZone]:
        ts = datetime.now(UTC)
        zones = []
        for s in sl:
            zones.append(
                LiquidityZone(
                    zone_type=LiquidityType.SWING_LOW,
                    status=LiquidityStatus.UNTAPPED,
                    price_level=s["price"],
                    price_range=(s["price"] * 0.999, s["price"]),
                    strength=60.0,
                    touch_count=1,
                    created_at=ts,
                    last_tested=None,
                    timeframe=tf,
                )
            )
        for e in el:
            zones.append(
                LiquidityZone(
                    zone_type=LiquidityType.EQUAL_LOWS,
                    status=LiquidityStatus.UNTAPPED,
                    price_level=e["price"],
                    price_range=(e["price"] * 0.999, e["price"]),
                    strength=80.0 + min(20, e["touches"] * 5),
                    touch_count=e["touches"],
                    created_at=ts,
                    last_tested=None,
                    timeframe=tf,
                )
            )
        return zones

    def _nearest(self, zones: list[LiquidityZone], price: float, direction: str) -> float | None:
        valid = [
            z
            for z in zones
            if z.status != LiquidityStatus.FULLY_SWEPT
            and (z.price_level > price if direction == "above" else z.price_level < price)
        ]
        if not valid:
            return None
        return min(z.price_level for z in valid) if direction == "above" else max(z.price_level for z in valid)

    def _imbalance(self, buy: list[LiquidityZone], sell: list[LiquidityZone], price: float) -> float:
        bs = sum(z.strength for z in buy if z.price_level > price and z.status != LiquidityStatus.FULLY_SWEPT)
        ss = sum(z.strength for z in sell if z.price_level < price and z.status != LiquidityStatus.FULLY_SWEPT)
        t = bs + ss
        return (bs - ss) / t if t else 0.0
