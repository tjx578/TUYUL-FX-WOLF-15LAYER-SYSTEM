"""
Regime Service - Glue Layer for Regime AI

RegimeService glue layer with config-driven label mapping and strategy routing.

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines.v11.config import get_v11
from engines.v11.regime_ai.feature_extractor import FeatureExtractor
from engines.v11.regime_ai.online_kmeans import ClusterResult, OnlineKMeans


@dataclass(frozen=True)
class RegimeResult:
    """Result of regime classification."""

    label: str
    confidence: float
    cluster_id: int
    distance: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON."""
        return {
            "label": self.label,
            "confidence": self.confidence,
            "cluster_id": self.cluster_id,
            "distance": self.distance,
        }


class RegimeService:
    """
    Regime classification service.

    Combines feature extraction, online clustering, and label mapping.
    """

    def __init__(self) -> None:
        # Load config
        n_clusters = get_v11("regime_ai.n_clusters", 4)
        confidence_tau = get_v11("regime_ai.confidence_tau", 1.5)
        learning_rate = get_v11("regime_ai.learning_rate", 0.1)
        state_file = get_v11("regime_ai.state_file", "storage/regime_ai_state.json")
        feature_window = get_v11("regime_ai.feature_window", 50)

        # Initialize components
        self._feature_extractor = FeatureExtractor(window=feature_window)
        self._kmeans = OnlineKMeans(
            n_clusters=n_clusters,
            confidence_tau=confidence_tau,
            learning_rate=learning_rate,
            state_file=state_file,
        )

        # Load label mapping
        self._label_mapping = get_v11(
            "regime_ai.label_mapping",
            {0: "TRENDING", 1: "RANGING", 2: "EXPANSION", 3: "SHOCK"}
        )

    def classify(self, candles: list[dict[str, Any]]) -> RegimeResult | None:
        """
        Classify market regime from candle history.

        Args:
            candles: List of OHLCV candles

        Returns:
            RegimeResult or None if insufficient data
        """
        # Extract features
        features = self._feature_extractor.extract(candles)

        if features is None:
            return None

        # Cluster
        cluster_result = self._kmeans.fit_predict(features)

        # Map to label
        label = self._label_mapping.get(cluster_result.cluster_id, "UNKNOWN")

        return RegimeResult(
            label=label,
            confidence=cluster_result.confidence,
            cluster_id=cluster_result.cluster_id,
            distance=cluster_result.distance,
        )
