"""
Sniper Portfolio Optimizer - Markowitz + Kelly

Kelly fraction: (b*p - q) / b with division-by-zero guard.
Shrinkage covariance (Ledoit-Wolf diagonal).
Analytical 2x2 matrix inverse for 2-asset Markowitz.
Confidence power scaling.
Composes with existing CorrelationRiskResult.
Returns frozen PortfolioDecision with to_dict().

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

from engines.v11.config import get_v11


@dataclass(frozen=True)
class PortfolioDecision:
    """Immutable portfolio optimization result."""
    
    kelly_fraction: float
    optimal_weights: tuple[float, ...]
    expected_return: float
    portfolio_risk: float
    sharpe_ratio: float
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON."""
        return {
            "kelly_fraction": self.kelly_fraction,
            "optimal_weights": list(self.optimal_weights),
            "expected_return": self.expected_return,
            "portfolio_risk": self.portfolio_risk,
            "sharpe_ratio": self.sharpe_ratio,
        }


class SniperOptimizer:
    """
    Portfolio optimizer combining Kelly criterion and Markowitz optimization.
    
    Parameters
    ----------
    kelly_fraction : float
        Kelly dampening factor (default from config)
    confidence_power : float
        Confidence power scaling (default from config)
    risk_free_rate : float
        Risk-free rate for Sharpe calculation (default from config)
    shrinkage_target : float
        Shrinkage target for covariance (default from config)
    """
    
    def __init__(
        self,
        kelly_fraction: float | None = None,
        confidence_power: float | None = None,
        risk_free_rate: float | None = None,
        shrinkage_target: float | None = None,
    ) -> None:
        self._kelly_frac = kelly_fraction or get_v11("portfolio.kelly_fraction", 0.5)
        self._conf_power = confidence_power or get_v11("portfolio.confidence_power", 2.0)
        self._rf_rate = risk_free_rate or get_v11("portfolio.risk_free_rate", 0.02)
        self._shrinkage = shrinkage_target or get_v11("portfolio.shrinkage_target", 0.5)
    
    def optimize(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        confidence: float = 1.0,
        returns: np.ndarray | None = None,
    ) -> PortfolioDecision:
        """
        Optimize portfolio allocation using Kelly + Markowitz.
        
        Args:
            win_rate: Historical win rate (0-1)
            avg_win: Average win amount
            avg_loss: Average loss amount (positive)
            confidence: Confidence scaling (0-1)
            returns: Optional return matrix for Markowitz (n_assets x n_obs)
        
        Returns:
            PortfolioDecision with optimal allocation
        """
        # Kelly fraction
        kelly = self._compute_kelly(win_rate, avg_win, avg_loss)
        
        # Apply confidence scaling
        kelly *= (confidence ** self._conf_power)
        
        # Apply dampening
        kelly *= self._kelly_frac
        
        # Markowitz optimization (if returns provided)
        if returns is not None and len(returns) > 0:
            weights, exp_ret, port_risk = self._markowitz_optimize(returns)
        else:
            # Single asset case - use win rate and payoff for simple risk estimate
            weights = (1.0,)
            exp_ret = win_rate * avg_win - (1 - win_rate) * avg_loss
            # Estimate risk from expected profit/loss distribution
            # Risk = sqrt(WR * (avg_win - EV)^2 + (1-WR) * (-avg_loss - EV)^2)
            variance = win_rate * (avg_win - exp_ret) ** 2 + (1 - win_rate) * (-avg_loss - exp_ret) ** 2
            port_risk = float(np.sqrt(variance)) if variance > 0 else 0.0
        
        # Compute Sharpe ratio
        sharpe = self._compute_sharpe(exp_ret, port_risk)
        
        return PortfolioDecision(
            kelly_fraction=kelly,
            optimal_weights=weights,
            expected_return=exp_ret,
            portfolio_risk=port_risk,
            sharpe_ratio=sharpe,
        )
    
    def _compute_kelly(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Compute Kelly fraction: (b*p - q) / b
        
        Where:
        - p = win_rate
        - q = 1 - win_rate
        - b = avg_win / avg_loss (payoff ratio)
        """
        if avg_loss == 0:
            return 0.0
        
        b = avg_win / avg_loss
        
        if b == 0:
            return 0.0
        
        p = win_rate
        q = 1 - win_rate
        
        kelly = (b * p - q) / b
        
        # Clamp to [0, 1]
        return float(np.clip(kelly, 0.0, 1.0))
    
    def _markowitz_optimize(
        self, returns: np.ndarray
    ) -> tuple[tuple[float, ...], float, float]:
        """
        Markowitz mean-variance optimization.
        
        For 2-asset case, uses analytical solution.
        For single asset, returns (1.0,).
        
        Args:
            returns: Return matrix (n_assets x n_obs)
        
        Returns:
            (weights, expected_return, portfolio_risk)
        """
        returns_arr = np.asarray(returns, dtype=np.float64)
        
        # Ensure 2D
        if returns_arr.ndim == 1:
            returns_arr = returns_arr.reshape(1, -1)
        
        n_assets = returns_arr.shape[0]
        
        if n_assets == 1:
            # Single asset - use actual return volatility
            mean_return = float(np.mean(returns_arr[0]))
            risk = float(np.std(returns_arr[0])) if len(returns_arr[0]) > 1 else 0.0
            return (1.0,), mean_return, risk
        
        # Compute mean returns
        mean_returns = np.mean(returns_arr, axis=1)
        
        # Compute covariance with shrinkage
        cov_matrix = self._shrinkage_covariance(returns_arr)
        
        if n_assets == 2:
            # Analytical solution for 2 assets
            weights = self._solve_2asset(mean_returns, cov_matrix)
        else:
            # Equal weights for >2 assets (simplified)
            weights = tuple([1.0 / n_assets] * n_assets)
        
        # Compute expected return and risk
        weights_arr = np.array(weights)
        exp_ret = float(np.dot(weights_arr, mean_returns))
        port_risk = float(np.sqrt(np.dot(weights_arr, np.dot(cov_matrix, weights_arr))))
        
        return weights, exp_ret, port_risk
    
    def _shrinkage_covariance(self, returns: np.ndarray) -> np.ndarray:
        """
        Ledoit-Wolf diagonal shrinkage for covariance matrix.
        
        Cov = alpha * Sample_Cov + (1 - alpha) * Diagonal
        """
        # Sample covariance
        sample_cov = np.cov(returns)
        
        # Diagonal target (variance only)
        diag_target = np.diag(np.diag(sample_cov))
        
        # Shrinkage
        shrunk_cov = self._shrinkage * sample_cov + (1 - self._shrinkage) * diag_target
        
        return shrunk_cov
    
    def _solve_2asset(self, mean_returns: np.ndarray, cov_matrix: np.ndarray) -> tuple[float, float]:
        """
        Analytical solution for 2-asset Markowitz.
        
        Maximizes Sharpe ratio.
        """
        # Extract elements
        mu1, mu2 = mean_returns
        var1 = cov_matrix[0, 0]
        var2 = cov_matrix[1, 1]
        cov12 = cov_matrix[0, 1]
        
        # Excess returns
        r1 = mu1 - self._rf_rate
        r2 = mu2 - self._rf_rate
        
        # Analytical weights (max Sharpe)
        denom = r1**2 * var2 - 2 * r1 * r2 * cov12 + r2**2 * var1
        
        if denom == 0:
            # Equal weights fallback
            return (0.5, 0.5)
        
        w1 = (r1 * var2 - r2 * cov12) / denom
        w2 = (r2 * var1 - r1 * cov12) / denom
        
        # Normalize to sum to 1
        total = w1 + w2
        if total != 0:
            w1 /= total
            w2 /= total
        else:
            w1, w2 = 0.5, 0.5
        
        # Clamp to [0, 1] and renormalize
        w1 = float(np.clip(w1, 0.0, 1.0))
        w2 = float(np.clip(w2, 0.0, 1.0))
        
        total = w1 + w2
        if total > 0:
            w1 /= total
            w2 /= total
        else:
            w1, w2 = 0.5, 0.5
        
        return (w1, w2)
    
    def _compute_sharpe(self, exp_ret: float, port_risk: float) -> float:
        """Compute Sharpe ratio."""
        if port_risk == 0:
            return 0.0
        
        return (exp_ret - self._rf_rate) / port_risk
