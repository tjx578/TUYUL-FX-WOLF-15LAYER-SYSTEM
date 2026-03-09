import pytest

from news.exceptions import NewsNormalizationError
from news.normalizers.forexfactory_normalizer import normalize_event, normalize_events


def test_normalize_event_basic_contract() -> None:
    event = normalize_event(
        {
            "title": "CPI m/m",
            "currency": "USD",
            "time": "8:30am",
            "impact": "High",
        },
        date_str="2026-03-08",
    )

    assert event.currency == "USD"
    assert event.impact.value == "HIGH"
    assert event.canonical_id


def test_normalize_event_raises_for_invalid_datetime() -> None:
    with pytest.raises(NewsNormalizationError):
        normalize_event(
            {
                "title": "Bad Time",
                "currency": "USD",
                "time": "25:99pm",
                "impact": "High",
            },
            date_str="2026-03-08",
        )


def test_normalize_events_skips_invalid_event() -> None:
    events = normalize_events(
        [
            {
                "title": "Valid",
                "currency": "USD",
                "time": "8:30am",
                "impact": "High",
            },
            {
                "title": "Invalid",
                "currency": "USD",
                "time": "xx",
                "impact": "High",
            },
        ],
        date_str="2026-03-08",
    )

    assert len(events) == 1
    assert events[0].title == "Valid"
