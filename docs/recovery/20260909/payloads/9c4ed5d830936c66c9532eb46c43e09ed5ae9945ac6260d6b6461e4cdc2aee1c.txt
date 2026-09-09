"""
L5 — Market Psychology with EAF (Emotional-Accuracy Factor)

Tracks trader psychology factors:
- Consecutive losses from journal
- Session fatigue (hours since start)
- Drawdown percentage
- EAF score (emotional bias, stability, focus, discipline)
"""

from loguru import logger

from config.constants import get_threshold
from context.runtime_state import RuntimeState

# EAF thresholds from constitution
EAF_MIN_FOR_TRADE: float = get_threshold("eaf.min_for_trade", 0.70)
EAF_WEIGHTS: dict = get_threshold("eaf.weights", {
    "emotional_bias": 0.30,
    "stability_index": 0.25,
    "focus_level": 0.25,
    "discipline_score": 0.20
})
FATIGUE_SESSION_THRESHOLD_MINUTES: int = get_threshold("eaf.fatigue.session_threshold_minutes", 180)
FATIGUE_MEDIUM_HOURS: float = get_threshold("eaf.fatigue.medium_hours", 3.0)
FATIGUE_HIGH_HOURS: float = get_threshold("eaf.fatigue.high_hours", 5.0)

# Psychology thresholds
MAX_CONSECUTIVE_LOSSES: int = get_threshold("wolf_discipline.emotion.max_consecutive_losses", 2)
MAX_DRAWDOWN_PERCENT: float = get_threshold("risk.max_dd_daily", 5.0)


