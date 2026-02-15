"""Dynamic Position Sizing Engine — Kelly + CVaR + Volatility + Bayesian Hybrid.

Institutional-grade position sizing that maximizes geometric growth while
governing tail risk, volatility clustering, and posterior confidence.

    f_final = Kelly × CVaR_adj × Vol_adj × Posterior_adj
    f_final = min(f_final, max_risk_cap)

Authority: ANALYSIS-ONLY. No execution side-effects.
           Outputs a recommended risk fraction for L10 consumption.
           Does NOT replace risk/position_sizer.py (execution-layer).
           Does NOT replace analysis/layers/L10_position_sizing.py (pipeline).
           This is an enrichment engine whose output injects into L10.

Integration flow:
    L7 Monte Carlo ──→ win_probability, avg_win, avg_loss
    L7 Bayesian    ──→ posterior_probability
    Vol Clustering ──→ risk_multiplier (volatility_multiplier)
    Trade history  ──→ returns_history (for CVaR)
         │
         ▼
    DynamicPositionSizingEngine.calculate()
         │
         ▼  (inject as risk_data.max_risk_pct override)
    L10 Position Analyzer (existing)
         │
         ▼
    L12 Verdict Engine (existing, constitutional gate)

Bug fixes over draft:
    ✅ avg_loss sign-agnostic: accepts negative, uses abs() internally
    ✅ Empty returns_history guard (minimum 10 observations)
    ✅ Empty tail slice guard (CVaR NaN prevention)
    ✅ volatility_multiplier == 0 → ZeroDivisionError prevented (clamp ≥ 0.01)
    ✅ Input validation: win_probability ∈ [0, 1], posterior ∈ [0, 1]
    ✅ avg_win <= 0 guard (payoff ratio undefined)
    ✅ Fractional Kelly support (default half-Kelly for safety)
    ✅ CVaR sensitivity configurable (replaces magic constant)
    ✅ Negative Kelly detection flagged in result
    ✅ Frozen dataclass result with to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

# ── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_MAX_RISK_CAP = 0.03          # 3% absolute maximum risk per trade
_DEFAULT_KELLY_FRACTION = 0.5         # Half-Kelly (conservative institutional)
_DEFAULT_CVAR_CONFIDENCE = 0.95       # 95% CVaR (5th percentile)
_DEFAULT_CVAR_SENSITIVITY = 5.0       # CVaR dampening coefficient
_DEFAULT_MIN_RETURNS = 10             # Minimum return history for CVaR
_DEFAULT_MIN_VOL_MULT = 0.01         # Floor for volatility multiplier


@dataclass(frozen=True)
class PositionSizingResult:
    """Immutable result of dynamic position sizing computation.

    All fractional values are in [0, 1] range (0% to 100% of capital).
    ``final_fraction`` is the recommended risk fraction after all adjustments,
    capped at ``max_risk_cap``.
    """

    # ── Component outputs ────────────────────────────────────────────
    kelly_raw: float              # Raw full-Kelly fraction (can be negative)
    kelly_fraction: float         # Fractional Kelly after clamp [0, 1]
    cvar_adjustment: float        # CVaR dampening factor (0, 1]
    volatility_adjustment: float  # Volatility dampening factor (0, 1]
    posterior_adjustment: float   # Bayesian posterior scaling [0, 1]

    # ── Final output ─────────────────────────────────────────────────
    final_fraction: float         # Recommended risk fraction [0, max_risk_cap]
    risk_percent: float           # final_fraction × 100 for display
    max_risk_cap: float           # Applied cap value

    # ── Diagnostics ──────────────────────────────────────────────────
    edge_negative: bool           # True if Kelly raw was negative (no edge)
    cvar_value: float             # Computed CVaR (Expected Shortfall)
    var_value: float              # Computed VaR at confidence level
    payoff_ratio: float           # avg_win / abs(avg_loss)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L10 / L12 consumption."""
        return {
            "kelly_raw": self.kelly_raw,
            "kelly_fraction": self.kelly_fraction,
            "cvar_adjustment": self.cvar_adjustment,
            "volatility_adjustment": self.volatility_adjustment,
            "posterior_adjustment": self.posterior_adjustment,
            "final_fraction": self.final_fraction,
            "risk_percent": self.risk_percent,
            "max_risk_cap": self.max_risk_cap,
            "edge_negative": self.edge_negative,
            "cvar_value": self.cvar_value,
            "var_value": self.var_value,
            "payoff_ratio": self.payoff_ratio,
        }


