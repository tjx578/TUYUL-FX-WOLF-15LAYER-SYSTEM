"""
Correlation Risk Guard — Atomic enforcement at position level.

Prevents opening correlated positions that would breach combined
exposure limits. Uses the CorrelationRiskEngine for analysis but
enforces limits as a GUARD (blocking authority).

Authority: risk/ — enforcement only, no market direction.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from storage.redis_client import RedisClient


class CorrelationVerdict(StrEnum):
    ALLOW = "ALLOW"
    REDUCE = "REDUCE"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class CorrelationGuardResult:
    """Result of correlation guard evaluation."""

    verdict: CorrelationVerdict
    combined_exposure: float  # Total risk across correlated group
    max_safe_risk: float  # Maximum additional risk allowed
    correlated_symbols: tuple[str, ...]  # Symbols in the correlated group
    max_correlation: float  # Highest pairwise correlation
    reason: str

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "combined_exposure": self.combined_exposure,
            "max_safe_risk": self.max_safe_risk,
            "correlated_symbols": list(self.correlated_symbols),
            "max_correlation": self.max_correlation,
            "reason": self.reason,
        }


# ── Static correlation map ───────────────────────────────────────────
# Pairs known to be highly correlated based on common factor exposure.
# Updated periodically by the CorrelationRiskEngine analysis output.
# Key: frozenset of two symbols → correlation coefficient.

_DEFAULT_CORRELATION_MAP: dict[frozenset[str], float] = {
    frozenset({"EURUSD", "GBPUSD"}): 0.85,
    frozenset({"EURUSD", "EURGBP"}): 0.75,
    frozenset({"GBPUSD", "EURGBP"}): 0.80,
    frozenset({"AUDUSD", "NZDUSD"}): 0.90,
    frozenset({"USDCAD", "USDCHF"}): 0.70,
    frozenset({"EURJPY", "GBPJPY"}): 0.82,
    frozenset({"USDJPY", "EURJPY"}): 0.72,
    frozenset({"USDJPY", "GBPJPY"}): 0.75,
    frozenset({"XAUUSD", "XAGUSD"}): 0.88,
    frozenset({"EURUSD", "USDCHF"}): 0.90,  # Inverse correlation (direction matters)
}

from core.redis_keys import RISK_CORRELATION_MAP as _REDIS_CORRELATION_MAP_KEY  # noqa: N811


class CorrelationGuard:
    """Atomic correlation risk enforcement at position level.

    When a new trade is proposed, this guard:
    1. Identifies all open positions in correlated pairs
    2. Sums the combined risk exposure across the correlated group
    3. Enforces a maximum combined exposure limit (per-group)
    4. Returns ALLOW / REDUCE / BLOCK verdict

    Parameters
    ----------
    max_group_exposure_pct : float
        Maximum combined risk percent for a correlated group. Default 3%.
    high_corr_threshold : float
        Correlation above which two pairs are considered in the same group.
    """

    _instance: CorrelationGuard | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        max_group_exposure_pct: float = 0.03,
        high_corr_threshold: float = 0.70,
    ) -> None:
        self._max_group_exposure_pct = max_group_exposure_pct
        self._high_corr_threshold = high_corr_threshold
        self._redis = RedisClient()
        self._correlation_map = dict(_DEFAULT_CORRELATION_MAP)
        self._try_load_dynamic_map()

    @classmethod
    def get_instance(
        cls,
        max_group_exposure_pct: float = 0.03,
        high_corr_threshold: float = 0.70,
    ) -> CorrelationGuard:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(max_group_exposure_pct, high_corr_threshold)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing."""
        with cls._lock:
            cls._instance = None

    # ── Public API ───────────────────────────────────────────────────

    def evaluate(
        self,
        proposed_symbol: str,
        proposed_direction: str,
        proposed_risk_amount: float,
        open_trades: list[dict],
        account_equity: float,
    ) -> CorrelationGuardResult:
        """Evaluate if a proposed trade would breach correlation exposure limits.

        Parameters
        ----------
        proposed_symbol : str
            Symbol of the proposed trade (e.g. "EURUSD").
        proposed_direction : str
            "BUY" or "SELL".
        proposed_risk_amount : float
            Risk amount in account currency for the proposed trade.
        open_trades : list[dict]
            Currently open trades. Each must have:
            - symbol (str)
            - direction (str)
            - risk_amount (float)
        account_equity : float
            Current account equity for percentage calculations.

        Returns
        -------
        CorrelationGuardResult
        """
        if account_equity <= 0:
            return CorrelationGuardResult(
                verdict=CorrelationVerdict.BLOCK,
                combined_exposure=0.0,
                max_safe_risk=0.0,
                correlated_symbols=(),
                max_correlation=0.0,
                reason="Account equity is zero or negative",
            )

        # Find all correlated symbols in current open trades
        correlated_group = self._find_correlated_group(proposed_symbol, proposed_direction, open_trades)

        if not correlated_group:
            return CorrelationGuardResult(
                verdict=CorrelationVerdict.ALLOW,
                combined_exposure=proposed_risk_amount / account_equity,
                max_safe_risk=self._max_group_exposure_pct * account_equity - proposed_risk_amount,
                correlated_symbols=(proposed_symbol,),
                max_correlation=0.0,
                reason="No correlated open positions",
            )

        # Sum existing exposure in the correlated group
        existing_exposure = sum(t["risk_amount"] for t in open_trades if t["symbol"] in correlated_group)

        combined_exposure = existing_exposure + proposed_risk_amount
        combined_exposure_pct = combined_exposure / account_equity
        max_corr = self._max_pairwise_correlation(proposed_symbol, correlated_group)

        group_limit = self._max_group_exposure_pct * account_equity
        remaining = max(0.0, group_limit - existing_exposure)

        all_symbols = tuple(sorted(correlated_group | {proposed_symbol}))

        if combined_exposure_pct >= self._max_group_exposure_pct:
            logger.warning(
                "Correlation guard BLOCK",
                proposed=proposed_symbol,
                group=all_symbols,
                combined_pct=f"{combined_exposure_pct * 100:.2f}%",
                limit_pct=f"{self._max_group_exposure_pct * 100:.2f}%",
                max_corr=max_corr,
            )
            return CorrelationGuardResult(
                verdict=CorrelationVerdict.BLOCK,
                combined_exposure=combined_exposure_pct,
                max_safe_risk=remaining,
                correlated_symbols=all_symbols,
                max_correlation=max_corr,
                reason=(
                    f"Combined correlated exposure {combined_exposure_pct * 100:.2f}% "
                    f">= limit {self._max_group_exposure_pct * 100:.2f}%"
                ),
            )

        # Warn if over 70% of limit
        warn_threshold = self._max_group_exposure_pct * 0.70
        if combined_exposure_pct >= warn_threshold:
            logger.info(
                "Correlation guard REDUCE",
                proposed=proposed_symbol,
                group=all_symbols,
                combined_pct=f"{combined_exposure_pct * 100:.2f}%",
            )
            return CorrelationGuardResult(
                verdict=CorrelationVerdict.REDUCE,
                combined_exposure=combined_exposure_pct,
                max_safe_risk=remaining,
                correlated_symbols=all_symbols,
                max_correlation=max_corr,
                reason=(
                    f"Correlated exposure {combined_exposure_pct * 100:.2f}% "
                    f"approaching limit, reduce risk to {remaining:.2f}"
                ),
            )

        return CorrelationGuardResult(
            verdict=CorrelationVerdict.ALLOW,
            combined_exposure=combined_exposure_pct,
            max_safe_risk=remaining,
            correlated_symbols=all_symbols,
            max_correlation=max_corr,
            reason="Correlated exposure within limits",
        )

    def update_correlation_map(self, new_map: dict[tuple[str, str], float]) -> None:
        """Update correlation map from CorrelationRiskEngine analysis output.

        Parameters
        ----------
        new_map : dict
            Key: (symbol_a, symbol_b), value: correlation coefficient.
        """
        updated: dict[frozenset[str], float] = {}
        for (s1, s2), corr in new_map.items():
            updated[frozenset({s1, s2})] = abs(corr)

        self._correlation_map.update(updated)
        self._persist_dynamic_map()

        logger.info(
            "Correlation map updated",
            pairs_updated=len(new_map),
            total_pairs=len(self._correlation_map),
        )

    # ── Private ──────────────────────────────────────────────────────

    def _find_correlated_group(
        self,
        proposed_symbol: str,
        proposed_direction: str,
        open_trades: list[dict],
    ) -> set[str]:
        """Find all open symbols that are correlated with the proposed symbol."""
        correlated = set()

        for trade in open_trades:
            sym = trade["symbol"]
            if sym == proposed_symbol:
                # Same symbol is always correlated
                correlated.add(sym)
                continue

            pair_key = frozenset({proposed_symbol, sym})
            corr = self._correlation_map.get(pair_key, 0.0)

            if corr >= self._high_corr_threshold:  # noqa: SIM102
                # Check direction: same direction on positively correlated pairs
                # or opposite direction on negatively correlated pairs = exposure stacking
                # For simplicity in static map (all abs values), same direction = risk stacking
                if trade["direction"] == proposed_direction or corr >= 0.85:
                    correlated.add(sym)

        return correlated

    def _max_pairwise_correlation(self, proposed_symbol: str, correlated_group: set[str]) -> float:
        """Find the highest correlation between proposed and group members."""
        max_corr = 0.0
        for sym in correlated_group:
            pair_key = frozenset({proposed_symbol, sym})
            corr = self._correlation_map.get(pair_key, 0.0)
            max_corr = max(max_corr, corr)
        return max_corr

    def _try_load_dynamic_map(self) -> None:
        """Load dynamic correlation map from Redis if available."""
        try:
            raw = self._redis.get(_REDIS_CORRELATION_MAP_KEY)
            if raw:
                data = json.loads(raw)
                for pair_str, corr in data.items():
                    # pair_str format: "EURUSD|GBPUSD"
                    parts = pair_str.split("|")
                    if len(parts) == 2:
                        self._correlation_map[frozenset(parts)] = float(corr)
                logger.debug("Loaded dynamic correlation map from Redis", pairs=len(data))
        except Exception as e:
            logger.warning("Failed to load dynamic correlation map", error=str(e))

    def _persist_dynamic_map(self) -> None:
        """Persist correlation map to Redis."""
        try:
            data = {}
            for pair_set, corr in self._correlation_map.items():
                symbols = sorted(pair_set)
                if len(symbols) == 2:
                    data[f"{symbols[0]}|{symbols[1]}"] = round(corr, 4)
            self._redis.set(_REDIS_CORRELATION_MAP_KEY, json.dumps(data))
        except Exception as e:
            logger.warning("Failed to persist correlation map", error=str(e))
