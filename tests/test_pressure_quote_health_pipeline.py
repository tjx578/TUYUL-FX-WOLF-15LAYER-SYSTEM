from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from analysis.frozen_quote_detector import FrozenQuoteAssessment, FrozenQuoteDetector, QuoteHealthStatus
from analysis.signal_decision_source_guard import convert_to_signal_pressure_state
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


class _FixedQuoteDetector:
    def __init__(self, status: QuoteHealthStatus, *, execution_blocked: bool) -> None:
        self.status: QuoteHealthStatus = status
        self.execution_blocked = execution_blocked

    def observe(self, *, observed_at: datetime, **_: object) -> FrozenQuoteAssessment:
        return FrozenQuoteAssessment(
            status=self.status,
            observed_at_utc=observed_at,
            unchanged_seconds=0.0,
            consecutive_unchanged=1,
            observation_count=1,
            warmup_elapsed_seconds=0.0,
            execution_blocked=self.execution_blocked,
            reason=f"TEST_{self.status}",
        )


def _lineage(*, freshness: str, reference_is_live: bool = False) -> dict[str, object]:
    at = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    return {
        "price": 1.155,
        "price_source": "LIVE_TICK_MID",
        "price_snapshot_time_utc": at.isoformat(),
        "price_age_seconds": 0.0,
        "price_freshness_status": freshness,
        "reference_price_is_live": reference_is_live,
    }


@pytest.mark.parametrize(
    (
        "feed_freshness",
        "quote_health",
        "quote_blocked",
        "feed_marks_live",
        "expected_reference_status",
        "expected_reference_is_live",
    ),
    [
        pytest.param("LIVE", "LIVE", False, True, "LIVE", True, id="fresh-healthy"),
        pytest.param(
            "LIVE",
            "PRICE_QUALITY_WARMING_UP",
            True,
            True,
            "PRICE_QUALITY_WARMING_UP",
            False,
            id="fresh-warmup",
        ),
        pytest.param("STALE_PRESERVED", "LIVE", False, False, "STALE", False, id="stale-healthy"),
        pytest.param(
            "STALE_PRESERVED",
            "PRICE_QUALITY_WARMING_UP",
            True,
            False,
            "STALE",
            False,
            id="stale-warmup",
        ),
        pytest.param(
            "STALE_PRESERVED",
            "PRICE_FROZEN",
            True,
            False,
            "PRICE_FROZEN",
            False,
            id="stale-frozen",
        ),
        pytest.param("NO_PRODUCER", "LIVE", False, False, "STALE", False, id="missing-healthy"),
        pytest.param(
            "DEGRADED_BUT_REFRESHING",
            "LIVE",
            False,
            False,
            "AVAILABLE",
            False,
            id="available-non-live-healthy",
        ),
    ],
)
def test_pipeline_keeps_feed_freshness_separate_from_quote_health(
    feed_freshness: str,
    quote_health: QuoteHealthStatus,
    quote_blocked: bool,
    feed_marks_live: bool,
    expected_reference_status: str,
    expected_reference_is_live: bool,
) -> None:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    cast(Any, pipeline)._frozen_quote_detector = _FixedQuoteDetector(
        quote_health,
        execution_blocked=quote_blocked,
    )

    payload = pipeline._decision_price_lineage_payload(
        _lineage(freshness=feed_freshness, reference_is_live=feed_marks_live),
        symbol="EURUSD",
    )

    assert payload["price_freshness_status"] == feed_freshness
    assert payload["quote_health_status"] == quote_health
    assert payload["reference_price_status"] == expected_reference_status
    assert payload["reference_price_is_live"] is expected_reference_is_live
    if feed_freshness == "STALE_PRESERVED":
        assert payload["reference_price_status"] not in {"LIVE", "AVAILABLE"}
    if quote_blocked:
        assert payload["reference_price_is_live"] is False


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
    assert frozen["price_freshness_status"] == "LIVE"
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


def test_pipeline_blocks_structural_authority_during_restart_quote_warmup() -> None:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._frozen_quote_detector = FrozenQuoteDetector(
        warmup_seconds=30,
        min_warmup_observations=3,
    )
    at = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)

    warming = pipeline._decision_price_lineage_payload(
        {
            "price": 1.155,
            "price_source": "LIVE_TICK_MID",
            "price_snapshot_time_utc": at.isoformat(),
            "price_age_seconds": 0.0,
            "price_freshness_status": "LIVE",
            "reference_price_is_live": True,
        },
        symbol="EURUSD",
    )

    assert warming["quote_health_status"] == "PRICE_QUALITY_WARMING_UP"
    assert warming["price_freshness_status"] == "LIVE"
    assert warming["quote_health_execution_blocked"] is True
    assert warming["observed_price_status"] == "PRICE_QUALITY_WARMING_UP"
    assert warming["reference_price_status"] == "PRICE_QUALITY_WARMING_UP"
    assert warming["reference_price_is_live"] is False
