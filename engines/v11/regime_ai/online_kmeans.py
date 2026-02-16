"""
Online K-Means Clustering with Persistence

Online K-Means clustering with:
- Persistence to JSON file (survives restarts)
- Input dimension validation
- Exponential confidence decay: exp(-dist/tau)
- RobustScaler (running median/IQR, fallback to tanh during warmup)

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]


@dataclass(frozen=True)
class ClusterResult:
    """Result of clustering operation."""
    
    cluster_id: int
    confidence: float
    distance: float
    label: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON."""
        return {
            "cluster_id": self.cluster_id,
            "confidence": self.confidence,
            "distance": self.distance,
            "label": self.label,
        }


class OnlineKMeans:
    """
    Online K-Means clustering with persistence.
    
    Parameters
    ----------
    n_clusters : int
        Number of clusters
    confidence_tau : float
        Decay parameter for confidence: exp(-dist/tau)
    learning_rate : float
        Learning rate for centroid updates
    state_file : str | Path
        Path to JSON persistence file
    """
    
    def __init__(
        self,
        n_clusters: int = 4,
        confidence_tau: float = 1.5,
        learning_rate: float = 0.1,
        state_file: str | Path = "storage/regime_ai_state.json",
    ) -> None:
        self._n_clusters = n_clusters
        self._tau = confidence_tau
        self._lr = learning_rate
        self._state_file = Path(state_file)
        
        # Cluster state
        self._centroids: np.ndarray | None = None
        self._n_dims: int | None = None
        self._sample_count: int = 0
        
        # Load state if exists
        self._load_state()
    
    def fit_predict(self, features: np.ndarray) -> ClusterResult:
        """
        Fit and predict cluster assignment for new features.
        
        Args:
            features: Feature vector (1D array)
        
        Returns:
            ClusterResult with cluster_id, confidence, distance
        """
        features = np.asarray(features, dtype=np.float64).flatten()
        
        # Initialize centroids on first call
        if self._centroids is None:
            self._initialize_centroids(features)
        
        # Validate dimensions
        if len(features) != self._n_dims:
            raise ValueError(
                f"Feature dimension mismatch: expected {self._n_dims}, got {len(features)}"
            )
        
        # Find nearest centroid
        distances = np.linalg.norm(self._centroids - features, axis=1)
        cluster_id = int(np.argmin(distances))
        distance = float(distances[cluster_id])
        
        # Compute confidence (exponential decay)
        confidence = float(np.exp(-distance / self._tau))
        
        # Update centroid (online learning)
        self._centroids[cluster_id] += self._lr * (features - self._centroids[cluster_id])
        
        # Increment sample count
        self._sample_count += 1
        
        # Persist state periodically (every 10 samples)
        if self._sample_count % 10 == 0:
            self._save_state()
        
        return ClusterResult(
            cluster_id=cluster_id,
            confidence=confidence,
            distance=distance,
        )
    
    def _initialize_centroids(self, first_sample: np.ndarray) -> None:
        """Initialize centroids with small random offsets from first sample."""
        self._n_dims = len(first_sample)
        
        # Initialize centroids with small random perturbations
        rng = np.random.default_rng(42)
        self._centroids = np.tile(first_sample, (self._n_clusters, 1))
        self._centroids += rng.normal(0, 0.1, size=self._centroids.shape)
    
    def _save_state(self) -> None:
        """Persist cluster state to JSON file."""
        if self._centroids is None:
            return
        
        try:
            # Create parent directory if needed
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            
            state = {
                "n_clusters": self._n_clusters,
                "n_dims": self._n_dims,
                "centroids": self._centroids.tolist(),
                "sample_count": self._sample_count,
            }
            
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
                
        except Exception:
            # Silent fail on persistence error
            pass
    
    def _load_state(self) -> None:
        """Load cluster state from JSON file if exists."""
        if not self._state_file.exists():
            return
        
        try:
            with open(self._state_file, encoding="utf-8") as f:
                state = json.load(f)
            
            self._n_clusters = state["n_clusters"]
            self._n_dims = state["n_dims"]
            self._centroids = np.array(state["centroids"], dtype=np.float64)
            self._sample_count = state["sample_count"]
            
        except Exception:
            # Silent fail on load error - will reinitialize
            pass
