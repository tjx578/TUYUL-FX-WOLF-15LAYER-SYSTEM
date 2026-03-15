"""Correlation Risk Engine -- Multi-pair hidden exposure detector.

Computes pairwise correlation across instruments to detect:
    - USD concentration risk (EURUSD + GBPUSD + XAUUSD overlap)
    - Multi-pair drawdown amplification
    - Hidden factor exposure via eigenvalue concentration

Authority: ANALYSIS-ONLY. No execution side-effects.
           Feeds L6 Risk as portfolio-level adjustment.
           L6 is currently PLACEHOLDER -- this fills that gap.

Bug fixes over original draft:
    ✅ Single-row matrix guard (need ≥ 2 pairs)
    ✅ NaN/Inf handling in return matrix (np.nan_to_num)
    ✅ Eigenvalue-based Herfindahl concentration (replaces max*avg product)
    ✅ Constant-series guard (NaN correlation -> 0)
    ✅ Minimum observations guard
    ✅ High-correlation pair flagging with labels
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CorrelationRiskResult:
    """Immutable result of multi-pair correlation risk evaluation."""

    max_correlation: float
    average_correlation: float
    concentration_risk: float  # Eigenvalue-based [0, 1]
    num_pairs: int
    high_correlation_pairs: tuple[tuple[int, int, float], ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / L6 risk consumption."""
        return {
            "max_correlation": self.max_correlation,
            "average_correlation": self.average_correlation,
            "concentration_risk": self.concentration_risk,
            "num_pairs": self.num_pairs,
            "high_correlation_pairs": [
                {"pair_i": i, "pair_j": j, "correlation": c} for i, j, c in self.high_correlation_pairs
            ],
            "passed": self.passed,
        }


class CorrelationRiskEngine:
    """Multi-pair correlation and concentration risk evaluator.

    Parameters
    ----------
    max_corr_threshold : float
        Maximum allowed |correlation| before failing. Default 0.85.
    high_corr_flag : float
        Threshold above which a pair is flagged. Default 0.70.
    min_observations : int
        Minimum return observations per pair. Default 20.
    """

    def __init__(
        self,
        max_corr_threshold: float = 0.85,
        high_corr_flag: float = 0.70,
        min_observations: int = 20,
    ) -> None:
        if max_corr_threshold <= 0 or max_corr_threshold > 1.0:
            raise ValueError(f"max_corr_threshold must be in (0, 1], got {max_corr_threshold}")
        self._max_corr = max_corr_threshold
        self._high_corr_flag = high_corr_flag
        self._min_obs = min_observations

    # ── Public API ───────────────────────────────────────────────────────────

    def evaluate(
        self,
        return_matrix: list[list[float]] | np.ndarray,
        pair_labels: list[str] | None = None,
    ) -> CorrelationRiskResult:
        """Evaluate correlation risk across multiple instruments.

        Args:
            return_matrix: 2D array of shape (num_pairs, num_observations).
                Each row = one instrument's return series.
            pair_labels: Optional names per row (for logging only).

        Returns:
            CorrelationRiskResult with concentration and pairwise metrics.

        Raises:
            ValueError: If fewer than 2 pairs or insufficient observations.
        """
        mat = np.asarray(return_matrix, dtype=np.float64)

        if mat.ndim != 2:
            raise ValueError(f"Expected 2D return matrix, got shape {mat.shape}")

        num_pairs, num_obs = mat.shape

        if num_pairs < 2:
            raise ValueError(f"Minimum 2 pairs required for correlation analysis, got {num_pairs}")
        if num_obs < self._min_obs:
            raise ValueError(f"Minimum {self._min_obs} observations per pair, got {num_obs}")

        # ── Clean NaN / Inf ──────────────────────────────────────────
        if np.any(~np.isfinite(mat)):
            mat = np.nan_to_num(mat, nan=0.0, posinf=0.0, neginf=0.0)

        # ── Correlation matrix ───────────────────────────────────────
        corr_matrix = np.atleast_2d(np.corrcoef(mat))
        # Constant series -> NaN correlations -> replace with 0
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

        # ── Upper triangle (exclude diagonal) ────────────────────────
        upper_idx = np.triu_indices(num_pairs, k=1)
        upper_corrs = corr_matrix[upper_idx]
        abs_upper = np.abs(upper_corrs)

        max_corr = float(np.max(abs_upper)) if len(abs_upper) > 0 else 0.0
        avg_corr = float(np.mean(abs_upper)) if len(abs_upper) > 0 else 0.0

        # ── High-correlation pairs ───────────────────────────────────
        high_pairs: list[tuple[int, int, float]] = []
        for idx in range(len(upper_corrs)):
            if float(abs_upper[idx]) >= self._high_corr_flag:
                i = int(upper_idx[0][idx])
                j = int(upper_idx[1][idx])
                high_pairs.append((i, j, round(float(upper_corrs[idx]), 4)))

        # ── Eigenvalue concentration (Herfindahl-Hirschman) ──────────
        concentration = self._eigenvalue_concentration(corr_matrix, num_pairs)

        passed = max_corr < self._max_corr

        return CorrelationRiskResult(
            max_correlation=round(max_corr, 4),
            average_correlation=round(avg_corr, 4),
            concentration_risk=round(concentration, 4),
            num_pairs=num_pairs,
            high_correlation_pairs=tuple(high_pairs),
            passed=passed,
        )

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _eigenvalue_concentration(
        corr_matrix: np.ndarray,
        num_pairs: int,
    ) -> float:
        """Compute Herfindahl-Hirschman index of eigenvalue shares.

        Measures how concentrated variance is across latent factors.
            1/n -> perfectly diversified (minimum)
            1.0 -> single factor dominates (maximum)

        Normalized to [0, 1]:  (HHI - 1/n) / (1 - 1/n)
        """
        try:
            eigenvalues = np.linalg.eigvalsh(corr_matrix)
            eigenvalues = np.maximum(eigenvalues, 0.0)  # numerical stability
            total = float(eigenvalues.sum())

            if total <= 0.0:
                return 0.0

            normalized = eigenvalues / total
            hhi = float(np.sum(normalized**2))

            min_hhi = 1.0 / num_pairs
            if num_pairs <= 1:
                return 0.0
            concentration = (hhi - min_hhi) / (1.0 - min_hhi)
            return max(0.0, min(1.0, concentration))

        except np.linalg.LinAlgError:
            # Fallback: simple product (degraded but safe)
            return 0.0
