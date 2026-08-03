from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.frozen_quote_detector import FrozenQuoteDetector
from analysis.signal_decision_source_guard import convert_to_signal_pressure_state
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def test_pipeline_marks_advancing_but_unchanged_live_tick_as_frozen() -> None:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._frozen_quote_detector = FrozenQuoteDetector(
        frozen_after_seconds=120,
        min_unchanged_observations=3,
    )
    start = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)

    def lineage(at: datetime) -> dict[str, object]:
        return {
            "price": 1.155,
            "price_source": "LIVE_TICK_MID",
            "price_snapshot_time_utc": at.isoformat(),
            "price_age_seconds": 0.0,
            "price_freshness_status": "LIVE",
            "reference_price_is_live": True,
        }

    pipeline._decision_price_lineage_payload(lineage(start), symbol="EURUSD")
    pipeline._decision_price_lineage_payload(
        lineage(start + timedelta(seconds=60)),
        symbol="EURUSD",
    )
    frozen = pipeline._decision_price_lineage_payload(
        lineage(start + timedelta(seconds=120)),
        symbol="EURUSD",
    )

    assert frozen["quote_health_status"] == "PRICE_FROZEN"
    assert frozen["observed_price_status"] == "PRICE_FROZEN"
    assert frozen["reference_price_status"] == "PRICE_FROZEN"
    assert frozen["reference_price_is_live"] is False

    pressure = convert_to_signal_pressure_state(
        {
            "source_stage": "PRESSURE_BLOCK",
            "symbol": "EURUSD",
            "cluster_id": "EURUSD:FROZEN",
            "raw_direction": "BUY",
            **frozen,
        }
    )
    assert pressure["observed_price_status"] == "PRICE_FROZEN"
    assert pressure["reference_price_status"] == "PRICE_FROZEN"
