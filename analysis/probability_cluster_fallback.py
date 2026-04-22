from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SYMBOL_CLUSTERS: dict[str, set[str]] = {
    "majors": {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"},
    "jpy_cross": {"EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CHFJPY", "CADJPY"},
    "metals": {"XAUUSD", "XAGUSD"},
    "aud_nzd": {"AUDNZD", "EURAUD", "EURNZD", "GBPAUD", "GBPNZD"},
}


@dataclass(frozen=True)
class ProbabilityFallbackResult:
    status: Literal["CONDITIONAL", "INSUFFICIENT"]
    source: str
    trade_returns: list[float]
    confidence_penalty: float
    cluster_name: str | None
    note: str
    sample_count: int


class ProbabilityClusterFallback:
    MIN_CLUSTER_SAMPLES = 30
    MIN_OWN_SAMPLES_PREFERRED = 30
    CONFIDENCE_PENALTY = 0.10

    def derive(
        self,
        *,
        symbol: str,
        own_history: list[float],
        cluster_pool: dict[str, list[float]] | None,
    ) -> ProbabilityFallbackResult:
        own_count = len(own_history)
        if own_count >= self.MIN_OWN_SAMPLES_PREFERRED:
            return ProbabilityFallbackResult(
                status="INSUFFICIENT",
                source="trade_history",
                trade_returns=[float(value) for value in own_history],
                confidence_penalty=0.0,
                cluster_name=None,
                note=f"own_history_sufficient_{own_count}/{self.MIN_OWN_SAMPLES_PREFERRED}",
                sample_count=own_count,
            )

        cluster_name = self.resolve_cluster(symbol)
        cluster_history = list((cluster_pool or {}).get(cluster_name or "", []))
        cluster_count = len(cluster_history)
        if cluster_name and cluster_count >= self.MIN_CLUSTER_SAMPLES:
            return ProbabilityFallbackResult(
                status="CONDITIONAL",
                source=f"cluster:{cluster_name}",
                trade_returns=[float(value) for value in cluster_history],
                confidence_penalty=self.CONFIDENCE_PENALTY,
                cluster_name=cluster_name,
                note=(f"cluster_fallback_{own_count}/{self.MIN_OWN_SAMPLES_PREFERRED}:{cluster_name}:{cluster_count}"),
                sample_count=cluster_count,
            )

        return ProbabilityFallbackResult(
            status="INSUFFICIENT",
            source="none",
            trade_returns=[],
            confidence_penalty=0.0,
            cluster_name=cluster_name,
            note=(
                f"insufficient_data_{own_count}/{self.MIN_OWN_SAMPLES_PREFERRED}"
                + (
                    f":cluster_{cluster_name}_{cluster_count}/{self.MIN_CLUSTER_SAMPLES}"
                    if cluster_name
                    else ":cluster_unknown"
                )
            ),
            sample_count=cluster_count,
        )

    @staticmethod
    def resolve_cluster(symbol: str) -> str | None:
        normalized = str(symbol).upper().strip()
        for cluster_name, members in SYMBOL_CLUSTERS.items():
            if normalized in members:
                return cluster_name
        return None


__all__ = [
    "ProbabilityClusterFallback",
    "ProbabilityFallbackResult",
    "SYMBOL_CLUSTERS",
]
