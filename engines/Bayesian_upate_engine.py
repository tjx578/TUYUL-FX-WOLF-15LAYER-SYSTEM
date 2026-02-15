"""Bayesian Probability Update Engine -- Layer-7 Bayesian inference.

Maintains Beta-distributed beliefs about win probability and updates
them with new evidence scores.

ANALYSIS-ONLY module. No execution side-effects.
"""  # noqa: N999

from __future__ import annotations

from dataclasses import dataclass

import numpy as np  # pyright: ignore[reportMissingImports]


@dataclass
class BayesianResult:
    """Result of Bayesian probability update."""

    posterior_win_probability: float
    confidence_interval_low: float
    confidence_interval_high: float
    alpha: float
    beta: float

    def to_dict(self) -> dict[str, float]:
        return {
            "posterior_win_probability": self.posterior_win_probability,
            "confidence_interval_low": self.confidence_interval_low,
            "confidence_interval_high": self.confidence_interval_high,
            "alpha": self.alpha,
            "beta": self.beta,
        }


class BayesianProbabilityEngine:
    """Beta-Binomial Bayesian updater for win-probability estimation.

    Parameters
    ----------
    evidence_weight : int
        How many pseudo-observations a single evidence score is worth (default 10).
    ci_percentile_low : float
        Lower percentile for credible interval (default 5.0).
    ci_percentile_high : float
        Upper percentile for credible interval (default 95.0).
    ci_samples : int
        Number of posterior samples for CI estimation (default 10_000).
    seed : int | None
        RNG seed for reproducibility.
    """

    def __init__(
        self,
        evidence_weight: int = 10,
        ci_percentile_low: float = 5.0,
        ci_percentile_high: float = 95.0,
        ci_samples: int = 10_000,
        seed: int | None = 42,
    ) -> None:
        self.evidence_weight = evidence_weight
        self.ci_percentile_low = ci_percentile_low
        self.ci_percentile_high = ci_percentile_high
        self.ci_samples = ci_samples
        self._rng = np.random.default_rng(seed)

    def update(
        self,
        prior_wins: int,
        prior_losses: int,
        new_evidence_score: float,
    ) -> BayesianResult:
        """Update Beta prior with new evidence.

        Args:
            prior_wins: Observed wins so far (≥ 0).
            prior_losses: Observed losses so far (≥ 0).
            new_evidence_score: Signal quality score in [0, 1].

        Returns:
            BayesianResult with posterior mean and credible interval.

        Raises:
            ValueError: If prior counts are negative or evidence out of range.
        """
        if prior_wins < 0 or prior_losses < 0:
            raise ValueError(
                f"Invalid prior counts: wins={prior_wins}, losses={prior_losses}"
            )
        if not 0.0 <= new_evidence_score <= 1.0:
            raise ValueError(
                f"Evidence score must be in [0, 1], got {new_evidence_score}"
            )

        # Beta prior (add 1 for uninformative Bayes-Laplace prior)
        alpha_prior = prior_wins + 1
        beta_prior = prior_losses + 1

        # Convert evidence score to pseudo-counts
        alpha_post = alpha_prior + new_evidence_score * self.evidence_weight
        beta_post = beta_prior + (1.0 - new_evidence_score) * self.evidence_weight

        posterior_mean = alpha_post / (alpha_post + beta_post)

        # Credible interval via posterior sampling
        samples = self._rng.beta(alpha_post, beta_post, self.ci_samples)
        ci_low = float(np.percentile(samples, self.ci_percentile_low))
        ci_high = float(np.percentile(samples, self.ci_percentile_high))

        return BayesianResult(
            posterior_win_probability=round(posterior_mean, 4),
            confidence_interval_low=round(ci_low, 4),
            confidence_interval_high=round(ci_high, 4),
            alpha=round(alpha_post, 2),
            beta=round(beta_post, 2),
        )
