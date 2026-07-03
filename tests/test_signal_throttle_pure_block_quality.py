from __future__ import annotations

from datetime import UTC, datetime

from analysis.signal_throttle_log_analyzer import PressureBlock
from analysis.signal_throttle_pure_block_quality import score_pure_pressure_block


def _block(
    *,
    duration_seconds: float,
    events: int,
    density: float,
    max_gap_seconds: float,
) -> PressureBlock:
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    return PressureBlock(
        symbol="USDJPY",
        start=start,
        end=start,
        events=events,
        duration_seconds=duration_seconds,
        density_per_minute=density,
        max_gap_seconds=max_gap_seconds,
        direction="BUY",
        effective_ticks=events,
        effective_density_per_minute=density,
    )


def test_pure_pressure_large_gap_degrades_heat_not_validity():
    quality = score_pure_pressure_block(
        _block(duration_seconds=900.0, events=24, density=1.6, max_gap_seconds=540.0)
    ).to_dict()

    assert quality["gap_policy"] == "QUALITY_ONLY"
    assert quality["split_rule"] == "PAIR_ROTATION_ONLY"
    assert quality["gap_split_applied"] is False
    assert quality["valid_for_execution"] is False
    assert quality["execution_tier"] == "WAIT"
    assert quality["pure_pressure_score"] > quality["heat_score"]
    assert "GAP_DEGRADES_HEAT_ONLY" in quality["reason"]


def test_short_dense_block_scores_hot_but_still_advisory_only():
    quality = score_pure_pressure_block(
        _block(duration_seconds=60.0, events=18, density=18.0, max_gap_seconds=5.0)
    ).to_dict()

    assert quality["heat_score"] >= 75.0
    assert quality["advisory_only"] is True
    assert quality["valid_for_execution"] is False
