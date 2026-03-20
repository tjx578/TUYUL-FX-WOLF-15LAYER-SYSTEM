"""Multi-Indicator Divergence Detector -- RSI/MACD/CCI/MFI."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ._types import (
    DivergenceSignal, DivergenceStrength, DivergenceType,
    MultiDivergenceResult, DEFAULT_LOOKBACK_BARS, DEFAULT_MIN_BARS_APART,
    DEFAULT_MAX_BARS_APART, DEFAULT_MIN_CONFLUENCE,
)


class MultiIndicatorDivergenceDetector:
    """Detects divergences across RSI, MACD, CCI, MFI indicators."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {
            "rsi_period": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "cci_period": 20, "mfi_period": 14, "lookback_bars": DEFAULT_LOOKBACK_BARS,
            "min_bars_apart": DEFAULT_MIN_BARS_APART, "max_bars_apart": DEFAULT_MAX_BARS_APART,
            "price_tolerance": 0.001, "min_confluence": DEFAULT_MIN_CONFLUENCE,
        }

    def analyze(self, ohlcv_data: List[Dict[str, Any]], pair: str, timeframe: str,
                indicators: Optional[Dict[str, List[float]]] = None) -> MultiDivergenceResult:
        ts = datetime.now(timezone.utc)
        if indicators is None:
            indicators = self._calculate_indicators(ohlcv_data)

        highs = [c.get("high", 0) for c in ohlcv_data]
        lows = [c.get("low", 0) for c in ohlcv_data]
        closes = [c.get("close", 0) for c in ohlcv_data]

        rsi_div = self._detect_divergence(highs, lows, closes, indicators.get("rsi", []), "RSI")
        macd_div = self._detect_divergence(highs, lows, closes, indicators.get("macd_histogram", []), "MACD")
        cci_div = self._detect_divergence(highs, lows, closes, indicators.get("cci", []), "CCI")
        mfi_div = self._detect_divergence(highs, lows, closes, indicators.get("mfi", []), "MFI")

        valid = [d for d in [rsi_div, macd_div, cci_div, mfi_div] if d is not None]
        overall_signal, overall_strength = self._determine_overall_signal(valid)

        return MultiDivergenceResult(
            timestamp=ts, pair=pair, timeframe=timeframe,
            rsi_divergence=rsi_div, macd_divergence=macd_div,
            cci_divergence=cci_div, mfi_divergence=mfi_div,
            confluence_count=len(valid), overall_signal=overall_signal,
            overall_strength=overall_strength,
            confidence=self._calculate_confidence(valid, len(valid)))

    # ── Indicator calculations ────────────────────────────────────────────────

    def _calculate_indicators(self, ohlcv: List[Dict[str, Any]]) -> Dict[str, List[float]]:
        if len(ohlcv) < 30:
            return {"rsi": [], "macd_histogram": [], "cci": [], "mfi": []}
        closes = [c.get("close", 0.0) for c in ohlcv]
        highs = [c.get("high", 0.0) for c in ohlcv]
        lows = [c.get("low", 0.0) for c in ohlcv]
        volumes = [c.get("volume", 1.0) for c in ohlcv]
        return {
            "rsi": self._calc_rsi(closes, self.config.get("rsi_period", 14)),
            "macd_histogram": self._calc_macd_histogram(closes, self.config.get("macd_fast", 12),
                self.config.get("macd_slow", 26), self.config.get("macd_signal", 9)),
            "cci": self._calc_cci(highs, lows, closes, self.config.get("cci_period", 20)),
            "mfi": self._calc_mfi(highs, lows, closes, volumes, self.config.get("mfi_period", 14)),
        }

    @staticmethod
    def _calc_rsi(closes: List[float], period: int) -> List[float]:
        if len(closes) < period + 1: return []
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [max(0, d) for d in deltas]; losses = [max(0, -d) for d in deltas]
        ag = sum(gains[:period]) / period; al = sum(losses[:period]) / period
        rsi: List[float] = []
        for i in range(period, len(deltas)):
            ag = (ag * (period - 1) + gains[i]) / period
            al = (al * (period - 1) + losses[i]) / period
            rsi.append(100.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al)))
        return [50.0] * (len(closes) - len(rsi)) + rsi

    @staticmethod
    def _calc_ema(values: List[float], period: int) -> List[float]:
        if len(values) < period: return values[:]
        k = 2.0 / (period + 1)
        ema = [sum(values[:period]) / period]
        for v in values[period:]: ema.append(v * k + ema[-1] * (1 - k))
        return (values[:period - 1] if period > 1 else []) + ema

    def _calc_macd_histogram(self, closes: List[float], fast: int, slow: int, signal: int) -> List[float]:
        if len(closes) < slow + signal: return []
        ef = self._calc_ema(closes, fast); es = self._calc_ema(closes, slow)
        ml = [f - s for f, s in zip(ef, es)]; sl = self._calc_ema(ml, signal)
        hist = [m - s for m, s in zip(ml, sl)]
        return [0.0] * (len(closes) - len(hist)) + hist

    @staticmethod
    def _calc_cci(highs: List[float], lows: List[float], closes: List[float], period: int) -> List[float]:
        if len(closes) < period: return []
        typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
        cci: List[float] = []
        for i in range(period - 1, len(typical)):
            w = typical[i - period + 1: i + 1]; sma = sum(w) / period
            md = sum(abs(v - sma) for v in w) / period
            cci.append(0.0 if md == 0 else (typical[i] - sma) / (0.015 * md))
        return [0.0] * (len(closes) - len(cci)) + cci

    @staticmethod
    def _calc_mfi(highs: List[float], lows: List[float], closes: List[float],
                  volumes: List[float], period: int) -> List[float]:
        if len(closes) < period + 1: return []
        typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
        mfi: List[float] = []
        for i in range(period, len(typical)):
            pf = nf = 0.0
            for j in range(i - period + 1, i + 1):
                rmf = typical[j] * volumes[j]
                if typical[j] > typical[j-1]: pf += rmf
                else: nf += rmf
            mfi.append(100.0 if nf == 0 else 100.0 - (100.0 / (1.0 + pf / nf)))
        return [50.0] * (len(closes) - len(mfi)) + mfi

    # ── Divergence detection ──────────────────────────────────────────────────

    def _detect_divergence(self, highs: List[float], lows: List[float],
                           closes: List[float], ind_vals: List[float],
                           ind_name: str) -> Optional[DivergenceSignal]:
        if len(ind_vals) < self.config["lookback_bars"]: return None
        lb = self.config["lookback_bars"]
        mn, mx = self.config["min_bars_apart"], self.config["max_bars_apart"]
        ph = self._find_swing_points(highs, lb, "high")
        pl = self._find_swing_points(lows, lb, "low")

        bull = self._check_regular_bullish(pl, lows, ind_vals, mn, mx)
        if bull:
            return DivergenceSignal(indicator=ind_name, divergence_type=DivergenceType.REGULAR_BULLISH,
                strength=self._calc_strength(bull), price_start=bull["price_start"],
                price_end=bull["price_end"], indicator_start=bull["ind_start"],
                indicator_end=bull["ind_end"], bars_apart=bull["bars"], confidence=bull.get("confidence", 0.7))
        bear = self._check_regular_bearish(ph, highs, ind_vals, mn, mx)
        if bear:
            return DivergenceSignal(indicator=ind_name, divergence_type=DivergenceType.REGULAR_BEARISH,
                strength=self._calc_strength(bear), price_start=bear["price_start"],
                price_end=bear["price_end"], indicator_start=bear["ind_start"],
                indicator_end=bear["ind_end"], bars_apart=bear["bars"], confidence=bear.get("confidence", 0.7))
        return None

    def _find_swing_points(self, values: List[float], lookback: int, pt: str) -> List[Tuple[int, float]]:
        swings = []; w = 5
        for i in range(w, len(values) - w):
            cur = values[i]; ok = True
            for j in range(i - w, i + w + 1):
                if j != i:
                    if (pt == "high" and values[j] > cur) or (pt == "low" and values[j] < cur):
                        ok = False; break
            if ok: swings.append((i, cur))
        return swings

    def _check_regular_bullish(self, price_lows: List[Tuple[int, float]],
                               lows: List[float], ind: List[float],
                               mn: int, mx: int) -> Optional[Dict[str, Any]]:
        if len(price_lows) < 2: return None
        for i in range(len(price_lows) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                i1, p1 = price_lows[j]; i2, p2 = price_lows[i]
                ba = i2 - i1
                if not (mn <= ba <= mx) or p2 >= p1: continue
                if i1 < len(ind) and i2 < len(ind) and ind[i2] > ind[i1]:
                    return {"price_start": p1, "price_end": p2, "ind_start": ind[i1],
                            "ind_end": ind[i2], "bars": ba, "confidence": 0.75}
        return None

    def _check_regular_bearish(self, price_highs: List[Tuple[int, float]],
                               highs: List[float], ind: List[float],
                               mn: int, mx: int) -> Optional[Dict[str, Any]]:
        if len(price_highs) < 2: return None
        for i in range(len(price_highs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                i1, p1 = price_highs[j]; i2, p2 = price_highs[i]
                ba = i2 - i1
                if not (mn <= ba <= mx) or p2 <= p1: continue
                if i1 < len(ind) and i2 < len(ind) and ind[i2] < ind[i1]:
                    return {"price_start": p1, "price_end": p2, "ind_start": ind[i1],
                            "ind_end": ind[i2], "bars": ba, "confidence": 0.75}
        return None

    @staticmethod
    def _calc_strength(d: Dict[str, Any]) -> DivergenceStrength:
        b = d["bars"]
        return DivergenceStrength.STRONG if b > 20 else DivergenceStrength.MODERATE if b > 10 else DivergenceStrength.WEAK

    @staticmethod
    def _determine_overall_signal(divs: List[DivergenceSignal]) -> Tuple[DivergenceType, DivergenceStrength]:
        if not divs: return DivergenceType.NONE, DivergenceStrength.WEAK
        bull = sum(1 for d in divs if d.divergence_type in [DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH])
        bear = sum(1 for d in divs if d.divergence_type in [DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH])
        sig = DivergenceType.REGULAR_BULLISH if bull > bear else DivergenceType.REGULAR_BEARISH if bear > bull else DivergenceType.NONE
        st = DivergenceStrength.STRONG if len(divs) >= 3 else DivergenceStrength.MODERATE if len(divs) >= 2 else DivergenceStrength.WEAK
        return sig, st

    @staticmethod
    def _calculate_confidence(divs: List[DivergenceSignal], count: int) -> float:
        if count == 0: return 0.0
        c = 0.5 + count * 0.15 + sum(0.05 for d in divs if d.strength == DivergenceStrength.STRONG)
        return min(1.0, c)
