"""
Drift Monitor — detect feature distribution shift vs. captured baseline.

Tracks statistical divergence (KL-divergence + Wasserstein distance) between
current inference features and a stored baseline snapshot.  When drift
exceeds thresholds, the monitor emits warnings that governance can use to
freeze rollouts or downgrade execution confidence.

Integrates with:
  - LiveContextBus.inference_snapshot() for real-time features
  - Redis for baseline persistence
  - Prometheus metrics (core.metrics) for alerting

Authority: Governance / advisory.
  - Does NOT override L12 verdict.
  - CAN trigger rollout freeze via RolloutController.
  - CAN add drift_warning to pipeline synthesis.
"""

from __future__ import annotations

import contextlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

# ── Redis key constants ───────────────────────────────────────────────────────
_KEY_PREFIX = "wolf15:governance:drift"
_BASELINE_KEY = f"{_KEY_PREFIX}:baseline"
_LATEST_KEY = f"{_KEY_PREFIX}:latest"
_ARTIFACT_DIR = Path("storage/snapshots/governance/drift")


@dataclass(frozen=True)
class DriftThresholds:
    """Configurable drift alert thresholds."""

    kl_warning: float = 0.10
    kl_critical: float = 0.20
    wasserstein_warning: float = 0.15
    wasserstein_critical: float = 0.30
    # Max fraction of features drifting before system-level alert
    feature_drift_fraction_warning: float = 0.30
    feature_drift_fraction_critical: float = 0.50


@dataclass(frozen=True)
class FeatureDriftResult:
    """Drift analysis for a single feature."""

    feature: str
    baseline_mean: float
    current_mean: float
    baseline_std: float
    current_std: float
    kl_divergence: float
    wasserstein_distance: float
    drifted: bool


@dataclass(frozen=True)
class DriftReport:
    """Complete drift assessment across all tracked features."""

    timestamp: str
    total_features: int
    drifted_features: int
    drift_fraction: float
    severity: str  # "STABLE" | "WARNING" | "CRITICAL"
    per_feature: tuple[FeatureDriftResult, ...]
    aggregate_kl: float
    aggregate_wasserstein: float
    should_freeze: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_features": self.total_features,
            "drifted_features": self.drifted_features,
            "drift_fraction": self.drift_fraction,
            "severity": self.severity,
            "per_feature": [asdict(f) for f in self.per_feature],
            "aggregate_kl": self.aggregate_kl,
            "aggregate_wasserstein": self.aggregate_wasserstein,
            "should_freeze": self.should_freeze,
        }


# ── Math helpers (no scipy dependency) ────────────────────────────────────────


def _safe_kl_divergence(mean_p: float, std_p: float, mean_q: float, std_q: float) -> float:
    """
    KL(P || Q) for two univariate Gaussians.

    Returns 0.0 on degenerate inputs (zero variance).
    """
    if std_p <= 1e-12 or std_q <= 1e-12:
        return 0.0
    var_p = std_p**2
    var_q = std_q**2
    return math.log(std_q / std_p) + (var_p + (mean_p - mean_q) ** 2) / (2 * var_q) - 0.5


def _wasserstein_1d(mean_p: float, std_p: float, mean_q: float, std_q: float) -> float:
    """
    1-Wasserstein distance between two univariate Gaussians.

    W_1 = |μ_p - μ_q| + |σ_p - σ_q| * sqrt(2/π)
    """
    return abs(mean_p - mean_q) + abs(std_p - std_q) * math.sqrt(2.0 / math.pi)


# ── Feature extraction from inference snapshot ────────────────────────────────

