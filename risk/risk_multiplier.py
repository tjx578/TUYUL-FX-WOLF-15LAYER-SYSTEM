"""
Risk Multiplier Engine - Adaptive Risk Scaling

Adjusts risk exposure based on multiple factors:
- Drawdown level
- VIX volatility
- Trading session
- Time of week (Friday afternoon)

Provides dynamic risk scaling to protect capital in
adverse conditions.
"""

from typing import Optional

from loguru import logger

from config_loader import load_risk
from utils.timezone_utils import now_utc, is_trading_session


class RiskMultiplier:
    """
    Adaptive risk multiplier based on market conditions.

    Combines multiple factors to calculate overall risk multiplier:
    - Drawdown state (reduce risk as drawdown increases)
    - VIX level (reduce risk in high volatility)
    - Trading session (reduce risk in low liquidity)
    - Friday afternoon (reduce risk before weekend)

    Final multiplier is the product of all factors.

    Attributes
    ----------
    vix_enabled : bool
        Whether to apply VIX-based scaling
    session_enabled : bool
        Whether to apply session-based scaling
    time_enabled : bool
        Whether to apply time-based scaling
    """

    def __init__(self):
        """Initialize RiskMultiplier with config."""
        self._config = load_risk()
        self._rm_config = self._config["risk_multiplier"]

        # Feature flags
        self.vix_enabled = self._rm_config["vix"]["enabled"]
        self.session_enabled = self._rm_config["session"]["enabled"]
        self.time_enabled = self._rm_config["time"]["enabled"]

        logger.info(
            "RiskMultiplier initialized",
            vix_enabled=self.vix_enabled,
            session_enabled=self.session_enabled,
            time_enabled=self.time_enabled,
        )

    def _calculate_drawdown_multiplier(
        self,
        drawdown_level: float
    ) -> float:
        """
        Calculate multiplier based on drawdown level.

        Parameters
        ----------
        drawdown_level : float
            Fraction of max drawdown used (0.0-1.0, e.g., 0.3 = 30%)

        Returns
        -------
        float
            Risk multiplier (0.25-1.0)
        """
        # Normalize to [0.0, 1.0] range
        level = max(0.0, min(float(drawdown_level), 1.0))

        dd_config = self._rm_config["drawdown"]

        if level < 0.3:
            return dd_config["level_30_multiplier"]
        if level < 0.6:
            return dd_config["level_60_multiplier"]
        if level < 0.8:
            return dd_config["level_80_multiplier"]

        return dd_config["level_max_multiplier"]

    def _calculate_vix_multiplier(
        self,
        vix_level: Optional[float]
    ) -> float:
        """
        Calculate multiplier based on VIX level.

        Parameters
        ----------
        vix_level : float, optional
            Current VIX value (None = use default 1.0)

        Returns
        -------
        float
            Risk multiplier based on VIX
        """
        if not self.vix_enabled or vix_level is None:
            return 1.0

        vix_config = self._rm_config["vix"]

        # Return appropriate multiplier based on thresholds
        if vix_level >= vix_config["high_threshold"]:
            return vix_config["extreme_multiplier"]
        if vix_level >= vix_config["medium_threshold"]:
            return vix_config["high_multiplier"]
        if vix_level >= vix_config["low_threshold"]:
            return vix_config["medium_multiplier"]

        return vix_config["low_multiplier"]

    def _calculate_session_multiplier(
        self,
        session: Optional[str]
    ) -> float:
        """
        Calculate multiplier based on trading session.

        Parameters
        ----------
        session : str, optional
            Trading session: "ASIA"|"LONDON"|"NEW_YORK"|"OFF_SESSION"
            If None, auto-detect from current time

        Returns
        -------
        float
            Risk multiplier based on session
        """
        if not self.session_enabled:
            return 1.0

        # Auto-detect if not provided
        if session is None:
            session = is_trading_session(now_utc())

        sess_config = self._rm_config["session"]

        multipliers = {
            "ASIA": sess_config["asia_multiplier"],
            "LONDON": sess_config["london_multiplier"],
            "NEW_YORK": sess_config["new_york_multiplier"],
            "OFF_SESSION": sess_config["off_session_multiplier"],
        }

        return multipliers.get(session, 1.0)

    def _calculate_time_multiplier(self) -> float:
        """
        Calculate multiplier based on time of week.

        Returns
        -------
        float
            Risk multiplier (reduced on Friday afternoon)
        """
        if not self.time_enabled:
            return 1.0

        now = now_utc()

        # Friday afternoon (UTC)
        time_config = self._rm_config["time"]
        if (
            now.weekday() == 4  # Friday
            and now.hour >= time_config["friday_cutoff_hour"]
        ):
            return time_config["friday_afternoon_multiplier"]

        return 1.0

    def calculate(
        self,
        drawdown_level: float,
        vix_level: Optional[float] = None,
        session: Optional[str] = None,
    ) -> float:
        """
        Calculate overall risk multiplier.

        Combines all factors (drawdown, VIX, session, time) into
        a single multiplier. Final multiplier is the product of
        all individual multipliers.

        Parameters
        ----------
        drawdown_level : float
            Fraction of max allowed drawdown used (0.0-1.0)
        vix_level : float, optional
            Current VIX level (None to skip VIX adjustment)
        session : str, optional
            Trading session (None to auto-detect)

        Returns
        -------
        float
            Overall risk multiplier (0.25-1.0)

        Examples
        --------
        >>> rm = RiskMultiplier()
        >>> # Low drawdown, low VIX, London session
        >>> rm.calculate(0.1, 15.0, "LONDON")
        1.0
        >>>
        >>> # High drawdown, high VIX, off-session
        >>> rm.calculate(0.9, 35.0, "OFF_SESSION")
        0.03125  # 0.25 * 0.25 * 0.5
        """
        dd_mult = self._calculate_drawdown_multiplier(drawdown_level)
        vix_mult = self._calculate_vix_multiplier(vix_level)
        session_mult = self._calculate_session_multiplier(session)
        time_mult = self._calculate_time_multiplier()

        # Product of all multipliers
        overall = dd_mult * vix_mult * session_mult * time_mult

        logger.debug(
            "Risk multiplier calculated",
            drawdown_mult=dd_mult,
            vix_mult=vix_mult,
            session_mult=session_mult,
            time_mult=time_mult,
            overall=overall,
            drawdown_level=drawdown_level,
            vix_level=vix_level,
            session=session,
        )

        return overall

    def get_breakdown(
        self,
        drawdown_level: float,
        vix_level: Optional[float] = None,
        session: Optional[str] = None,
    ) -> dict:
        """
        Get detailed breakdown of risk multiplier calculation.

        Parameters
        ----------
        drawdown_level : float
            Fraction of max drawdown used
        vix_level : float, optional
            Current VIX level
        session : str, optional
            Trading session

        Returns
        -------
        dict
            Breakdown of each multiplier component and overall result
        """
        dd_mult = self._calculate_drawdown_multiplier(drawdown_level)
        vix_mult = self._calculate_vix_multiplier(vix_level)
        session_mult = self._calculate_session_multiplier(session)
        time_mult = self._calculate_time_multiplier()
        overall = dd_mult * vix_mult * session_mult * time_mult

        return {
            "overall": overall,
            "components": {
                "drawdown": dd_mult,
                "vix": vix_mult,
                "session": session_mult,
                "time": time_mult,
            },
            "inputs": {
                "drawdown_level": drawdown_level,
                "vix_level": vix_level,
                "session": session or is_trading_session(now_utc()),
            },
        }