class DynamicPositionSizingEngine:
    """Kelly + CVaR + Volatility + Bayesian hybrid position sizing.

    Computes optimal risk fraction by multiplying four independent
    adjustment factors, then capping at an absolute maximum.

    Parameters
    ----------
    max_risk_cap : float
        Absolute maximum risk fraction per trade. Default 0.03 (3%).
        Prop-firm safe: most firms allow 1–2% daily loss.
    kelly_fraction_multiplier : float
        Fraction of full Kelly to use. Default 0.5 (half-Kelly).
        Full Kelly (1.0) is theoretically optimal but practically
        too aggressive for finite sample sizes.
    cvar_confidence : float
        Confidence level for CVaR computation. Default 0.95.
        CVaR is computed at the (1 - confidence) percentile.
    cvar_sensitivity : float
        Dampening coefficient for CVaR adjustment. Default 5.0.
        Higher = more aggressive size reduction from tail risk.
    min_returns : int
        Minimum return history length for CVaR. Default 10.
    """

    def __init__(
        self,
        max_risk_cap: float = _DEFAULT_MAX_RISK_CAP,
        kelly_fraction_multiplier: float = _DEFAULT_KELLY_FRACTION,
        cvar_confidence: float = _DEFAULT_CVAR_CONFIDENCE,
        cvar_sensitivity: float = _DEFAULT_CVAR_SENSITIVITY,
        min_returns: int = _DEFAULT_MIN_RETURNS,
    ) -> None:
        if not 0.0 < max_risk_cap <= 1.0:
            raise ValueError(f"max_risk_cap must be in (0, 1], got {max_risk_cap}")
        if not 0.0 < kelly_fraction_multiplier <= 1.0:
            raise ValueError(
                f"kelly_fraction_multiplier must be in (0, 1], got {kelly_fraction_multiplier}"
            )
        if not 0.0 < cvar_confidence < 1.0:
            raise ValueError(f"cvar_confidence must be in (0, 1), got {cvar_confidence}")
        if cvar_sensitivity <= 0.0:
            raise ValueError(f"cvar_sensitivity must be > 0, got {cvar_sensitivity}")

        self._max_risk_cap = max_risk_cap
        self._kelly_frac = kelly_fraction_multiplier
        self._cvar_conf = cvar_confidence
        self._cvar_sens = cvar_sensitivity
        self._min_returns = max(2, min_returns)

    # ── Public API ───────────────────────────────────────────────────────────

    def calculate(
        self,
        win_probability: float,
        avg_win: float,
        avg_loss: float,
        posterior_probability: float,
        returns_history: list[float],
        volatility_multiplier: float = 1.0,
    ) -> PositionSizingResult:
        """Compute hybrid position sizing recommendation.

        Args:
            win_probability: Historical or Monte Carlo win rate [0, 1].
            avg_win: Average winning trade P&L (must be > 0).
            avg_loss: Average losing trade P&L (sign-agnostic; abs used).
            posterior_probability: Bayesian posterior win probability [0, 1].
            returns_history: Historical trade returns for CVaR computation.
            volatility_multiplier: From VolatilityClusteringModel.risk_multiplier.
                Values > 1.0 reduce position size.

        Returns:
            PositionSizingResult with all component adjustments and final fraction.

        Raises:
            ValueError: On invalid inputs.
        """
        # ── Input validation ─────────────────────────────────────────
        self._validate_inputs(
            win_probability, avg_win, avg_loss,
            posterior_probability, returns_history, volatility_multiplier,
        )

        abs_avg_loss = abs(avg_loss)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1️⃣  KELLY CRITERION (Growth Optimizer)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        payoff_ratio = avg_win / abs_avg_loss  # b = W/L
        q = 1.0 - win_probability

        # f* = (bp - q) / b  =  p - q/b
        kelly_raw = (payoff_ratio * win_probability - q) / payoff_ratio

        edge_negative = kelly_raw <= 0.0

        # Apply fractional Kelly and clamp to [0, 1]
        kelly_fraction = max(0.0, min(kelly_raw * self._kelly_frac, 1.0))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2️⃣  CVaR TAIL RISK PROTECTION (Expected Shortfall)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        var_value, cvar_value, cvar_adjustment = self._compute_cvar(returns_history)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 3️⃣  VOLATILITY CLUSTERING ADJUSTMENT
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Clamp multiplier to prevent division by zero
        safe_vol_mult = max(_DEFAULT_MIN_VOL_MULT, volatility_multiplier)
        volatility_adjustment = 1.0 / safe_vol_mult
        # Clamp to (0, 1] — multiplier ≥ 1 always reduces; < 1 would amplify
        volatility_adjustment = max(0.0, min(1.0, volatility_adjustment))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4️⃣  BAYESIAN POSTERIOR CONFIDENCE
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Clamp to [0, 1] — posterior > 1 would amplify beyond Kelly
        posterior_adjustment = max(0.0, min(1.0, posterior_probability))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # FINAL HYBRID FRACTION
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        final_fraction = (
            kelly_fraction
            * cvar_adjustment
            * volatility_adjustment
            * posterior_adjustment
        )

        # Absolute cap — prop-firm safety
        final_fraction = max(0.0, min(final_fraction, self._max_risk_cap))

        return PositionSizingResult(
            kelly_raw=round(kelly_raw, 6),
            kelly_fraction=round(kelly_fraction, 4),
            cvar_adjustment=round(cvar_adjustment, 4),
            volatility_adjustment=round(volatility_adjustment, 4),
            posterior_adjustment=round(posterior_adjustment, 4),
            final_fraction=round(final_fraction, 6),
            risk_percent=round(final_fraction * 100, 2),
            max_risk_cap=self._max_risk_cap,
            edge_negative=edge_negative,
            cvar_value=round(cvar_value, 6),
            var_value=round(var_value, 6),
            payoff_ratio=round(payoff_ratio, 4),
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _validate_inputs(
        self,
        win_probability: float,
        avg_win: float,
        avg_loss: float,
        posterior_probability: float,
        returns_history: list[float],
        volatility_multiplier: float,
    ) -> None:
        """Validate all inputs with explicit error messages."""
        if not 0.0 <= win_probability <= 1.0:
            raise ValueError(
                f"win_probability must be in [0, 1], got {win_probability}"
            )
        if avg_win <= 0.0:
            raise ValueError(
                f"avg_win must be > 0 (average winning P&L), got {avg_win}"
            )
        if avg_loss == 0.0:
            raise ValueError(
                "avg_loss cannot be zero (division by zero in payoff ratio)"
            )
        if not 0.0 <= posterior_probability <= 1.0:
            raise ValueError(
                f"posterior_probability must be in [0, 1], got {posterior_probability}"
            )
        if len(returns_history) < self._min_returns:
            raise ValueError(
                f"returns_history needs ≥ {self._min_returns} observations "
                f"for CVaR computation, got {len(returns_history)}"
            )
        if volatility_multiplier < 0.0:
            raise ValueError(
                f"volatility_multiplier must be ≥ 0, got {volatility_multiplier}"
            )

    def _compute_cvar(
        self, returns_history: list[float],
    ) -> tuple[float, float, float]:
        """Compute VaR, CVaR (Expected Shortfall), and the CVaR adjustment factor.

        Returns:
            (var_value, cvar_value, cvar_adjustment)
        """
        arr = np.asarray(returns_history, dtype=np.float64)

        # VaR at (1 - confidence) percentile
        # For 95% confidence → 5th percentile (worst 5% of returns)
        percentile = (1.0 - self._cvar_conf) * 100.0
        var_value = float(np.percentile(arr, percentile))

        # CVaR = mean of returns ≤ VaR (Expected Shortfall)
        tail = arr[arr <= var_value]

        if len(tail) == 0:
            # No returns at or below VaR → use VaR as CVaR (conservative)
            cvar_value = var_value
        else:
            cvar_value = float(np.mean(tail))

        # CVaR adjustment: larger tail loss → smaller position
        # adj = 1 / (1 + |CVaR| × sensitivity)
        # Range: (0, 1] — always reduces, never amplifies
        cvar_adjustment = 1.0 / (1.0 + abs(cvar_value) * self._cvar_sens)

        return var_value, cvar_value, cvar_adjustment
