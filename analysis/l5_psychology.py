"""Layer-5 trader psychology and sentiment analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

EXTREME_SENTIMENT_THRESHOLD = 0.90
EXTREME_SHORT_THRESHOLD = 0.10
LOSS_STREAK_CAUTION = 2
LOSS_STREAK_TILT = 4
MAX_TRADES_PER_DAY = 6
BAD_DAY_PNL_PCT = -3.0
REVENGE_TRADE_HOURS = 0.5


class SentimentBias(Enum):
    EXTREME_LONG = "extreme_long"
    LONG = "long"
    NEUTRAL = "neutral"
    SHORT = "short"
    EXTREME_SHORT = "extreme_short"


class PsychState(Enum):
    OPTIMAL = "optimal"
    CAUTION = "caution"
    IMPAIRED = "impaired"
    TILT = "tilt"


@dataclass(frozen=True)
class PsychFlag:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class PsychologyInputs:
    retail_long_ratio: float
    recent_consecutive_losses: int = 0
    hours_since_last_trade: float = 9_999.0
    trades_today: int = 0
    daily_pnl_pct: float = 0.0
    in_session_window: bool = True
    fear_greed_index: float = 50.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.retail_long_ratio <= 1.0:
            raise ValueError("retail_long_ratio must be within [0, 1]")
        if not 0.0 <= self.fear_greed_index <= 100.0:
            raise ValueError("fear_greed_index must be within [0, 100]")


@dataclass(frozen=True)
class L5Result:
    symbol: str
    sentiment_bias: SentimentBias
    contrarian_signal: bool
    state: PsychState
    tilt_detected: bool
    overtrade_warning: bool
    psych_score: float
    flags: tuple[PsychFlag, ...]
    metadata: dict[str, Any] | None = None


def _classify_sentiment(retail_long_ratio: float) -> SentimentBias:
    if retail_long_ratio >= EXTREME_SENTIMENT_THRESHOLD:
        return SentimentBias.EXTREME_LONG
    if retail_long_ratio >= 0.60:
        return SentimentBias.LONG
    if retail_long_ratio <= EXTREME_SHORT_THRESHOLD:
        return SentimentBias.EXTREME_SHORT
    if retail_long_ratio <= 0.40:
        return SentimentBias.SHORT
    return SentimentBias.NEUTRAL


def analyze(
    symbol: str,
    inputs: PsychologyInputs,
    metadata: dict[str, Any] | None = None,
) -> L5Result:
    sentiment_bias = _classify_sentiment(inputs.retail_long_ratio)
    contrarian_signal = sentiment_bias in {
        SentimentBias.EXTREME_LONG,
        SentimentBias.EXTREME_SHORT,
    }

    flags: list[PsychFlag] = []
    penalty = 0.0

    if inputs.recent_consecutive_losses >= LOSS_STREAK_TILT:
        flags.append(PsychFlag("LOSS_STREAK_TILT", "CRITICAL", "Loss streak at tilt level"))
        penalty += 40.0
    elif inputs.recent_consecutive_losses >= LOSS_STREAK_CAUTION:
        flags.append(PsychFlag("LOSS_STREAK_CAUTION", "HIGH", "Loss streak caution threshold"))
        penalty += 20.0

    if (
        inputs.recent_consecutive_losses > 0
        and inputs.hours_since_last_trade <= REVENGE_TRADE_HOURS
    ):
        flags.append(PsychFlag("REVENGE_TRADE_RISK", "CRITICAL", "Re-entry too soon after loss"))
        penalty += 30.0

    overtrade_warning = inputs.trades_today >= MAX_TRADES_PER_DAY
    if overtrade_warning:
        flags.append(PsychFlag("OVERTRADE", "HIGH", "Daily trade cap reached"))
        penalty += 20.0

    if inputs.daily_pnl_pct <= BAD_DAY_PNL_PCT:
        flags.append(PsychFlag("BAD_DAY", "CRITICAL", "Daily PnL below safe threshold"))
        penalty += 25.0

    if not inputs.in_session_window:
        flags.append(PsychFlag("OUT_OF_SESSION", "HIGH", "Outside approved session window"))
        penalty += 20.0

    psych_score = max(0.0, min(100.0, round(100.0 - penalty, 2)))

    critical_count = sum(1 for flag in flags if flag.severity == "CRITICAL")
    if psych_score < 30.0 or critical_count >= 2:
        state = PsychState.TILT
    elif psych_score < 55.0:
        state = PsychState.IMPAIRED
    elif psych_score < 85.0:
        state = PsychState.CAUTION
    else:
        state = PsychState.OPTIMAL

    return L5Result(
        symbol=symbol,
        sentiment_bias=sentiment_bias,
        contrarian_signal=contrarian_signal,
        state=state,
        tilt_detected=state == PsychState.TILT,
        overtrade_warning=overtrade_warning,
        psych_score=psych_score,
        flags=tuple(flags),
        metadata=metadata,
    )