# Features we extract for drift tracking.
# Each key maps to a callable that extracts a float from the inference snapshot.
_FEATURE_EXTRACTORS: dict[str, Any] = {
    "regime_state_macro": lambda snap: float(snap.get("regime_state", {}).get("regime", 0)),
    "regime_state_vix": lambda snap: float(snap.get("regime_state", {}).get("vix", 0)),
    "volatility_regime_ordinal": lambda snap: {"LOW": 0.0, "NORMAL": 1.0, "HIGH": 2.0, "EXTREME": 3.0}.get(
        snap.get("volatility_regime", "NORMAL"), 1.0
    ),
    "session_multiplier": lambda snap: float(snap.get("session_state", {}).get("multiplier", 1.0)),
    "news_pressure_impact": lambda snap: float(snap.get("news_pressure_vector", {}).get("impact", 0.0)),
    "signal_stack_depth": lambda snap: float(len(snap.get("signal_stack", []))),
}


def extract_features(inference_snapshot: dict[str, Any]) -> dict[str, float]:
    """Extract trackable numeric features from an inference snapshot."""
    result: dict[str, float] = {}
    for name, extractor in _FEATURE_EXTRACTORS.items():
        try:
            result[name] = float(extractor(inference_snapshot))
        except (TypeError, ValueError, KeyError):
            result[name] = 0.0
    return result


# ── Baseline: running mean/std tracker ────────────────────────────────────────


@dataclass
class FeatureBaseline:
    """Welford's online mean/variance tracker for a single feature."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0  # sum of squared deviations

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        return math.sqrt(self.m2 / (self.count - 1))

    def update(self, value: float) -> None:
        """Welford's one-pass update."""
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    def to_dict(self) -> dict[str, float | int]:
        return {"count": self.count, "mean": self.mean, "m2": self.m2, "std": self.std}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> FeatureBaseline:
        return FeatureBaseline(
            count=int(d.get("count", 0)),
            mean=float(d.get("mean", 0.0)),
            m2=float(d.get("m2", 0.0)),
        )


# ── Main monitor ──────────────────────────────────────────────────────────────


