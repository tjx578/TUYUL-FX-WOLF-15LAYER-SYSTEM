"""
Online K-Means Clustering for Regime Detection
Wolf-15 Layer Analysis System

Implements an incremental (online) K-Means clustering algorithm
for real-time market regime classification without requiring
full dataset retraining.

Pure analysis module (L1–L11). No execution side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClusterState:
    """State of a single cluster centroid."""

    centroid: np.ndarray
    count: int = 0
    label: str = ""
    inertia: float = 0.0


@dataclass
class KMeansState:
    """Full state of the online K-Means model."""

    clusters: list[ClusterState] = field(default_factory=lambda: list[ClusterState]())
    n_features: int = 0
    total_samples: int = 0
    initialized: bool = False


@dataclass
class ClusterResult:
    """Result of a single clustering prediction."""

    cluster_id: int
    confidence: float
    distance: float
    distances: list[float] = field(default_factory=lambda: [])


class OnlineKMeans:
    """
    Online (incremental) K-Means clustering for regime detection.

    Updates cluster centroids incrementally as new data arrives,
    avoiding the need to retrain on the full dataset each time.

    Analysis-only: produces cluster assignments and distances,
    no execution side-effects.
    """

    def __init__(
        self,
        n_clusters: int = 4,
        learning_rate: float = 0.1,
        min_learning_rate: float = 0.01,
        decay_factor: float = 0.999,
        random_seed: int | None = None,
        confidence_tau: float = 1.5,
        state_file: str | None = None,
    ) -> None:
        """
        Initialize online K-Means.

        Args:
            n_clusters: Number of clusters (regime types).
            learning_rate: Initial learning rate for centroid updates.
            min_learning_rate: Minimum learning rate after decay.
            decay_factor: Learning rate decay per sample.
            random_seed: Random seed for reproducibility.
            confidence_tau: Temperature parameter for confidence scoring.
            state_file: Optional path to persist/load model state (currently unused).
        """
        super().__init__()
        self.n_clusters = n_clusters
        self.learning_rate = learning_rate
        self.min_learning_rate = min_learning_rate
        self.decay_factor = decay_factor
        self.confidence_tau = confidence_tau
        self.state_file = state_file
        self.rng = np.random.default_rng(random_seed)

        self.state = KMeansState()
        self._current_lr = learning_rate

    def initialize(self, initial_data: np.ndarray) -> None:
        """
        Initialize centroids from a batch of initial data.

        Args:
            initial_data: 2D array of shape (n_samples, n_features).
        """
        if initial_data.ndim != 2:
            msg = f"Expected 2D array, got {initial_data.ndim}D"
            raise ValueError(msg)

        n_samples, n_features = initial_data.shape
        if n_samples < self.n_clusters:
            msg = f"Need at least {self.n_clusters} samples, got {n_samples}"
            raise ValueError(msg)

        # K-Means++ initialization
        indices = self._kmeans_plus_plus_init(initial_data)
        clusters: list[ClusterState] = []
        for i, idx in enumerate(indices):
            clusters.append(
                ClusterState(
                    centroid=initial_data[idx].copy(),
                    count=0,
                    label=f"regime_{i}",
                )
            )

        self.state = KMeansState(
            clusters=clusters,
            n_features=n_features,
            total_samples=0,
            initialized=True,
        )

        # Run a few batch iterations on initial data
        self._batch_update(initial_data, n_iterations=5)
        logger.info(
            "OnlineKMeans initialized with %d clusters, %d features",
            self.n_clusters,
            n_features,
        )

    def predict(self, features: np.ndarray) -> tuple[int, np.ndarray]:
        """
        Predict cluster assignment for a feature vector.

        Args:
            features: 1D feature vector.

        Returns:
            Tuple of (cluster_index, distances_to_all_centroids).
        """
        if not self.state.initialized:
            msg = "Model not initialized. Call initialize() first."
            raise RuntimeError(msg)

        features = np.asarray(features).flatten()
        distances = np.array([np.linalg.norm(features - c.centroid) for c in self.state.clusters])

        cluster_idx = int(np.argmin(distances))
        return cluster_idx, distances

    def fit_predict(self, features: np.ndarray) -> ClusterResult:
        """
        Predict cluster and update centroids; return a structured ClusterResult.

        Args:
            features: 1D feature vector.

        Returns:
            ClusterResult with cluster_id, confidence, and distance.
        """
        if not self.state.initialized:
            # Auto-initialize with single-sample warm start
            arr = np.asarray(features).flatten().reshape(1, -1)
            expanded = np.tile(arr, (self.n_clusters, 1)) + self.rng.normal(0, 1e-6, (self.n_clusters, arr.shape[1]))
            self.initialize(expanded)

        cluster_idx, distances = self.predict(features)
        dist_arr = np.asarray(distances)
        min_dist = float(dist_arr[cluster_idx])

        # Confidence via softmin over distances scaled by tau
        scaled = -dist_arr / max(self.confidence_tau, 1e-9)
        exp_s = np.exp(scaled - scaled.max())
        confidence = float(exp_s[cluster_idx] / exp_s.sum())

        # Update centroids online
        self.update(np.asarray(features).flatten())

        return ClusterResult(
            cluster_id=cluster_idx,
            confidence=confidence,
            distance=min_dist,
            distances=dist_arr.tolist(),
        )

    def update(self, features: np.ndarray) -> int:
        """
        Update centroids with a new sample and return assignment.

        Args:
            features: 1D feature vector.

        Returns:
            Assigned cluster index.
        """
        cluster_idx, _ = self.predict(features)

        # Update centroid with learning rate
        cluster = self.state.clusters[cluster_idx]
        cluster.centroid += self._current_lr * (features - cluster.centroid)
        cluster.count += 1

        # Decay learning rate
        self._current_lr = max(self._current_lr * self.decay_factor, self.min_learning_rate)
        self.state.total_samples += 1

        return cluster_idx

    def distance_to_regimes(self, features: np.ndarray) -> dict[str, float]:
        """
        Compute distance from features to each regime centroid.

        Args:
            features: 1D feature vector.

        Returns:
            Dictionary mapping regime labels to distances.
        """
        if not self.state.initialized:
            return {}

        features = np.asarray(features).flatten()
        return {c.label: float(np.linalg.norm(features - c.centroid)) for c in self.state.clusters}

    def _kmeans_plus_plus_init(self, data: np.ndarray) -> list[int]:
        """K-Means++ centroid initialization."""
        n_samples = data.shape[0]
        indices: list[int] = []

        # First centroid: random
        first_raw = cast(np.integer[Any], self.rng.integers(0, n_samples))
        first_idx = int(first_raw)
        indices.append(first_idx)

        for _ in range(1, self.n_clusters):
            # Compute distances to nearest chosen centroid
            distances = np.full(n_samples, np.inf)
            for idx in indices:
                d = np.linalg.norm(data - data[idx], axis=1)
                distances = np.minimum(distances, d)

            # Square distances for probability weighting
            dist_sq = distances**2
            total = dist_sq.sum()
            if total == 0:
                # All points are identical; pick randomly
                next_raw = cast(np.integer[Any], self.rng.integers(0, n_samples))
                next_idx = int(next_raw)
            else:
                probs = dist_sq / total
                cdf = np.cumsum(probs)
                r = float(self.rng.random())
                chosen_idx = int(np.searchsorted(cdf, r, side="right"))
                next_idx = min(chosen_idx, n_samples - 1)

            indices.append(next_idx)

        return indices

    def _batch_update(self, data: np.ndarray, n_iterations: int = 5) -> None:
        """Run batch K-Means iterations on data to refine initial centroids."""
        for _ in range(n_iterations):
            # Assign all points to nearest centroid
            assignments: list[int] = []
            for point in data:
                distances = [np.linalg.norm(point - c.centroid) for c in self.state.clusters]
                assignments.append(int(np.argmin(distances)))

            # Update centroids
            for k, cluster in enumerate(self.state.clusters):
                mask = [i for i, a in enumerate(assignments) if a == k]
                if mask:
                    cluster.centroid = np.mean(data[mask], axis=0)
                    cluster.count = len(mask)
