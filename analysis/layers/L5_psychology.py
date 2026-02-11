"""
L5 — Market Psychology (Objective)

Tracks trader psychology factors:
- Consecutive losses from journal
- Session fatigue (hours since start)
- Drawdown percentage
"""

from loguru import logger

from context.runtime_state import RuntimeState


class L5PsychologyAnalyzer:
    """
    Analyzes trader psychology and fatigue.

    Monitors:
    - Consecutive losses (from journal)
    - Session duration and fatigue
    - Drawdown levels
    """

    # Psychology thresholds
    MAX_CONSECUTIVE_LOSSES = 3
    FATIGUE_HOURS_MEDIUM = 4
    FATIGUE_HOURS_HIGH = 6
    MAX_DRAWDOWN_PERCENT = 5.0  # 5% max drawdown

    def __init__(self) -> None:
        self._consecutive_losses = 0
        self._current_drawdown = 0.0

    def analyze(
        self,
        symbol: str,
        volatility_profile: dict | None = None,
    ) -> dict:
        """
        Analyze trader psychology and fatigue.

        Args:
            symbol: Trading pair symbol
            volatility_profile: Optional volatility profile from L2/L3

        Returns:
            Dictionary with psychology analysis
        """
        # Check volatility if provided
        stable = True
        if volatility_profile and volatility_profile.get("profile") == "HIGH":
            stable = False

        # Get session duration from RuntimeState
        session_hours = RuntimeState.get_session_hours()
        fatigue_level = self._calculate_fatigue(session_hours)

        # Check consecutive losses
        losses_ok = self._consecutive_losses < self.MAX_CONSECUTIVE_LOSSES

        # Check drawdown
        drawdown_ok = self._current_drawdown < self.MAX_DRAWDOWN_PERCENT

        # Overall psychology OK if all factors are acceptable
        psychology_ok = stable and losses_ok and drawdown_ok and fatigue_level != "HIGH"

        # Build recommendation
        recommendation = "Psychology OK"
        if not psychology_ok:
            reasons = []
            if not stable:
                reasons.append("high volatility")
            if not losses_ok:
                reasons.append(f"{self._consecutive_losses} consecutive losses")
            if not drawdown_ok:
                reasons.append(f"{self._current_drawdown:.1f}% drawdown")
            if fatigue_level == "HIGH":
                reasons.append("high fatigue")
            recommendation = f"Psychology NOT OK: {', '.join(reasons)}"

        return {
            "stable": stable,
            "psychology_ok": psychology_ok,
            "fatigue_level": fatigue_level,
            "session_hours": round(session_hours, 1),
            "consecutive_losses": self._consecutive_losses,
            "drawdown_percent": round(self._current_drawdown, 2),
            "losses_ok": losses_ok,
            "drawdown_ok": drawdown_ok,
            "recommendation": recommendation,
            "valid": True,
        }

    def _calculate_fatigue(self, hours: float) -> str:
        """
        Calculate fatigue level based on session duration.

        Args:
            hours: Hours since session start

        Returns:
            "LOW" | "MEDIUM" | "HIGH"
        """
        if hours >= self.FATIGUE_HOURS_HIGH:
            return "HIGH"
        if hours >= self.FATIGUE_HOURS_MEDIUM:
            return "MEDIUM"
        return "LOW"

    def record_loss(self) -> None:
        """Record a consecutive loss."""
        self._consecutive_losses += 1
        logger.warning(
            f"Consecutive losses: {self._consecutive_losses}/{self.MAX_CONSECUTIVE_LOSSES}"
        )

    def record_win(self) -> None:
        """Record a win (resets consecutive losses)."""
        if self._consecutive_losses > 0:
            logger.info(
                f"Win recorded, resetting consecutive losses from {self._consecutive_losses} to 0"
            )
        self._consecutive_losses = 0

    def update_drawdown(self, drawdown_percent: float) -> None:
        """
        Update current drawdown percentage.

        Args:
            drawdown_percent: Current drawdown as percentage (0-100)
        """
        self._current_drawdown = drawdown_percent

        if drawdown_percent >= self.MAX_DRAWDOWN_PERCENT:
            logger.warning(
                f"Drawdown alert: {drawdown_percent:.2f}% (limit: {self.MAX_DRAWDOWN_PERCENT}%)"
            )

    def reset_session(self) -> None:
        """Reset session tracking (e.g., at start of new trading day)."""
        RuntimeState.session_start = None  # Will be reinitialized on next call
        self._consecutive_losses = 0
        self._current_drawdown = 0.0
        logger.info("Psychology session reset")
