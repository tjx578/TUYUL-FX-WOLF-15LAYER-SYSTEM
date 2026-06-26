from __future__ import annotations

from analysis.signal_promotion_score import score_signal_promotion


def test_signal_promotion_score_can_mark_advisory_candidate():
    score = score_signal_promotion(
        candidate={
            "symbol": "USDCAD",
            "direction": "BUY",
            "events": 20,
            "effective_ticks": 20,
            "duration_minutes": 6.0,
            "effective_density_per_minute": 3.3,
            "pressure_grade": "A",
        },
        allowed_quorum={"symbol": "USDCAD", "direction": "BUY", "streak": 3, "quorum_reached": True},
        microboost_summary={
            "count_total": 3,
            "latest": {
                "symbol": "USDCAD",
                "direction": "BUY",
                "direction_validation_status": "PASSED",
            },
        },
        market_context_validation={"direction_validated": True, "final_direction": "BUY"},
        pressure_cluster_summary={
            "by_symbol_direction": {
                "USDCAD:BUY": {
                    "cluster_pressure_score": 40,
                    "duplicate_penalty": 0.0,
                }
            }
        },
        outcome_memory_summary={
            "by_symbol_direction": {
                "USDCAD:BUY": {
                    "known_records": 3,
                    "success_rate": 1.0,
                    "failure_rate": 0.0,
                }
            }
        },
        regime_invalidation={"status": "VALID", "invalidated": False},
    )

    assert score.eligible is True
    assert score.status == "PROMOTION_CANDIDATE"
    assert score.advisory_only is True
    assert score.score >= 70


def test_signal_promotion_score_blocks_invalidated_regime():
    score = score_signal_promotion(
        candidate={"symbol": "AUDCAD", "direction": "BUY", "events": 20, "duration_minutes": 6},
        allowed_quorum={"symbol": "AUDCAD", "direction": "BUY", "streak": 3, "quorum_reached": True},
        market_context_validation={"direction_validated": False, "action": "BLOCK_BASKET_CONTRADICTION"},
        regime_invalidation={
            "status": "INVALIDATED",
            "invalidated": True,
            "blockers": ["BASKET_PAIR_BASKET_NOT_ALIGNED_BUY"],
        },
    )

    assert score.eligible is False
    assert score.status == "BLOCKED"
    assert "BLOCK_BASKET_CONTRADICTION" in score.blockers
    assert "BASKET_PAIR_BASKET_NOT_ALIGNED_BUY" in score.blockers
