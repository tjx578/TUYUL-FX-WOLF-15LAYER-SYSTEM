"""
Slippage Model — Spread widening and execution slippage estimator.

Accounts for:
1. Normal market slippage (based on pair liquidity profile)
2. Spread widening during high-impact news events
3. Low-liquidity session spread inflation (Asia, off-hours)
4. Adjusts position sizing to account for real execution cost

Authority: risk/ — position sizing adjustment, no market direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loguru import logger


class NewsImpact(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LiquiditySession(StrEnum):
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    ASIA = "ASIA"
    OFF_HOURS = "OFF_HOURS"


@dataclass(frozen=True)
class SlippageEstimate:
    """Estimated slippage and spread cost for a trade."""

    symbol: str
    base_spread_pips: float  # Normal spread for this pair
    estimated_spread_pips: float  # Adjusted spread after all factors
    slippage_pips: float  # Expected execution slippage
    total_cost_pips: float  # spread + slippage
    spread_multiplier: float  # Factor applied to base spread
    news_impact: str
    session: str
    sl_adjusted_pips: float  # SL pips after accounting for slippage
    lot_adjustment_factor: float  # Multiply lot size by this to account for extra cost

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "base_spread_pips": self.base_spread_pips,
            "estimated_spread_pips": round(self.estimated_spread_pips, 2),
            "slippage_pips": round(self.slippage_pips, 2),
            "total_cost_pips": round(self.total_cost_pips, 2),
            "spread_multiplier": round(self.spread_multiplier, 2),
            "news_impact": self.news_impact,
            "session": self.session,
            "sl_adjusted_pips": round(self.sl_adjusted_pips, 2),
            "lot_adjustment_factor": round(self.lot_adjustment_factor, 4),
        }


# ── Pair liquidity profiles ─────────────────────────────────────────
# Base spreads in pips under normal (London session) conditions.

_BASE_SPREADS: dict[str, float] = {
    # Forex majors — tight spreads
    "EURUSD": 1.0,
    "GBPUSD": 1.2,
    "USDJPY": 1.0,
    "USDCHF": 1.3,
    "AUDUSD": 1.2,
    "NZDUSD": 1.4,
    "USDCAD": 1.3,
    # Crosses — wider spreads
    "EURJPY": 1.5,
    "GBPJPY": 2.0,
    "EURGBP": 1.3,
    "EURAUD": 2.0,
    "EURNZD": 2.5,
    "EURCAD": 2.0,
    "EURCHF": 1.5,
    "GBPAUD": 2.5,
    "GBPNZD": 3.0,
    "GBPCAD": 2.5,
    "GBPCHF": 2.0,
    "AUDNZD": 2.0,
    "AUDCAD": 2.0,
    "AUDCHF": 2.0,
    "AUDJPY": 1.8,
    "NZDJPY": 2.0,
    "NZDCAD": 2.5,
    "NZDCHF": 2.5,
    "CADJPY": 2.0,
    "CADCHF": 2.5,
    "CHFJPY": 2.0,
    # Commodities — wider spreads
    "XAUUSD": 3.0,
    "XAGUSD": 3.5,
}

_DEFAULT_BASE_SPREAD = 2.0  # Fallback for unknown pairs

# ── Session multipliers ──────────────────────────────────────────────
_SESSION_SPREAD_MULT: dict[str, float] = {
    LiquiditySession.LONDON: 1.0,  # Tightest spreads
    LiquiditySession.NEW_YORK: 1.0,  # Also tight
    LiquiditySession.ASIA: 1.5,  # Wider due to lower liquidity
    LiquiditySession.OFF_HOURS: 2.0,  # Widest — weekend gaps, rollover
}

# ── News impact multipliers ──────────────────────────────────────────
_NEWS_SPREAD_MULT: dict[str, float] = {
    NewsImpact.NONE: 1.0,
    NewsImpact.LOW: 1.2,
    NewsImpact.MEDIUM: 1.8,
    NewsImpact.HIGH: 3.0,  # NFP, FOMC, etc. — spreads can 3x
}

# ── Base slippage (execution) in pips ────────────────────────────────
_BASE_SLIPPAGE: dict[str, float] = {
    NewsImpact.NONE: 0.3,
    NewsImpact.LOW: 0.5,
    NewsImpact.MEDIUM: 1.0,
    NewsImpact.HIGH: 2.5,  # Fast markets, requotes, partial fills
}


class SlippageModel:
    """Estimates execution cost (spread + slippage) for position sizing.

    Adjusts the effective stop-loss distance and lot size to account
    for real-world execution costs that reduce the actual risk-reward
    ratio of a trade.

    Parameters
    ----------
    custom_spreads : dict, optional
        Override base spreads for specific pairs.
    max_spread_multiplier : float
        Safety cap on total spread multiplier. Default 5.0.
    """

    def __init__(
        self,
        custom_spreads: dict[str, float] | None = None,
        max_spread_multiplier: float = 5.0,
    ) -> None:
        self._spreads = dict(_BASE_SPREADS)
        if custom_spreads:
            self._spreads.update(custom_spreads)
        self._max_mult = max_spread_multiplier

    def estimate(
        self,
        symbol: str,
        sl_pips: float,
        news_impact: NewsImpact = NewsImpact.NONE,
        session: LiquiditySession = LiquiditySession.LONDON,
        lot_size: float | None = None,
    ) -> SlippageEstimate:
        """Estimate total execution cost for a proposed trade.

        Parameters
        ----------
        symbol : str
            Trading pair (e.g., "EURUSD").
        sl_pips : float
            Stop-loss distance in pips (before slippage adjustment).
        news_impact : NewsImpact
            Current news impact level.
        session : LiquiditySession
            Current trading session.
        lot_size : float, optional
            Proposed lot size (for logging only).

        Returns
        -------
        SlippageEstimate
            Includes adjusted SL and lot adjustment factor.
        """
        if sl_pips <= 0:
            return SlippageEstimate(
                symbol=symbol,
                base_spread_pips=0.0,
                estimated_spread_pips=0.0,
                slippage_pips=0.0,
                total_cost_pips=0.0,
                spread_multiplier=1.0,
                news_impact=news_impact.value,
                session=session.value,
                sl_adjusted_pips=0.0,
                lot_adjustment_factor=1.0,
            )

        base_spread = self._spreads.get(symbol, _DEFAULT_BASE_SPREAD)

        # Compute spread multiplier from session + news
        session_mult = _SESSION_SPREAD_MULT.get(session, 1.0)
        news_mult = _NEWS_SPREAD_MULT.get(news_impact, 1.0)
        total_mult = min(session_mult * news_mult, self._max_mult)

        estimated_spread = base_spread * total_mult
        slippage = _BASE_SLIPPAGE.get(news_impact, 0.3)
        total_cost = estimated_spread + slippage

        # Adjusted SL: the real SL needs to account for cost
        # If your SL is 20 pips but cost is 3.5 pips, your effective risk
        # is 23.5 pips worth of movement — position size should be based on this.
        sl_adjusted = sl_pips + total_cost

        # Lot adjustment: reduce lot to keep risk constant despite extra cost
        # original risk = lot * sl_pips * pip_value
        # adjusted risk = lot * sl_adjusted * pip_value
        # To keep risk constant: adjusted_lot = lot * (sl_pips / sl_adjusted)
        lot_adjustment = sl_pips / sl_adjusted if sl_adjusted > 0 else 1.0

        if total_cost > sl_pips * 0.20:
            logger.warning(
                "High execution cost detected",
                symbol=symbol,
                sl_pips=sl_pips,
                total_cost_pips=total_cost,
                cost_ratio=f"{(total_cost / sl_pips) * 100:.1f}%",
                news_impact=news_impact.value,
                session=session.value,
            )

        return SlippageEstimate(
            symbol=symbol,
            base_spread_pips=base_spread,
            estimated_spread_pips=estimated_spread,
            slippage_pips=slippage,
            total_cost_pips=total_cost,
            spread_multiplier=total_mult,
            news_impact=news_impact.value,
            session=session.value,
            sl_adjusted_pips=sl_adjusted,
            lot_adjustment_factor=lot_adjustment,
        )

    def should_skip_trade(
        self,
        symbol: str,
        sl_pips: float,
        news_impact: NewsImpact = NewsImpact.NONE,
        session: LiquiditySession = LiquiditySession.LONDON,
        max_cost_ratio: float = 0.30,
    ) -> tuple[bool, str]:
        """Check if execution cost makes the trade impractical.

        Parameters
        ----------
        max_cost_ratio : float
            Maximum cost-to-SL ratio. If cost > 30% of SL, skip.

        Returns
        -------
        tuple[bool, str]
            (should_skip, reason)
        """
        estimate = self.estimate(symbol, sl_pips, news_impact, session)
        cost_ratio = estimate.total_cost_pips / sl_pips if sl_pips > 0 else 1.0

        if cost_ratio >= max_cost_ratio:
            reason = (
                f"Execution cost {estimate.total_cost_pips:.1f} pips = "
                f"{cost_ratio * 100:.0f}% of SL ({sl_pips} pips). "
                f"News: {news_impact.value}, Session: {session.value}"
            )
            return True, reason

        return False, ""

    def adjust_lot_for_slippage(
        self,
        lot_size: float,
        sl_pips: float,
        symbol: str,
        news_impact: NewsImpact = NewsImpact.NONE,
        session: LiquiditySession = LiquiditySession.LONDON,
        min_lot: float = 0.01,
        lot_step: float = 0.01,
    ) -> tuple[float, SlippageEstimate]:
        """Adjust a lot size to account for execution cost.

        Returns the adjusted lot size and the slippage estimate used.

        Parameters
        ----------
        lot_size : float
            Original calculated lot size.
        sl_pips : float
            Stop-loss distance in pips.
        symbol : str
            Trading pair.
        news_impact : NewsImpact
            Current news impact.
        session : LiquiditySession
            Current session.
        min_lot : float
            Minimum lot size.
        lot_step : float
            Lot size increment.

        Returns
        -------
        tuple[float, SlippageEstimate]
            (adjusted_lot, estimate)
        """
        estimate = self.estimate(symbol, sl_pips, news_impact, session, lot_size)
        adjusted = lot_size * estimate.lot_adjustment_factor

        # Round down to lot step
        adjusted = max(min_lot, round(adjusted // lot_step * lot_step, 2))

        if adjusted < lot_size:
            logger.info(
                "Lot adjusted for slippage",
                symbol=symbol,
                original_lot=lot_size,
                adjusted_lot=adjusted,
                factor=estimate.lot_adjustment_factor,
                cost_pips=estimate.total_cost_pips,
            )

        return adjusted, estimate
