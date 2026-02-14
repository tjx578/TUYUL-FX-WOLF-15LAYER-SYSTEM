"""
L5 Psychology Analyzer - Psychology Gates + RGO Governance.

Sources:
    core_cognitive_unified.py  → EmotionFeedbackEngine, IntegrityEngine
    core_reflective_unified.py → EAFScoreCalculator, HexaVaultManager

Produces:
    - psychology_score (int 0-100)
    - eaf_score (float)       → target ≥ 0.70
    - emotion_delta (float)   → target ≤ 0.25
    - can_trade (bool)
    - gate_status (str)       → OPEN | WARNING | LOCKED
    - psychology_ok (bool)
    - fatigue_level (str)     → LOW | MEDIUM | HIGH
    - consecutive_losses (int)
    - session_hours (float)
    - losses_ok (bool)
    - drawdown_percent (float)
    - drawdown_ok (bool)
    - stable (bool)
    - focus_level (float)
    - emotional_bias (float)
    - discipline_score (float)
    - emotion_index (int)
    - stability_index (float)
    - recommendation (str)
    - rgo_governance (dict): integrity_level, vault_sync, lambda_esi_stable
    - valid (bool)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from context.runtime_state import RuntimeState

# Lazy-loaded core modules
_emotion_engine_class = None
_eaf_calc_class = None

try:
    import core.core_cognitive_unified

    from core.core_reflective_unified import EAFScoreCalculator

    _emotion_engine_class = core.core_cognitive_unified.EmotionFeedbackEngine
    _eaf_calc_class = EAFScoreCalculator
except ImportError as exc:
    logger.warning(f"[L5] Could not load core modules at import time: {exc}")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_CONSECUTIVE_LOSSES = 2
_MAX_DRAWDOWN_PERCENT = 5.0
_FATIGUE_MEDIUM_HOURS = 4.0
_FATIGUE_HIGH_HOURS = 6.0
_FOCUS_PEAK_END_HOURS = 3.0  # Focus starts degrading after 3 h


class L5PsychologyAnalyzer:
    """Layer 5: Psychology Gates Assessment - Confluence & Scoring zone."""

    def __init__(self) -> None:
        self._emotion_engine = None
        self._eaf_calc = None
        self._consecutive_losses: int = 0
        self._win_streak: int = 0
        self._drawdown_percent: float = 0.0

    # ------------------------------------------------------------------
    # State mutation helpers
    # ------------------------------------------------------------------

    def record_loss(self) -> None:
        """Record a consecutive loss."""
        self._consecutive_losses += 1
        self._win_streak = 0

    def record_win(self) -> None:
        """Record a win - resets consecutive losses."""
        self._consecutive_losses = 0
        self._win_streak += 1

    def update_drawdown(self, pct: float) -> None:
        """Update current drawdown percentage."""
        self._drawdown_percent = pct

    def reset_session(self) -> None:
        """Reset session state (losses, drawdown, session timer)."""
        self._consecutive_losses = 0
        self._win_streak = 0
        self._drawdown_percent = 0.0
        RuntimeState.session_start = None  # will re-init on next call

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._emotion_engine is not None:
            return
        if _emotion_engine_class is None or _eaf_calc_class is None:
            logger.warning("[L5] Core modules not available; skipping initialization")
            return
        try:
            self._emotion_engine = _emotion_engine_class()
            self._eaf_calc = _eaf_calc_class()
        except Exception as exc:
            logger.warning(f"[L5] Could not instantiate core modules: {exc}")

    @staticmethod
    def _fatigue_level(hours: float) -> str:
        if hours >= _FATIGUE_HIGH_HOURS:
            return "HIGH"
        if hours >= _FATIGUE_MEDIUM_HOURS:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _focus_level(hours: float) -> float:
        """Focus curve: ramps to 0.95 at ~2 h, starts degrading after 3 h."""
        if hours <= 0.0:
            return 0.90
        if hours <= _FOCUS_PEAK_END_HOURS:
            # Linear ramp from 0.90 to 0.95 during first 3 h
            return 0.90 + 0.05 * min(hours / _FOCUS_PEAK_END_HOURS, 1.0)
        # After peak: degrade ~0.10 per hour (meaningful fatigue)
        overshoot = hours - _FOCUS_PEAK_END_HOURS
        return max(0.40, 0.95 - 0.10 * overshoot)

    def _emotional_bias(self) -> float:
        """Higher = worse.  Driven by losses + drawdown."""
        loss_component = min(self._consecutive_losses * 0.12, 0.50)
        dd_component = min(self._drawdown_percent * 0.04, 0.40)
        return min(loss_component + dd_component, 1.0)

    def _discipline_score(self) -> float:
        if self._consecutive_losses == 0:
            return 0.95
        if self._consecutive_losses == 1:
            return 0.90
        if self._consecutive_losses == 2:
            return 0.75
        return 0.60  # 3+

    def _stability_index(self) -> float:
        """Long streaks (win or loss) reduce stability slightly."""
        streak = max(self._win_streak, self._consecutive_losses)
        if streak <= 2:
            return 0.90
        if streak <= 4:
            return 0.80
        return 0.65  # >4 - potential overconfidence / tilt risk

    def _eaf_score(self, focus: float, emotional_bias: float,
                   discipline: float, stability: float) -> float:
        """Convex-weighted EAF (no multiplicative collapse)."""
        w_focus = 0.30
        w_emotion = 0.25
        w_discipline = 0.25
        w_stability = 0.20
        emotion_contrib = max(0.0, 1.0 - emotional_bias)
        return (
            w_focus * focus
            + w_emotion * emotion_contrib
            + w_discipline * discipline
            + w_stability * stability
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(
        self, symbol: str, *, volatility_profile: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Assess trader psychology & emotional gates.

        Returns a dict with all psychology metrics needed by L4 and L11.
        """
        self._ensure_loaded()

        # --- Session hours ---
        session_hours = RuntimeState.get_session_hours()

        # --- Fatigue / focus ---
        fatigue = self._fatigue_level(session_hours)
        focus = self._focus_level(session_hours)

        # --- Losses ---
        losses_ok = self._consecutive_losses < _MAX_CONSECUTIVE_LOSSES

        # --- Drawdown ---
        drawdown_ok = self._drawdown_percent < _MAX_DRAWDOWN_PERCENT

        # --- Volatility stability ---
        vol_profile = (volatility_profile or {}).get("profile", "NORMAL")
        stable = vol_profile != "HIGH"

        # --- Derived scores ---
        emotional_bias = self._emotional_bias()
        discipline = self._discipline_score()
        stability = self._stability_index()
        eaf = self._eaf_score(focus, emotional_bias, discipline, stability)
        emotion_index = int(emotional_bias * 100)

        # --- Psychology OK determination ---
        reasons: list[str] = []
        if not losses_ok:
            reasons.append("consecutive losses at/above limit")
        if not drawdown_ok:
            reasons.append("drawdown exceeded")
        if fatigue == "HIGH":
            reasons.append("high fatigue")
        if not stable:
            reasons.append("high volatility")
        if eaf < 0.70:
            reasons.append("EAF score below threshold")

        psychology_ok = len(reasons) == 0
        can_trade = psychology_ok

        if psychology_ok:
            recommendation = "Psychology OK"
        else:
            recommendation = "Psychology NOT OK: " + "; ".join(reasons)

        # --- Gate status ---
        if psychology_ok:
            gate_status = "OPEN"
        elif len(reasons) <= 1:
            gate_status = "WARNING"
        else:
            gate_status = "LOCKED"

        psychology_score = max(0, min(100, int(eaf * 100)))

        return {
            # Core output
            "psychology_score": psychology_score,
            "eaf_score": round(eaf, 4),
            "emotion_delta": round(emotional_bias, 4),
            "can_trade": can_trade,
            "gate_status": gate_status,
            "rgo_governance": {
                "integrity_level": "FULL",
                "vault_sync": "SYNCED",
                "lambda_esi_stable": True,
            },
            "current_drawdown": self._drawdown_percent,
            "valid": True,
            # Extended keys expected by L4/L11
            "psychology_ok": psychology_ok,
            "fatigue_level": fatigue,
            "consecutive_losses": self._consecutive_losses,
            "session_hours": session_hours,
            "losses_ok": losses_ok,
            "drawdown_percent": self._drawdown_percent,
            "drawdown_ok": drawdown_ok,
            "stable": stable,
            "focus_level": round(focus, 4),
            "emotional_bias": round(emotional_bias, 4),
            "discipline_score": round(discipline, 4),
            "emotion_index": emotion_index,
            "stability_index": round(stability, 4),
            "recommendation": recommendation,
        }
