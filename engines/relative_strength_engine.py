"""
TUYUL FX — Relative Strength Engine (Enrichment Module)

Computes individual currency strength scores by aggregating rate-of-change
(ROC) across all forex pairs that contain each currency.  Produces a ranked
currency strength map and a pair-specific relative-strength delta.

This is an **enrichment/advisory** module.  It does NOT make execution
decisions — that authority belongs exclusively to Layer-12.

Algorithm
---------
1. For every tracked pair, compute weighted ROC across multiple lookback
   windows (short / medium / long) from close prices.
2. Attribute positive ROC to base currency strength and negative ROC to
   quote currency strength (and vice versa).
3. Normalize per-currency aggregates to a -1.0 … +1.0 scale.
4. Rank all 8 major currencies strongest → weakest.
5. For the target symbol, compute:
   ``relative_strength_delta = base_strength - quote_strength``
6. Map the delta to a qualitative alignment label and confidence score.

Data Source
-----------
``LiveContextBus.get_candle_history(symbol, timeframe, count)``
The engine reads D1 candles for all available pairs.  If a pair has
insufficient data, it is gracefully excluded — partial-data analysis is
still valid, but confidence is reduced proportionally.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The 8 major currencies tracked by the system
MAJOR_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")

# All forex pair symbols from config/pairs.yaml (excluding commodities)
# Each pair is decomposed into (base_ccy, quote_ccy)
_PAIR_UNIVERSE: tuple[str, ...] = (
    # Majors
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    # EUR crosses
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "EURAUD",
    "EURCAD",
    "EURNZD",
    # GBP crosses
    "GBPJPY",
    "GBPCHF",
    "GBPAUD",
    "GBPCAD",
    "GBPNZD",
    # AUD crosses
    "AUDJPY",
    "AUDNZD",
    "AUDCAD",
    "AUDCHF",
    # NZD crosses
    "NZDJPY",
    "NZDCHF",
    "NZDCAD",
    # CAD / CHF
    "CADJPY",
    "CADCHF",
    "CHFJPY",
)

# ROC lookback windows (in D1 bars) and their weights
# Short-term momentum is de-emphasized vs medium/long for structural bias
_ROC_WINDOWS: tuple[tuple[int, float], ...] = (
    (5, 0.20),  # ~1 week   — short-term momentum
    (10, 0.30),  # ~2 weeks  — medium-term swing
    (20, 0.50),  # ~1 month  — structural trend
)

# Minimum required candles to compute any ROC
_MIN_CANDLES: int = 6

# D1 candle depth to request from context bus
_CANDLE_DEPTH: int = 25

# Timeframe for strength analysis (D1 captures structural moves)
_ANALYSIS_TF: str = "D1"

# Alignment thresholds for relative_strength_delta
_STRONG_THRESHOLD: float = 0.35
_MODERATE_THRESHOLD: float = 0.15


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class CurrencyStrengthResult:
    """Output of the Relative Strength Engine."""

    # Per-currency normalized strength scores (-1.0 … +1.0)
    currency_scores: dict[str, float] = field(default_factory=dict)

    # Ordered list: strongest → weakest
    currency_ranks: list[str] = field(default_factory=list)

    # Pair-specific decomposition
    base_currency: str = ""
    quote_currency: str = ""
    base_strength: float = 0.0
    quote_strength: float = 0.0
    relative_strength_delta: float = 0.0

    # Qualitative alignment: STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL
    alignment: str = "NEUTRAL"

    # Confidence based on data completeness (0.0 … 1.0)
    confidence: float = 0.0

    # Diagnostic
    pairs_analyzed: int = 0
    pairs_available: int = len(_PAIR_UNIVERSE)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency_scores": self.currency_scores,
            "currency_ranks": self.currency_ranks,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "base_strength": round(self.base_strength, 4),
            "quote_strength": round(self.quote_strength, 4),
            "relative_strength_delta": round(self.relative_strength_delta, 4),
            "alignment": self.alignment,
            "confidence": round(self.confidence, 4),
            "pairs_analyzed": self.pairs_analyzed,
            "pairs_available": self.pairs_available,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Helper: decompose pair → (base, quote)
# ---------------------------------------------------------------------------
def _decompose_pair(symbol: str) -> tuple[str, str] | None:
    """Return (base_ccy, quote_ccy) for a 6-char forex pair, or None."""
    s = symbol.upper().replace("/", "")
    if len(s) != 6:
        return None
    base = s[:3]
    quote = s[3:]
    if base in MAJOR_CURRENCIES and quote in MAJOR_CURRENCIES:
        return (base, quote)
    return None


# ---------------------------------------------------------------------------
# Helper: compute weighted multi-window ROC from close prices
# ---------------------------------------------------------------------------
def _weighted_roc(closes: list[float]) -> float:
    """Compute a weighted average ROC across multiple lookback windows.

    Returns a value typically in the range [-1, +1] after clamp, representing
    the directional strength of the pair.
    """
    if len(closes) < _MIN_CANDLES:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for lookback, weight in _ROC_WINDOWS:
        if len(closes) <= lookback:
            continue
        current = closes[-1]
        past = closes[-(lookback + 1)]
        if past == 0.0 or not math.isfinite(past) or not math.isfinite(current):
            continue
        roc = (current - past) / abs(past)
        weighted_sum += roc * weight
        total_weight += weight

    if total_weight == 0.0:
        return 0.0

    raw = weighted_sum / total_weight
    # Clamp to [-1, +1] — extreme moves beyond ±100% are capped
    return max(-1.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class RelativeStrengthEngine:
    """Computes cross-pair currency strength rankings.

    Usage::

        rse = RelativeStrengthEngine()
        result = rse.analyze(
            context_bus=bus,
            symbol="NZDCAD",
        )
        # result.currency_ranks → ["NZD", "AUD", "EUR", ...]
        # result.alignment → "STRONG_BUY"

    The engine is **analysis-only** — it produces enrichment metrics.
    It NEVER makes execution decisions.
    """

    def __init__(self, pair_universe: tuple[str, ...] | None = None) -> None:
        self._pair_universe = pair_universe or _PAIR_UNIVERSE

    def analyze(
        self,
        context_bus: Any,
        symbol: str,
        *,
        timeframe: str = _ANALYSIS_TF,
        candle_depth: int = _CANDLE_DEPTH,
    ) -> CurrencyStrengthResult:
        """Compute currency strength map and pair-specific delta.

        Parameters
        ----------
        context_bus:
            LiveContextBus instance providing ``get_candle_history()``.
        symbol:
            The target pair being analyzed (e.g. "NZDCAD").
        timeframe:
            Candle timeframe for ROC analysis (default D1).
        candle_depth:
            Number of candles to request per pair.

        Returns
        -------
        CurrencyStrengthResult
        """
        result = CurrencyStrengthResult()

        # Decompose target pair
        pair_parts = _decompose_pair(symbol)
        if pair_parts is None:
            result.errors.append(f"Cannot decompose symbol: {symbol}")
            return result
        result.base_currency, result.quote_currency = pair_parts

        # ── Step 1: Collect ROC per pair ──
        pair_rocs = self._collect_pair_rocs(context_bus, timeframe, candle_depth, result)

        if not pair_rocs:
            result.errors.append("No pair data available for strength analysis")
            return result

        # ── Step 2: Aggregate strength per currency ──
        raw_scores = self._aggregate_currency_scores(pair_rocs)

        # ── Step 3: Normalize to [-1, +1] ──
        result.currency_scores = self._normalize_scores(raw_scores)

        # ── Step 4: Rank currencies ──
        result.currency_ranks = sorted(
            result.currency_scores,
            key=lambda c: result.currency_scores[c],
            reverse=True,
        )

        # ── Step 5: Pair-specific delta ──
        result.base_strength = result.currency_scores.get(result.base_currency, 0.0)
        result.quote_strength = result.currency_scores.get(result.quote_currency, 0.0)
        result.relative_strength_delta = result.base_strength - result.quote_strength

        # ── Step 6: Alignment label ──
        result.alignment = self._classify_alignment(result.relative_strength_delta)

        # ── Step 7: Confidence from data completeness ──
        max_forex_pairs = sum(1 for p in self._pair_universe if _decompose_pair(p) is not None)
        data_ratio = result.pairs_analyzed / max(max_forex_pairs, 1)
        result.confidence = min(1.0, data_ratio * 1.1)  # slight boost, cap at 1.0

        logger.info(
            "[RSE] %s: delta=%.4f alignment=%s confidence=%.2f base(%s)=%.4f quote(%s)=%.4f pairs=%d/%d",
            symbol,
            result.relative_strength_delta,
            result.alignment,
            result.confidence,
            result.base_currency,
            result.base_strength,
            result.quote_currency,
            result.quote_strength,
            result.pairs_analyzed,
            result.pairs_available,
        )
        return result

    # ------------------------------------------------------------------
    # Internal: collect ROC from all pairs via context bus
    # ------------------------------------------------------------------
    def _collect_pair_rocs(
        self,
        context_bus: Any,
        timeframe: str,
        candle_depth: int,
        result: CurrencyStrengthResult,
    ) -> dict[str, float]:
        """Fetch candles for each pair and compute weighted ROC.

        Returns dict[pair_symbol, roc_value].
        """
        pair_rocs: dict[str, float] = {}

        if context_bus is None:
            result.errors.append("No context_bus available")
            return pair_rocs

        for pair in self._pair_universe:
            if _decompose_pair(pair) is None:
                continue
            try:
                candles = context_bus.get_candle_history(pair, timeframe, count=candle_depth)
                if not candles or len(candles) < _MIN_CANDLES:
                    continue

                closes = [float(c["close"]) for c in candles if "close" in c and c["close"] is not None]
                if len(closes) < _MIN_CANDLES:
                    continue

                roc = _weighted_roc(closes)
                pair_rocs[pair] = roc
                result.pairs_analyzed += 1

            except Exception as exc:  # noqa: BLE001
                # Engine isolation: never crash the pipeline
                result.errors.append(f"{pair}: {exc}")
                logger.debug("RSE: failed to fetch %s: %s", pair, exc)

        return pair_rocs

    # ------------------------------------------------------------------
    # Internal: aggregate ROC into per-currency scores
    # ------------------------------------------------------------------
    @staticmethod
    def _aggregate_currency_scores(pair_rocs: dict[str, float]) -> dict[str, list[float]]:
        """Distribute each pair's ROC to its base and quote currencies.

        If EURUSD ROC = +0.02:
          → EUR gets +0.02  (base gained)
          → USD gets -0.02  (quote lost)
        """
        scores: dict[str, list[float]] = {ccy: [] for ccy in MAJOR_CURRENCIES}

        for pair, roc in pair_rocs.items():
            parts = _decompose_pair(pair)
            if parts is None:
                continue
            base, quote = parts
            if base in scores:
                scores[base].append(+roc)
            if quote in scores:
                scores[quote].append(-roc)

        return scores

    # ------------------------------------------------------------------
    # Internal: normalize aggregated scores
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_scores(raw_scores: dict[str, list[float]]) -> dict[str, float]:
        """Average each currency's contributions, then rescale so the
        strongest = +1.0 and weakest = -1.0 (if range > 0)."""
        averages: dict[str, float] = {}
        for ccy, values in raw_scores.items():
            if values:
                averages[ccy] = sum(values) / len(values)
            else:
                averages[ccy] = 0.0

        max_abs = max((abs(v) for v in averages.values()), default=0.0)
        if max_abs < 1e-10:
            return averages

        return {ccy: v / max_abs for ccy, v in averages.items()}

    # ------------------------------------------------------------------
    # Internal: classify alignment from delta
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_alignment(delta: float) -> str:
        """Map relative_strength_delta to a qualitative label."""
        if delta >= _STRONG_THRESHOLD:
            return "STRONG_BUY"
        if delta >= _MODERATE_THRESHOLD:
            return "BUY"
        if delta <= -_STRONG_THRESHOLD:
            return "STRONG_SELL"
        if delta <= -_MODERATE_THRESHOLD:
            return "SELL"
        return "NEUTRAL"
