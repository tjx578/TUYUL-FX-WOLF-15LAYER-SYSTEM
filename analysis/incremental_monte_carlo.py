"""
Incremental Monte Carlo Engine — Cache-aware portfolio risk assessment.

Wraps the existing portfolio_monte_carlo module with:
1. Incremental update capability (add/remove single pair without full rerun)
2. Redis cache with TTL and invalidation on trade close
3. Delta computation for fast updates
4. Staleness detection for cron-based vs live assessment

Authority: analysis-only. No execution side-effects.
Zone: analysis/
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass

from analysis.portfolio_monte_carlo import (
    PairSpec,
    PortfolioMCResult,
    run_portfolio_monte_carlo,
)

logger = logging.getLogger(__name__)

_REDIS_MC_CACHE_PREFIX = "wolf15:analysis:mc_cache:"
_REDIS_MC_META_KEY = "wolf15:analysis:mc_meta"
_DEFAULT_TTL_SECONDS = 300  # 5 min cache
_STALENESS_THRESHOLD_SECONDS = 600  # 10 min = stale


@dataclass
class MCCacheEntry:
    """Cached Monte Carlo result with metadata."""

    result: PortfolioMCResult
    computed_at: float
    pair_hash: str
    n_simulations: int
    is_incremental: bool = False  # True if this was an incremental update
    staleness_threshold: float = _STALENESS_THRESHOLD_SECONDS

    @property
    def age_seconds(self) -> float:
        return time.time() - self.computed_at

    @property
    def is_stale(self) -> bool:
        return self.age_seconds > self.staleness_threshold


@dataclass
class IncrementalDelta:
    """Delta info when a single pair is added/removed."""

    delta_type: str  # "ADD" or "REMOVE"
    symbol: str
    old_advisory: str
    new_advisory: str
    risk_of_ruin_change: float
    max_dd_change: float
    diversification_change: float


class IncrementalMonteCarlo:
    """Cache-aware incremental Monte Carlo portfolio risk engine.

    Maintains a cache of the most recent full MC run and provides
    fast incremental updates when a single pair is added or removed.
    Full re-runs are triggered when:
    - Cache is stale (> TTL)
    - More than 1 pair changes at once
    - Cache is invalidated (trade close event)

    Parameters
    ----------
    ttl_seconds : int
        Cache time-to-live. Default 300s (5 min).
    staleness_seconds : int
        Age after which a cached result is considered stale.
    n_simulations_full : int
        Simulations for full MC run.
    n_simulations_incremental : int
        Simulations for incremental delta (can be lower for speed).
    """

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        staleness_seconds: int = _STALENESS_THRESHOLD_SECONDS,
        n_simulations_full: int = 10_000,
        n_simulations_incremental: int = 5_000,
        redis_client: object | None = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._staleness = staleness_seconds
        self._n_sims_full = n_simulations_full
        self._n_sims_incr = n_simulations_incremental
        self._redis = redis_client

        # In-memory cache (fastest path)
        self._cache: MCCacheEntry | None = None
        self._pair_specs: list[PairSpec] = []
        self._correlations: dict[tuple[str, str], float] = {}

    # ── Public API ───────────────────────────────────────────────────

    def run_full(
        self,
        pair_specs: list[PairSpec],
        correlations: dict[tuple[str, str], float] | None = None,
        seed: int | None = None,
    ) -> PortfolioMCResult:
        """Run a full MC simulation and cache the result.

        Parameters
        ----------
        pair_specs : list[PairSpec]
            Current portfolio pairs.
        correlations : dict, optional
            Pairwise correlations.
        seed : int, optional
            RNG seed for reproducibility.

        Returns
        -------
        PortfolioMCResult
        """
        self._pair_specs = list(pair_specs)
        self._correlations = dict(correlations) if correlations else {}

        if not pair_specs:
            empty = PortfolioMCResult(
                portfolio_win_rate=0.0,
                portfolio_profit_factor=0.0,
                portfolio_risk_of_ruin=1.0,
                portfolio_max_drawdown=0.0,
                portfolio_expected_value=0.0,
                diversification_ratio=0.0,
                advisory_flag="BLOCK",
            )
            self._cache = MCCacheEntry(
                result=empty,
                computed_at=time.time(),
                pair_hash="",
                n_simulations=0,
                staleness_threshold=self._staleness,
            )
            return empty

        result = run_portfolio_monte_carlo(
            pair_specs=pair_specs,
            historical_correlations=correlations,
            n_simulations=self._n_sims_full,
            seed=seed,
        )

        self._cache = MCCacheEntry(
            result=result,
            computed_at=time.time(),
            pair_hash=self._compute_pair_hash(pair_specs),
            n_simulations=self._n_sims_full,
            is_incremental=False,
            staleness_threshold=self._staleness,
        )

        self._persist_cache()

        logger.info(
            "Full MC run cached: %d pairs, advisory=%s",
            len(pair_specs),
            result.advisory_flag,
        )

        return result

    def add_pair(
        self,
        new_pair: PairSpec,
        pair_correlations: dict[tuple[str, str], float] | None = None,
        seed: int | None = None,
    ) -> tuple[PortfolioMCResult, IncrementalDelta | None]:
        """Incrementally add a pair and estimate impact.

        If cache is fresh, runs a smaller MC with the new pair added
        and computes the delta. If cache is stale, runs full MC.

        Returns
        -------
        tuple[PortfolioMCResult, IncrementalDelta | None]
            Updated result and delta info (None if full rerun was needed).
        """
        # Update internal state
        updated_specs = list(self._pair_specs) + [new_pair]
        if pair_correlations:
            self._correlations.update(pair_correlations)

        # Check if we can do incremental
        if self._cache is not None and not self._cache.is_stale:
            old_result = self._cache.result

            # Run smaller MC with all pairs including the new one
            new_result = run_portfolio_monte_carlo(
                pair_specs=updated_specs,
                historical_correlations=self._correlations or None,
                n_simulations=self._n_sims_incr,
                seed=seed,
            )

            delta = IncrementalDelta(
                delta_type="ADD",
                symbol=new_pair.symbol,
                old_advisory=old_result.advisory_flag,
                new_advisory=new_result.advisory_flag,
                risk_of_ruin_change=new_result.portfolio_risk_of_ruin - old_result.portfolio_risk_of_ruin,
                max_dd_change=new_result.portfolio_max_drawdown - old_result.portfolio_max_drawdown,
                diversification_change=new_result.diversification_ratio - old_result.diversification_ratio,
            )

            # Update cache
            self._pair_specs = updated_specs
            self._cache = MCCacheEntry(
                result=new_result,
                computed_at=time.time(),
                pair_hash=self._compute_pair_hash(updated_specs),
                n_simulations=self._n_sims_incr,
                is_incremental=True,
                staleness_threshold=self._staleness,
            )
            self._persist_cache()

            logger.info(
                "Incremental MC (ADD %s): advisory %s -> %s, RoR change %.4f",
                new_pair.symbol,
                delta.old_advisory,
                delta.new_advisory,
                delta.risk_of_ruin_change,
            )

            return new_result, delta

        # Cache stale or missing → full rerun
        logger.info("Cache stale, running full MC with %d pairs", len(updated_specs))
        result = self.run_full(updated_specs, self._correlations or None, seed)
        self._pair_specs = updated_specs
        return result, None

    def remove_pair(
        self,
        symbol: str,
        seed: int | None = None,
    ) -> tuple[PortfolioMCResult, IncrementalDelta | None]:
        """Incrementally remove a pair (trade closed) and estimate impact.

        Always invalidates cache since a trade close changes the portfolio.
        """
        old_result = self._cache.result if self._cache else None

        # Remove pair from specs
        updated_specs = [p for p in self._pair_specs if p.symbol != symbol]
        self._pair_specs = updated_specs

        if not updated_specs:
            # No pairs left → empty result
            empty = PortfolioMCResult(
                portfolio_win_rate=0.0,
                portfolio_profit_factor=0.0,
                portfolio_risk_of_ruin=0.0,
                portfolio_max_drawdown=0.0,
                portfolio_expected_value=0.0,
                diversification_ratio=1.0,
                advisory_flag="PASS",
            )
            self._cache = MCCacheEntry(
                result=empty,
                computed_at=time.time(),
                pair_hash="",
                n_simulations=0,
                staleness_threshold=self._staleness,
            )
            delta = None
            if old_result:
                delta = IncrementalDelta(
                    delta_type="REMOVE",
                    symbol=symbol,
                    old_advisory=old_result.advisory_flag,
                    new_advisory="PASS",
                    risk_of_ruin_change=-old_result.portfolio_risk_of_ruin,
                    max_dd_change=-old_result.portfolio_max_drawdown,
                    diversification_change=1.0 - old_result.diversification_ratio,
                )
            return empty, delta

        # Run MC with remaining pairs
        new_result = run_portfolio_monte_carlo(
            pair_specs=updated_specs,
            historical_correlations=self._correlations or None,
            n_simulations=self._n_sims_incr,
            seed=seed,
        )

        self._cache = MCCacheEntry(
            result=new_result,
            computed_at=time.time(),
            pair_hash=self._compute_pair_hash(updated_specs),
            n_simulations=self._n_sims_incr,
            is_incremental=True,
            staleness_threshold=self._staleness,
        )
        self._persist_cache()

        delta = None
        if old_result:
            delta = IncrementalDelta(
                delta_type="REMOVE",
                symbol=symbol,
                old_advisory=old_result.advisory_flag,
                new_advisory=new_result.advisory_flag,
                risk_of_ruin_change=new_result.portfolio_risk_of_ruin - old_result.portfolio_risk_of_ruin,
                max_dd_change=new_result.portfolio_max_drawdown - old_result.portfolio_max_drawdown,
                diversification_change=new_result.diversification_ratio - old_result.diversification_ratio,
            )

        logger.info(
            "Incremental MC (REMOVE %s): %d pairs remaining, advisory=%s",
            symbol,
            len(updated_specs),
            new_result.advisory_flag,
        )

        return new_result, delta

    def invalidate(self) -> None:
        """Force cache invalidation (e.g. on trade close event)."""
        self._cache = None
        self._clear_redis_cache()
        logger.info("MC cache invalidated")

    def get_cached(self) -> MCCacheEntry | None:
        """Get cached result if available and fresh."""
        if self._cache and not self._cache.is_stale:
            return self._cache
        return None

    def get_staleness_info(self) -> dict:
        """Return info about cache freshness."""
        if not self._cache:
            return {
                "has_cache": False,
                "is_stale": True,
                "age_seconds": None,
                "pair_count": len(self._pair_specs),
            }
        return {
            "has_cache": True,
            "is_stale": self._cache.is_stale,
            "age_seconds": round(self._cache.age_seconds, 1),
            "is_incremental": self._cache.is_incremental,
            "pair_count": len(self._pair_specs),
            "advisory": self._cache.result.advisory_flag,
        }

    # ── Private ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_pair_hash(pair_specs: list[PairSpec]) -> str:
        """Compute a stable hash of the current pair set."""
        key_data = sorted(f"{p.symbol}:{p.win_probability:.4f}:{p.avg_win:.4f}:{p.avg_loss:.4f}" for p in pair_specs)
        return hashlib.sha256("|".join(key_data).encode()).hexdigest()[:16]

    def _persist_cache(self) -> None:
        """Persist cache metadata to Redis and PostgreSQL."""
        if not self._cache:
            return

        # --- Redis (metadata only) ---
        if self._redis:
            try:
                meta = {
                    "computed_at": self._cache.computed_at,
                    "pair_hash": self._cache.pair_hash,
                    "n_simulations": self._cache.n_simulations,
                    "is_incremental": self._cache.is_incremental,
                    "advisory": self._cache.result.advisory_flag,
                    "risk_of_ruin": self._cache.result.portfolio_risk_of_ruin,
                    "max_drawdown": self._cache.result.portfolio_max_drawdown,
                    "pair_count": len(self._pair_specs),
                }
                if hasattr(self._redis, "set"):
                    self._redis.set(  # type: ignore[union-attr]
                        _REDIS_MC_META_KEY,
                        json.dumps(meta),
                    )
            except Exception as e:
                logger.warning("Failed to persist MC cache metadata: %s", e)

        # --- PostgreSQL (full result for historical trending) ---
        self._persist_to_postgres()

    def _persist_to_postgres(self) -> None:
        """Fire-and-forget async write of MC result to PostgreSQL."""
        if not self._cache:
            return
        try:
            from storage.mc_persistence import persist_mc_result  # noqa: PLC0415
        except ImportError:
            return

        cache = self._cache
        pair_specs = list(self._pair_specs)

        async def _write() -> None:
            try:
                await persist_mc_result(
                    result=cache.result,
                    pair_specs=pair_specs,
                    is_incremental=cache.is_incremental,
                    computed_at=cache.computed_at,
                )
            except Exception as exc:
                logger.warning("MC postgres persistence failed: %s", exc)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write())
        except RuntimeError:
            # No running event loop — skip async persistence
            logger.debug("MC postgres persistence skipped: no running event loop")

    def _clear_redis_cache(self) -> None:
        """Clear Redis cache."""
        if not self._redis:
            return
        try:
            if hasattr(self._redis, "delete"):
                self._redis.delete(_REDIS_MC_META_KEY)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("Failed to clear MC cache: %s", e)
