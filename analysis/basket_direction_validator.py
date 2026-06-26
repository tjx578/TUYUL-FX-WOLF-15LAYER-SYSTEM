"""Real-price basket direction validation.

The validator reuses currency-strength scores when available and can compute
them through RelativeStrengthEngine. It is advisory/blocker enrichment only;
execution authority stays downstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from engines.relative_strength_engine import MAJOR_CURRENCIES, RelativeStrengthEngine
from schemas.direction import normalize_direction

_COMMODITY_BASES = frozenset({"XAU", "XAG"})


@dataclass(frozen=True)
class BasketDirectionResult:
    symbol: str
    direction: str | None
    base_currency: str | None
    quote_currency: str | None
    base_score: float | None
    quote_score: float | None
    pair_alignment: float | None
    basket_bias: str | None
    directional_status: str
    valid: bool
    data_ready: bool
    blockers: list[str]
    evidence: dict[str, Any]
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_basket_direction(
    symbol: str,
    direction: str | None,
    *,
    currency_scores: Mapping[str, float] | None = None,
    context_bus: Any | None = None,
    relative_strength_engine: RelativeStrengthEngine | None = None,
    min_base_strength: float = 0.15,
    min_quote_strength: float = 0.15,
    min_pair_alignment: float = 0.15,
) -> BasketDirectionResult:
    normalized_symbol = str(symbol or "").upper().replace("/", "")
    normalized_direction = normalize_direction(direction, None)
    parts = decompose_symbol(normalized_symbol)
    if parts is None:
        return _empty_result(normalized_symbol, normalized_direction, "SYMBOL_NOT_SUPPORTED")
    base, quote = parts

    scores: dict[str, float] = {}
    confidence = 0.0
    if currency_scores:
        scores = {str(key).upper(): float(value) for key, value in currency_scores.items()}
        confidence = 1.0
    elif context_bus is not None:
        engine = relative_strength_engine or RelativeStrengthEngine()
        result = engine.analyze(context_bus, symbol=normalized_symbol)
        scores = {str(key).upper(): float(value) for key, value in result.currency_scores.items()}
        confidence = float(result.confidence)

    base_score = _score_for_base(base, scores)
    quote_score = scores.get(quote)
    if normalized_direction not in {"BUY", "SELL"}:
        return BasketDirectionResult(
            symbol=normalized_symbol,
            direction=normalized_direction,
            base_currency=base,
            quote_currency=quote,
            base_score=base_score,
            quote_score=quote_score,
            pair_alignment=None,
            basket_bias=_basket_bias(None, min_pair_alignment),
            directional_status="DIRECTION_MISSING",
            valid=False,
            data_ready=bool(scores),
            blockers=["DIRECTION_MISSING"],
            evidence={"currency_scores": dict(scores)},
            confidence=confidence,
        )
    if base_score is None or quote_score is None:
        return BasketDirectionResult(
            symbol=normalized_symbol,
            direction=normalized_direction,
            base_currency=base,
            quote_currency=quote,
            base_score=base_score,
            quote_score=quote_score,
            pair_alignment=None,
            basket_bias=_basket_bias(None, min_pair_alignment),
            directional_status="DATA_UNAVAILABLE",
            valid=False,
            data_ready=False,
            blockers=["BASKET_DATA_UNAVAILABLE"],
            evidence={"currency_scores": dict(scores)},
            confidence=confidence,
        )

    pair_alignment = base_score - quote_score
    blockers: list[str] = []
    if normalized_direction == "BUY":
        if base not in _COMMODITY_BASES and base_score < min_base_strength:
            blockers.append(f"BASE_{base}_BASKET_WEAK")
        if quote_score > -min_quote_strength:
            blockers.append(
                f"QUOTE_{quote}_BASKET_STRONG"
                if quote_score >= min_quote_strength
                else f"QUOTE_{quote}_BASKET_NOT_WEAK"
            )
        if pair_alignment < min_pair_alignment:
            blockers.append("PAIR_BASKET_NOT_ALIGNED_BUY")
    else:
        if base not in _COMMODITY_BASES and base_score > -min_base_strength:
            blockers.append(
                f"BASE_{base}_BASKET_STRONG"
                if base_score >= min_base_strength
                else f"BASE_{base}_BASKET_NOT_WEAK"
            )
        if quote_score < min_quote_strength:
            blockers.append(f"QUOTE_{quote}_BASKET_WEAK" if quote_score <= -min_quote_strength else f"QUOTE_{quote}_BASKET_NOT_STRONG")
        if pair_alignment > -min_pair_alignment:
            blockers.append("PAIR_BASKET_NOT_ALIGNED_SELL")
    basket_bias = _basket_bias(pair_alignment, min_pair_alignment)

    return BasketDirectionResult(
        symbol=normalized_symbol,
        direction=normalized_direction,
        base_currency=base,
        quote_currency=quote,
        base_score=round(base_score, 4),
        quote_score=round(quote_score, 4),
        pair_alignment=round(pair_alignment, 4),
        basket_bias=basket_bias,
        directional_status=_directional_status(normalized_direction, basket_bias, blockers),
        valid=not blockers,
        data_ready=True,
        blockers=blockers,
        evidence={
            "currency_scores": dict(scores),
            "min_base_strength": min_base_strength,
            "min_quote_strength": min_quote_strength,
            "min_pair_alignment": min_pair_alignment,
        },
        confidence=round(confidence, 4),
    )


def decompose_symbol(symbol: str) -> tuple[str, str] | None:
    normalized = str(symbol or "").upper().replace("/", "")
    if len(normalized) != 6:
        return None
    base, quote = normalized[:3], normalized[3:]
    if base in MAJOR_CURRENCIES and quote in MAJOR_CURRENCIES:
        return base, quote
    if base in _COMMODITY_BASES and quote in MAJOR_CURRENCIES:
        return base, quote
    return None


def _score_for_base(base: str, scores: Mapping[str, float]) -> float | None:
    if base in _COMMODITY_BASES:
        return 0.0
    return scores.get(base)


def _basket_bias(pair_alignment: float | None, min_pair_alignment: float) -> str:
    if pair_alignment is None:
        return "UNKNOWN"
    if abs(float(pair_alignment)) < float(min_pair_alignment):
        return "NEUTRAL_LOW_DIFFERENTIAL"
    return "SUPPORTS_BUY" if pair_alignment > 0 else "SUPPORTS_SELL"


def _directional_status(direction: str | None, basket_bias: str, blockers: list[str]) -> str:
    if direction not in {"BUY", "SELL"}:
        return "DIRECTION_MISSING"
    if basket_bias == "NEUTRAL_LOW_DIFFERENTIAL":
        return "NEUTRAL_LOW_DIFFERENTIAL"
    if (direction == "BUY" and basket_bias == "SUPPORTS_BUY") or (
        direction == "SELL" and basket_bias == "SUPPORTS_SELL"
    ):
        return "SUPPORTS_DIRECTION" if not blockers else "PARTIAL_SUPPORT_BLOCKED"
    if basket_bias in {"SUPPORTS_BUY", "SUPPORTS_SELL"}:
        return "REJECTS_DIRECTION"
    return "UNKNOWN"


def _empty_result(symbol: str, direction: str | None, blocker: str) -> BasketDirectionResult:
    return BasketDirectionResult(
        symbol=symbol,
        direction=direction,
        base_currency=None,
        quote_currency=None,
        base_score=None,
        quote_score=None,
        pair_alignment=None,
        basket_bias=None,
        directional_status=blocker,
        valid=False,
        data_ready=False,
        blockers=[blocker],
        evidence={},
        confidence=0.0,
    )


__all__ = [
    "BasketDirectionResult",
    "decompose_symbol",
    "validate_basket_direction",
]