class L5PsychologyAnalyzer:
    """
    Analyzes trader psychology and fatigue with EAF integration.

    Monitors:
    - Consecutive losses (from journal)
    - Session duration and fatigue
    - Drawdown levels
    - EAF score (emotional bias, stability, focus, discipline)
    """

    def __init__(self) -> None:
        self._consecutive_losses = 0
        self._current_drawdown = 0.0
        self._win_streak = 0
        self._loss_streak = 0
        self._total_trades = 0

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
            Dictionary with psychology analysis including EAF
        """
        # Check volatility if provided
        stable = True
        if volatility_profile and volatility_profile.get("profile") == "HIGH":
            stable = False

        # Get session duration from RuntimeState
        session_hours = RuntimeState.get_session_hours()
        fatigue_level = self._calculate_fatigue(session_hours)

        # Check consecutive losses
        losses_ok = self._consecutive_losses < MAX_CONSECUTIVE_LOSSES

        # Check drawdown
        drawdown_ok = self._current_drawdown < MAX_DRAWDOWN_PERCENT

        # Calculate EAF score (convex weighted formula)
        eaf_result = self._calculate_eaf(session_hours)
        
        # Overall psychology OK if all factors are acceptable
        psychology_ok = (
            stable 
            and losses_ok 
            and drawdown_ok 
            and fatigue_level != "HIGH"
            and eaf_result["can_trade"]
        )

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
            if not eaf_result["can_trade"]:
                reasons.append(f"EAF score {eaf_result['eaf_score']:.2f} < {EAF_MIN_FOR_TRADE}")
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
            # EAF fields
            "eaf_score": eaf_result["eaf_score"],
            "can_trade": eaf_result["can_trade"],
            "emotional_bias": eaf_result["emotional_bias"],
            "stability_index": eaf_result["stability_index"],
            "focus_level": eaf_result["focus_level"],
            "discipline_score": eaf_result["discipline_score"],
            # Additional fields for L4/L11 compatibility
            "emotion_index": eaf_result["emotion_index"],
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
        if hours >= FATIGUE_HIGH_HOURS:
            return "HIGH"
        if hours >= FATIGUE_MEDIUM_HOURS:
            return "MEDIUM"
        return "LOW"

    def _calculate_eaf(self, session_hours: float) -> dict:
        """
        Calculate EAF (Emotional-Accuracy Factor) using convex weighted formula.
        
        This replaces the multiplicative formula to avoid collapse problems.
        
        Args:
            session_hours: Current session duration in hours
            
        Returns:
            Dictionary with EAF components and score
        """
        # 1. Calculate emotional bias (0-1, lower is better)
        # Based on revenge trading indicators
        emotional_bias = self._calculate_emotional_bias()
        
        # 2. Calculate stability index (0-1, higher is better)
        # Based on consistency of performance
        stability_index = self._calculate_stability_index()
        
        # 3. Calculate focus level (0-1, higher is better)
        # Based on session duration and fatigue
        focus_level = self._calculate_focus_level(session_hours)
        
        # 4. Calculate discipline score (0-1, higher is better)
        # Based on adherence to trading rules
        discipline_score = self._calculate_discipline_score()
        
        # Convex weighted formula (NO multiplication collapse)
        eaf_score = (
            (1 - emotional_bias) * EAF_WEIGHTS["emotional_bias"]
            + stability_index * EAF_WEIGHTS["stability_index"]
            + focus_level * EAF_WEIGHTS["focus_level"]
            + discipline_score * EAF_WEIGHTS["discipline_score"]
        )
        
        can_trade = eaf_score >= EAF_MIN_FOR_TRADE
        
        return {
            "eaf_score": round(eaf_score, 3),
            "can_trade": can_trade,
            "emotional_bias": round(emotional_bias, 3),
            "stability_index": round(stability_index, 3),
            "focus_level": round(focus_level, 3),
            "discipline_score": round(discipline_score, 3),
            "emotion_index": int(emotional_bias * 100),  # For L11 compatibility
        }

    def _calculate_emotional_bias(self) -> float:
        """
        Calculate emotional bias (0-1, lower is better).
        
        Detects revenge trading and emotional decision-making.
        """
        if self._total_trades == 0:
            return 0.0
        
        # Consecutive losses increase emotional bias
        loss_factor = min(self._consecutive_losses / 5.0, 1.0)
        
        # Heavy drawdown increases emotional pressure
        drawdown_factor = min(self._current_drawdown / 10.0, 1.0)
        
        # Combine factors
        bias = (loss_factor * 0.6) + (drawdown_factor * 0.4)
        
        return min(bias, 1.0)

    def _calculate_stability_index(self) -> float:
        """
        Calculate stability index (0-1, higher is better).
        
        Based on consistency of performance.
        Fixed: Don't penalize high win rates - that's greed detection.
        """
        if self._total_trades < 3:
            return 0.80  # Default for new sessions
        
        # Stability is about consistency, not win rate
        # Low volatility in performance = high stability
        
        # Check if recent performance is consistent
        # Alternating wins/losses = high stability
        # Long streaks (win or loss) = lower stability
        max_streak = max(self._win_streak, self._loss_streak)
        
        if max_streak <= 2:
            return 0.90  # Very stable
        elif max_streak <= 4:
            return 0.75  # Moderate
        else:
            return 0.60  # Less stable (long streaks indicate potential issues)

    def _calculate_focus_level(self, session_hours: float) -> float:
        """
        Calculate focus level (0-1, higher is better).
        
        Based on session duration - professional sessions are 2-3 hours.
        Fixed: Start fatigue at 180min (3 hours) instead of 120min.
        """
        session_minutes = session_hours * 60
        
        if session_minutes < FATIGUE_SESSION_THRESHOLD_MINUTES:
            # Peak focus zone (0-3 hours)
            return 1.0 - (session_minutes / FATIGUE_SESSION_THRESHOLD_MINUTES) * 0.15
        else:
            # Fatigue begins after 3 hours
            overtime_hours = session_hours - (FATIGUE_SESSION_THRESHOLD_MINUTES / 60)
            # Linear decay: lose 0.10 per hour after threshold
            decay = min(overtime_hours * 0.10, 0.50)
            return max(0.775 - decay, 0.50)

    def _calculate_discipline_score(self) -> float:
        """
        Calculate discipline score (0-1, higher is better).
        
        Based on adherence to trading rules.
        """
        if self._total_trades == 0:
            return 1.0  # Perfect discipline at start
        
        # Discipline drops with excessive consecutive losses
        if self._consecutive_losses > MAX_CONSECUTIVE_LOSSES:
            return 0.60  # Below minimum (3+ losses)
        elif self._consecutive_losses == MAX_CONSECUTIVE_LOSSES:
            return 0.75  # At limit (2 losses)
        elif self._consecutive_losses == 1:
            return 0.90  # Minor issue
        else:
            return 1.0  # Perfect

    def record_loss(self) -> None:
        """Record a consecutive loss."""
        self._consecutive_losses += 1
        self._loss_streak += 1
        self._win_streak = 0
        self._total_trades += 1
        logger.warning(
            f"Consecutive losses: {self._consecutive_losses}/{MAX_CONSECUTIVE_LOSSES}"
        )

    def record_win(self) -> None:
        """Record a win (resets consecutive losses)."""
        if self._consecutive_losses > 0:
            logger.info(
                f"Win recorded, resetting consecutive losses from {self._consecutive_losses} to 0"
            )
        self._consecutive_losses = 0
        self._win_streak += 1
        self._loss_streak = 0
        self._total_trades += 1

    def update_drawdown(self, drawdown_percent: float) -> None:
        """
        Update current drawdown percentage.

        Args:
            drawdown_percent: Current drawdown as percentage (0-100)
        """
        self._current_drawdown = drawdown_percent

        if drawdown_percent >= MAX_DRAWDOWN_PERCENT:
            logger.warning(
                f"Drawdown alert: {drawdown_percent:.2f}% (limit: {MAX_DRAWDOWN_PERCENT}%)"
            )

    def reset_session(self) -> None:
        """Reset session tracking (e.g., at start of new trading day)."""
        RuntimeState.session_start = None  # Will be reinitialized on next call
        self._consecutive_losses = 0
        self._current_drawdown = 0.0
        self._win_streak = 0
        self._loss_streak = 0
        self._total_trades = 0
        logger.info("Psychology session reset")
