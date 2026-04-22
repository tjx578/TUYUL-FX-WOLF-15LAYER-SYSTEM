from __future__ import annotations

from analysis.probability_cluster_fallback import ProbabilityClusterFallback


def test_cluster_fallback_returns_conditional_when_cluster_has_enough_samples() -> None:
    fallback = ProbabilityClusterFallback()

    result = fallback.derive(
        symbol="EURUSD",
        own_history=[1.0, -0.5, 2.0],
        cluster_pool={"majors": [0.02, -0.01, 0.015, -0.005] * 10},
    )

    assert result.status == "CONDITIONAL"
    assert result.source == "cluster:majors"
    assert result.cluster_name == "majors"
    assert result.sample_count == 40


def test_cluster_fallback_returns_insufficient_when_cluster_pool_is_missing() -> None:
    fallback = ProbabilityClusterFallback()

    result = fallback.derive(
        symbol="EURUSD",
        own_history=[1.0, -0.5, 2.0],
        cluster_pool=None,
    )

    assert result.status == "INSUFFICIENT"
    assert result.source == "none"
    assert result.trade_returns == []
    assert result.cluster_name == "majors"


def test_cluster_fallback_reports_trade_history_when_own_samples_are_sufficient() -> None:
    fallback = ProbabilityClusterFallback()

    result = fallback.derive(
        symbol="EURUSD",
        own_history=[0.01] * 30,
        cluster_pool={"majors": [0.02, -0.01] * 20},
    )

    assert result.status == "INSUFFICIENT"
    assert result.source == "trade_history"
    assert result.sample_count == 30
    assert result.trade_returns == [0.01] * 30


def test_cluster_fallback_resolves_clusters_case_insensitively() -> None:
    fallback = ProbabilityClusterFallback()

    assert fallback.resolve_cluster(" eurusd ") == "majors"
