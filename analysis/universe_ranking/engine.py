"""Universe-level ranking and conditional watchlist engine.

This layer answers a different question from L12:

* Universe ranking: which symbols deserve attention, and under what condition?
* L12: is this exact symbol executable now?

The engine is advisory-only. It does not create execution permission and does
not relax any downstream constitutional gate.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any

from engines.relative_strength_engine import MAJOR_CURRENCIES, RelativeStrengthEngine

from .models import PairRank, UniverseRankingResult

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE: tuple[str, ...] = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "EURAUD",
    "EURCAD",
    "EURNZD",
    "GBPJPY",
    "GBPCHF",
    "GBPAUD",
    "GBPCAD",
    "GBPNZD",
    "AUDJPY",
    "AUDNZD",
    "AUDCAD",
    "AUDCHF",
    "NZDJPY",
    "NZDCHF",
    "NZDCAD",
    "CADJPY",
    "CADCHF",
    "CHFJPY",
    "XAUUSD",
    "XAGUSD",
)

_COMMODITY_BASES = frozenset({"XAU", "XAG"})
_BUY_THRESHOLD = 0.15
_SELL_THRESHOLD = -0.15
_MIN_RSE_CONFIDENCE = 0.45
_MIN_CANDLES_FOR_PHASE = 12


class UniverseRankingEngine:
    """Build cross-sectional ranking and conditional watchlist status."""

    def __init__(
        self,
        *,
        pair_universe: Sequence[str] | None = None,
        relative_strength_engine: RelativeStrengthEngine | None = None,
    ) -> None:
        self._pair_universe = tuple(str(s).upper().replace("/", "") for s in (pair_universe or DEFAULT_UNIVERSE))
        self._rse = relative_strength_engine or RelativeStrengthEngine(
            pair_universe=tuple(s for s in self._pair_universe if _decompose_forex_symbol(s) is not None)
        )

    def analyze(
        self,
        context_bus: Any,
        *,
        target_symbol: str,
        warmup: dict[str, Any] | None = None,
        data_quality_reports: Sequence[dict[str, Any]] | None = None,
        top_n: int = 5,
    ) -> UniverseRankingResult:
        """Return a universe ranking snapshot for the current market context."""

        target = _normalize_symbol(target_symbol)
        readiness_reasons = _readiness_reasons(warmup, data_quality_reports)

        anchor = self._select_anchor_symbol(target)
        rs_result = self._rse.analyze(context_bus, symbol=anchor)
        if rs_result.confidence < _MIN_RSE_CONFIDENCE:
            readiness_reasons.append(
                f"relative_strength_coverage_low:{rs_result.pairs_analyzed}/{rs_result.pairs_available}"
            )

        data_ready = not readiness_reasons
        result = UniverseRankingResult(
            target_symbol=target,
            data_ready=data_ready,
            readiness_reasons=readiness_reasons,
            currency_scores=dict(rs_result.currency_scores),
            currency_ranks=list(rs_result.currency_ranks),
            pairs_analyzed=rs_result.pairs_analyzed,
            pairs_available=rs_result.pairs_available,
            top_n=top_n,
            errors=list(rs_result.errors),
        )

        basket_width = _score_width(rs_result.currency_scores)
        ranked: list[PairRank] = []
        for symbol in self._pair_universe:
            pair_rank = self._rank_symbol(
                context_bus,
                symbol=symbol,
                currency_scores=rs_result.currency_scores,
                rs_confidence=rs_result.confidence,
                basket_width=basket_width,
                data_ready=data_ready,
            )
            ranked.append(pair_rank)

        ranked.sort(key=lambda item: item.rank_score, reverse=True)
        for idx, item in enumerate(ranked, start=1):
            item.rank = idx
            if not data_ready:
                item.watchlist_status = "DATA_NOT_READY_FOR_RANKING"
                item.data_ready = False

        result.ranked_pairs = ranked
        result.target_rank = next((item for item in ranked if item.symbol == target), None)

        logger.info(
            "[UniverseRanking] target=%s ready=%s top=%s reasons=%s",
            target,
            data_ready,
            [(p.symbol, p.bias, round(p.rank_score, 3), p.watchlist_status) for p in ranked[:top_n]],
            readiness_reasons,
        )
        return result

    def _select_anchor_symbol(self, target: str) -> str:
        if _decompose_forex_symbol(target) is not None:
            return target
        for symbol in self._pair_universe:
            if _decompose_forex_symbol(symbol) is not None:
                return symbol
        return "EURUSD"

    def _rank_symbol(
        self,
        context_bus: Any,
        *,
        symbol: str,
        currency_scores: dict[str, float],
        rs_confidence: float,
        basket_width: float,
        data_ready: bool,
    ) -> PairRank:
        parts = _decompose_symbol(symbol)
        if parts is None:
            return PairRank(
                symbol=symbol,
                watchlist_status="NO_DATA",
                data_ready=False,
                reasons=["symbol_not_supported"],
            )

        base, quote = parts
        delta = self._relative_delta_for_symbol(context_bus, symbol, base, quote, currency_scores)
        bias = _bias_from_delta(delta)
        candles = _get_candles(context_bus, symbol, "H1", count=50)
        closes = _extract_closes(candles)
        symbol_data_ready = data_ready and len(closes) >= _MIN_CANDLES_FOR_PHASE
        short_roc = _roc(closes, 5)
        medium_roc = _roc(closes, 20)

        phase = _classify_phase(bias, short_roc, medium_roc, candles_available=len(closes))
        theme_score = min(1.0, abs(delta) / 2.0)
        cross_score = min(1.0, abs(delta) / max(basket_width, 1.0))
        entry_quality = _entry_quality_score(theme_score, cross_score, rs_confidence, phase)
        rank_score = _rank_score(theme_score, cross_score, entry_quality, rs_confidence, bias)
        status = _watchlist_status(
            bias=bias,
            rank_score=rank_score,
            theme_score=theme_score,
            entry_quality=entry_quality,
            phase=phase,
            data_ready=symbol_data_ready,
        )

        reasons = [
            f"relative_strength_delta={delta:.4f}",
            f"theme_score={theme_score:.4f}",
            f"phase={phase}",
            f"entry_quality={entry_quality:.4f}",
        ]
        if base in _COMMODITY_BASES:
            reasons.append("commodity_scored_vs_quote_currency")

        return PairRank(
            symbol=symbol,
            bias=bias,
            phase=phase,
            watchlist_status=status,
            rank_score=rank_score,
            theme_score=theme_score,
            relative_strength_delta=delta,
            cross_confirmation_score=cross_score,
            entry_quality_score=entry_quality,
            confidence=rs_confidence,
            base_currency=base,
            quote_currency=quote,
            short_roc=short_roc,
            medium_roc=medium_roc,
            data_ready=symbol_data_ready,
            reasons=reasons,
        )

    def _relative_delta_for_symbol(
        self,
        context_bus: Any,
        symbol: str,
        base: str,
        quote: str,
        currency_scores: dict[str, float],
    ) -> float:
        quote_strength = currency_scores.get(quote, 0.0)
        if base in _COMMODITY_BASES:
            return _commodity_strength(context_bus, symbol) - quote_strength
        return currency_scores.get(base, 0.0) - quote_strength


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").strip()


def _decompose_forex_symbol(symbol: str) -> tuple[str, str] | None:
    normalized = _normalize_symbol(symbol)
    if len(normalized) != 6:
        return None
    base, quote = normalized[:3], normalized[3:]
    if base in MAJOR_CURRENCIES and quote in MAJOR_CURRENCIES:
        return base, quote
    return None


def _decompose_symbol(symbol: str) -> tuple[str, str] | None:
    normalized = _normalize_symbol(symbol)
    forex = _decompose_forex_symbol(normalized)
    if forex is not None:
        return forex
    if len(normalized) == 6 and normalized[:3] in _COMMODITY_BASES and normalized[3:] in MAJOR_CURRENCIES:
        return normalized[:3], normalized[3:]
    return None


def _get_candles(context_bus: Any, symbol: str, timeframe: str, *, count: int) -> list[dict[str, Any]]:
    if context_bus is None:
        return []
    candles: Any = None
    getter = getattr(context_bus, "get_candle_history", None)
    if callable(getter):
        try:
            candles = getter(symbol, timeframe, count=count)
        except TypeError:
            candles = None
    if candles is None:
        getter = getattr(context_bus, "get_candles", None)
        if callable(getter):
            try:
                candles = getter(symbol, timeframe)
            except TypeError:
                candles = None
    if not isinstance(candles, list):
        return []
    return candles[-count:]


def _extract_closes(candles: Sequence[dict[str, Any]]) -> list[float]:
    closes: list[float] = []
    for candle in candles:
        value = candle.get("close")
        if value is None:
            continue
        try:
            close = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(close) and close > 0:
            closes.append(close)
    return closes


def _roc(closes: Sequence[float], lookback: int) -> float:
    if len(closes) <= lookback:
        return 0.0
    current = float(closes[-1])
    past = float(closes[-(lookback + 1)])
    if past <= 0.0 or not math.isfinite(current) or not math.isfinite(past):
        return 0.0
    return (current - past) / abs(past)


def _commodity_strength(context_bus: Any, symbol: str) -> float:
    closes = _extract_closes(_get_candles(context_bus, symbol, "H1", count=50))
    medium = _roc(closes, 20)
    short = _roc(closes, 5)
    # Metals have larger intraday percent swings than most FX crosses. Tanh
    # keeps the pseudo-currency score bounded and comparable to RSE output.
    return math.tanh((medium * 18.0) + (short * 8.0))


def _score_width(currency_scores: dict[str, float]) -> float:
    if not currency_scores:
        return 1.0
    return max(currency_scores.values()) - min(currency_scores.values())


def _bias_from_delta(delta: float) -> str:
    if delta >= _BUY_THRESHOLD:
        return "BUY"
    if delta <= _SELL_THRESHOLD:
        return "SELL"
    return "NEUTRAL"


def _classify_phase(bias: str, short_roc: float, medium_roc: float, *, candles_available: int) -> str:
    if candles_available < _MIN_CANDLES_FOR_PHASE:
        return "DATA_NOT_READY"
    if bias == "NEUTRAL":
        return "SIDEWAYS_OR_MIXED"

    sign = 1.0 if bias == "BUY" else -1.0
    short_aligned = short_roc * sign > 0.0001
    medium_aligned = medium_roc * sign > 0.0001
    short_against = short_roc * sign < -0.0001

    if medium_aligned and short_against:
        return "PULLBACK_IN_THEME"
    if short_aligned and not medium_aligned:
        return "RECLAIM_ATTEMPT"
    if short_aligned and medium_aligned:
        if abs(short_roc) >= 0.006:
            return "IMPULSE_EXTENDED"
        return "RECOVERY_CONTINUATION"
    return "MIXED_OR_UNKNOWN"


def _entry_quality_score(theme_score: float, cross_score: float, rs_confidence: float, phase: str) -> float:
    score = 0.20 + (theme_score * 0.45) + (cross_score * 0.10) + (rs_confidence * 0.25)
    if phase == "PULLBACK_IN_THEME":
        score += 0.18
    elif phase == "RECLAIM_ATTEMPT":
        score += 0.05
    elif phase == "IMPULSE_EXTENDED":
        score -= 0.18
    elif phase in {"MIXED_OR_UNKNOWN", "SIDEWAYS_OR_MIXED", "DATA_NOT_READY"}:
        score -= 0.20
    return max(0.0, min(1.0, score))


def _rank_score(theme_score: float, cross_score: float, entry_quality: float, rs_confidence: float, bias: str) -> float:
    if bias == "NEUTRAL":
        return 0.0
    return max(0.0, min(1.0, theme_score * 0.45 + cross_score * 0.20 + entry_quality * 0.25 + rs_confidence * 0.10))


def _watchlist_status(
    *,
    bias: str,
    rank_score: float,
    theme_score: float,
    entry_quality: float,
    phase: str,
    data_ready: bool,
) -> str:
    if not data_ready:
        return "DATA_NOT_READY_FOR_RANKING"
    if bias == "NEUTRAL" or theme_score < 0.12:
        return "BLOCKED"
    if rank_score >= 0.65 and entry_quality >= 0.65:
        if phase == "PULLBACK_IN_THEME":
            return "VALID_ON_PULLBACK"
        if phase == "RECLAIM_ATTEMPT":
            return "WAIT_RECLAIM"
        if phase == "IMPULSE_EXTENDED":
            return "VALID_ON_PULLBACK"
        return "VALID_BERSYARAT"
    if rank_score >= 0.45:
        return "CADANGAN"
    return "WATCH"


def _readiness_reasons(
    warmup: dict[str, Any] | None,
    data_quality_reports: Sequence[dict[str, Any]] | None,
) -> list[str]:
    reasons: list[str] = []
    if isinstance(warmup, dict) and warmup.get("ready") is False:
        reasons.append("warmup_not_ready")
    for report in data_quality_reports or ():
        if not isinstance(report, dict) or not report.get("degraded"):
            continue
        tf = str(report.get("timeframe", "unknown"))
        report_reasons = ",".join(str(x) for x in report.get("reasons", [])) or "degraded"
        reasons.append(f"data_quality_degraded:{tf}:{report_reasons}")
    return reasons


__all__ = ["DEFAULT_UNIVERSE", "UniverseRankingEngine"]
