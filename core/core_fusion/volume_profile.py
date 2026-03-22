"""Volume Profile Analyzer -- POC, VAH, VAL, HVN, LVN."""

from datetime import UTC, datetime
from typing import Any

from ._types import VolumeProfileResult, VolumeZoneType


class VolumeProfileAnalyzer:
    """Analyzes volume-at-price for institutional zones."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {
            "value_area_percent": 0.70,
            "price_bins": 100,
            "hvn_threshold": 1.5,
            "lvn_threshold": 0.5,
            "min_volume_significance": 0.01,
        }

    def analyze(self, ohlcv: list[dict[str, Any]], pair: str, tf: str) -> VolumeProfileResult:
        ts = datetime.now(UTC)
        profile = self._build(ohlcv)
        poc = self._poc(profile)
        vah, val = self._va(profile)
        nodes = self._nodes(profile)
        shape = self._shape(profile, poc)
        tv = sum(v for _, v in profile)
        vav = sum(v for p, v in profile if val <= p <= vah)
        return VolumeProfileResult(
            timestamp=ts,
            pair=pair,
            timeframe=tf,
            poc_price=poc,
            vah_price=vah,
            val_price=val,
            value_area_percent=vav / tv if tv else 0,
            volume_nodes=nodes,
            total_volume=tv,
            profile_shape=shape,
        )

    def _build(self, ohlcv: list[dict[str, Any]]) -> list[tuple[float, float]]:
        if not ohlcv:
            return []
        ap = []
        [ap.extend([c.get("high", 0), c.get("low", 0)]) for c in ohlcv]
        if not ap:
            return []
        pmn, pmx = min(ap), max(ap)
        if pmx == pmn:
            return [(pmn, sum(c.get("volume", 0) for c in ohlcv))]
        nb = self.config["price_bins"]
        bs = (pmx - pmn) / nb
        vb: dict[int, float] = {i: 0.0 for i in range(nb)}
        for c in ohlcv:
            v = c.get("volume", 0)
            if v == 0:
                continue
            lo = max(0, min(nb - 1, int((c.get("low", 0) - pmn) / bs)))
            hi = max(0, min(nb - 1, int((c.get("high", 0) - pmn) / bs)))
            vpb = v / (hi - lo + 1)
            for b in range(lo, hi + 1):
                vb[b] += vpb
        return [(pmn + (i + 0.5) * bs, vb[i]) for i in range(nb)]

    def _poc(self, profile: list[tuple[float, float]]) -> float:
        if not profile:
            return 0.0
        return max(profile, key=lambda x: x[1])[0]

    def _va(self, profile: list[tuple[float, float]]) -> tuple[float, float]:
        if not profile:
            return 0.0, 0.0
        tv = sum(v for _, v in profile)
        target = tv * self.config["value_area_percent"]
        sp = sorted(profile, key=lambda x: x[1], reverse=True)
        cum = 0.0
        prices = []
        for p, v in sp:
            cum += v
            prices.append(p)
            if cum >= target:
                break
        return (max(prices), min(prices)) if prices else (profile[-1][0], profile[0][0])

    def _nodes(self, profile: list[tuple[float, float]]) -> list[dict[str, Any]]:
        if not profile:
            return []
        tv = sum(v for _, v in profile)
        avg = tv / len(profile) if profile else 0
        ht = avg * self.config["hvn_threshold"]
        lt = avg * self.config["lvn_threshold"]
        nodes = []
        for p, v in profile:
            if v > ht:
                nodes.append(
                    {
                        "type": VolumeZoneType.HIGH_VOLUME_NODE.value,
                        "price": p,
                        "volume": v,
                        "strength": v / avg if avg else 0,
                    }
                )
            elif 0 < v < lt:
                nodes.append(
                    {
                        "type": VolumeZoneType.LOW_VOLUME_NODE.value,
                        "price": p,
                        "volume": v,
                        "strength": v / avg if avg else 0,
                    }
                )
        return nodes

    def _shape(self, profile: list[tuple[float, float]], poc: float) -> str:
        if not profile:
            return "normal"
        prices = [p for p, _ in profile]
        pr = max(prices) - min(prices)
        if pr == 0:
            return "normal"
        pos = (poc - min(prices)) / pr
        return "p" if pos > 0.7 else "b" if pos < 0.3 else "d"

    def validate_entry_at_level(self, price: float, pr: VolumeProfileResult, direction: str) -> dict[str, Any]:
        v: dict[str, Any] = {"valid": False, "score": 0, "reasons": [], "warnings": []}
        if pr.poc_price and abs(price - pr.poc_price) / pr.poc_price < 0.001:
            v["reasons"].append("Entry at POC")
            v["score"] += 30
        if pr.val_price <= price <= pr.vah_price:
            v["reasons"].append("Within Value Area")
            v["score"] += 20
        if direction == "buy" and pr.val_price and abs(price - pr.val_price) / pr.val_price < 0.002:
            v["reasons"].append("Buy at VAL")
            v["score"] += 25
        if direction == "sell" and pr.vah_price and abs(price - pr.vah_price) / pr.vah_price < 0.002:
            v["reasons"].append("Sell at VAH")
            v["score"] += 25
        for n in pr.volume_nodes:
            np = n["price"]
            nd = abs(price - np) / np if np else 0
            if nd < 0.002:
                if n["type"] == VolumeZoneType.HIGH_VOLUME_NODE.value:
                    v["reasons"].append("At HVN")
                    v["score"] += 15
                elif n["type"] == VolumeZoneType.LOW_VOLUME_NODE.value:
                    v["warnings"].append("At LVN")
        v["valid"] = v["score"] >= 50
        return v