class DriftMonitor:
    """
    Stateful drift monitor comparing live features against captured baseline.

    Usage:
        monitor = DriftMonitor(redis_client=redis)
        monitor.capture_baseline(inference_snapshot)  # during stable period
        ...
        report = monitor.evaluate(inference_snapshot)  # during live
        if report.should_freeze:
            rollout_controller.freeze(...)
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        thresholds: DriftThresholds | None = None,
        window_size: int = 100,
    ) -> None:
        self._redis = redis_client
        self._thresholds = thresholds or DriftThresholds()
        self._window_size = window_size

        # Baseline: captured during stable period
        self._baseline: dict[str, FeatureBaseline] = {}
        # Current window: rolling tracker for live
        self._current: dict[str, FeatureBaseline] = {}
        self._sample_count = 0

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        self._load_baseline()

    # ── Baseline management ───────────────────────────────────────────────

    def capture_baseline(self, inference_snapshot: dict[str, Any]) -> None:
        """Add an inference snapshot to the baseline distribution."""
        features = extract_features(inference_snapshot)
        for name, value in features.items():
            if name not in self._baseline:
                self._baseline[name] = FeatureBaseline()
            self._baseline[name].update(value)

    def save_baseline(self) -> None:
        """Persist current baseline to Redis + artifact."""
        payload = {k: v.to_dict() for k, v in self._baseline.items()}
        raw = json.dumps(payload, default=str)

        if self._redis is not None:
            try:
                self._redis.set(_BASELINE_KEY, raw, ex=86400 * 90)
            except Exception as exc:
                logger.warning("DriftMonitor: Redis baseline save failed: {}", exc)

        artifact = _ARTIFACT_DIR / "baseline.json"
        artifact.write_text(raw, encoding="utf-8")
        logger.info(
            "DriftMonitor: baseline saved ({} features, {} samples)",
            len(self._baseline),
            max((b.count for b in self._baseline.values()), default=0),
        )

    def _load_baseline(self) -> None:
        """Load baseline from Redis or artifact."""
        raw_str: str | None = None
        if self._redis is not None:
            with contextlib.suppress(Exception):
                raw_str = self._redis.get(_BASELINE_KEY)

        if raw_str is None:
            artifact = _ARTIFACT_DIR / "baseline.json"
            if artifact.exists():
                raw_str = artifact.read_text(encoding="utf-8")

        if raw_str is not None:
            try:
                data = json.loads(raw_str)
                self._baseline = {k: FeatureBaseline.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("DriftMonitor: baseline load failed: {}", exc)

    def has_baseline(self) -> bool:
        return bool(self._baseline) and any(b.count >= 10 for b in self._baseline.values())

    # ── Live evaluation ───────────────────────────────────────────────────

    def observe(self, inference_snapshot: dict[str, Any]) -> None:
        """Add a live observation to the current window."""
        features = extract_features(inference_snapshot)
        for name, value in features.items():
            if name not in self._current:
                self._current[name] = FeatureBaseline()
            self._current[name].update(value)

        self._sample_count += 1

        # Rolling window: reset after window_size samples
        if self._sample_count > self._window_size:
            self._current = {}
            self._sample_count = 0

    def evaluate(self, inference_snapshot: dict[str, Any] | None = None) -> DriftReport:
        """
        Evaluate drift between baseline and current window.

        If inference_snapshot is provided, it's added to current window first.
        """
        if inference_snapshot is not None:
            self.observe(inference_snapshot)

        if not self.has_baseline():
            return DriftReport(
                timestamp=datetime.now(UTC).isoformat(),
                total_features=0,
                drifted_features=0,
                drift_fraction=0.0,
                severity="STABLE",
                per_feature=(),
                aggregate_kl=0.0,
                aggregate_wasserstein=0.0,
                should_freeze=False,
            )

        t = self._thresholds
        per_feature: list[FeatureDriftResult] = []
        total_kl = 0.0
        total_w = 0.0
        drifted = 0

        for name, baseline in self._baseline.items():
            current = self._current.get(name)
            if current is None or current.count < 5:
                continue

            kl = _safe_kl_divergence(baseline.mean, baseline.std, current.mean, current.std)
            w = _wasserstein_1d(baseline.mean, baseline.std, current.mean, current.std)

            is_drifted = kl > t.kl_warning or w > t.wasserstein_warning
            if is_drifted:
                drifted += 1

            total_kl += kl
            total_w += w

            per_feature.append(
                FeatureDriftResult(
                    feature=name,
                    baseline_mean=baseline.mean,
                    current_mean=current.mean,
                    baseline_std=baseline.std,
                    current_std=current.std,
                    kl_divergence=kl,
                    wasserstein_distance=w,
                    drifted=is_drifted,
                )
            )

        total = len(per_feature) or 1
        fraction = drifted / total
        avg_kl = total_kl / total
        avg_w = total_w / total

        # Determine severity
        if fraction >= t.feature_drift_fraction_critical or avg_kl >= t.kl_critical or avg_w >= t.wasserstein_critical:
            severity = "CRITICAL"
            should_freeze = True
        elif fraction >= t.feature_drift_fraction_warning or avg_kl >= t.kl_warning or avg_w >= t.wasserstein_warning:
            severity = "WARNING"
            should_freeze = False
        else:
            severity = "STABLE"
            should_freeze = False

        report = DriftReport(
            timestamp=datetime.now(UTC).isoformat(),
            total_features=total,
            drifted_features=drifted,
            drift_fraction=round(fraction, 4),
            severity=severity,
            per_feature=tuple(per_feature),
            aggregate_kl=round(avg_kl, 6),
            aggregate_wasserstein=round(avg_w, 6),
            should_freeze=should_freeze,
        )

        self._persist_report(report)
        return report

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist_report(self, report: DriftReport) -> None:
        payload = json.dumps(report.to_dict(), default=str)
        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.set(_LATEST_KEY, payload, ex=3600)

        artifact = _ARTIFACT_DIR / "drift_latest.json"
        artifact.write_text(payload, encoding="utf-8")
