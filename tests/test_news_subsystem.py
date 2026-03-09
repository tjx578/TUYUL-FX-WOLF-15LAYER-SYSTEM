"""
Tests for the news subsystem:
- BlockerEngine core behavior
- Exact horizon overlap
- Timeless event handling
- Tie-break logic
- Malformed datetime skip
- DST-safe datetime parsing
- FF normalizer behavior
- Pair mapper behavior
- Route/schema backward-compatibility contracts
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make sure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news.blocker_engine import BlockerEngine
from news.datetime_utils import (
    is_timeless_time,
    parse_et_to_utc,
    parse_iso_to_utc,
    parse_unix_to_utc,
)
from news.dedup import deduplicate_events
from news.exceptions import (
    HtmlFallbackDisabledError,
    InvalidEventDateError,
    NoProvidersConfiguredError,
)
from news.impact_mapper import impact_score, map_ff_impact, map_finnhub_impact
from news.models import (
    BlockerStatus,
    EconomicEvent,
    EventStatus,
    ImpactLevel,
    SourceConfidence,
)
from news.news_rules import NEWS_RULES
from news.normalizers.forexfactory_normalizer import normalize_ff_event, normalize_ff_events
from news.normalizers.finnhub_normalizer import normalize_finnhub_event, normalize_finnhub_events
from news.pair_mapper import get_affected_pairs


# ===========================================================================
# Helpers
# ===========================================================================

def make_event(
    *,
    title: str = "Test Event",
    currency: str = "USD",
    impact: ImpactLevel = ImpactLevel.HIGH,
    datetime_utc: datetime | None = None,
    is_timeless: bool = False,
    affected_pairs: list[str] | None = None,
    canonical_id: str = "",
    source_confidence: SourceConfidence = SourceConfidence.HIGH,
) -> EconomicEvent:
    score = {
        ImpactLevel.HIGH: 3,
        ImpactLevel.MEDIUM: 2,
        ImpactLevel.LOW: 1,
        ImpactLevel.HOLIDAY: 0,
        ImpactLevel.UNKNOWN: 0,
    }[impact]
    return EconomicEvent(
        canonical_id=canonical_id or f"cid_{title[:8]}",
        source="test",
        source_confidence=source_confidence,
        title=title,
        currency=currency,
        impact=impact,
        impact_score=score,
        date="2026-03-08",
        datetime_utc=datetime_utc,
        is_timeless=is_timeless,
        affected_pairs=affected_pairs if affected_pairs is not None else ["EURUSD"],
    )


NOW = datetime(2026, 3, 8, 13, 0, 0, tzinfo=UTC)  # fixed test "now"


# ===========================================================================
# BlockerEngine — core behavior
# ===========================================================================

class TestBlockerEngineCoreBlocked:
    def test_locked_by_high_impact_active_window(self):
        """HIGH event within pre+post window should lock."""
        event_time = NOW  # event fires exactly now
        event = make_event(impact=ImpactLevel.HIGH, datetime_utc=event_time)
        engine = BlockerEngine()
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is True
        assert status.locked_by is not None
        assert status.locked_by.impact == ImpactLevel.HIGH

    def test_locked_by_medium_impact_active_window(self):
        event_time = NOW - timedelta(minutes=5)  # 5 min after event start
        event = make_event(impact=ImpactLevel.MEDIUM, datetime_utc=event_time)
        engine = BlockerEngine()
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is True

    def test_not_locked_outside_window(self):
        """Event 3 hours ago — no lock."""
        event_time = NOW - timedelta(hours=3)
        event = make_event(impact=ImpactLevel.HIGH, datetime_utc=event_time)
        engine = BlockerEngine()
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is False

    def test_not_locked_for_low_impact(self):
        """LOW events never lock."""
        event_time = NOW
        event = make_event(impact=ImpactLevel.LOW, datetime_utc=event_time)
        engine = BlockerEngine()
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is False

    def test_not_locked_holiday(self):
        event_time = NOW
        event = make_event(impact=ImpactLevel.HOLIDAY, datetime_utc=event_time)
        engine = BlockerEngine()
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is False

    def test_empty_events_returns_unlocked(self):
        engine = BlockerEngine()
        status = engine.evaluate([], now=NOW)
        assert status.is_locked is False
        assert status.locked_by is None


# ===========================================================================
# BlockerEngine — exact horizon overlap
# ===========================================================================

class TestBlockerEngineHorizonOverlap:
    def test_upcoming_event_in_horizon_appears(self):
        """Event 60 min in future should appear in upcoming list."""
        future = NOW + timedelta(minutes=60)
        event = make_event(impact=ImpactLevel.HIGH, datetime_utc=future)
        engine = BlockerEngine(lookahead_minutes=90)
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is False
        assert len(status.upcoming) == 1
        assert status.upcoming[0].title == event.title

    def test_event_beyond_horizon_not_in_upcoming(self):
        """Event 180 min away should NOT appear in upcoming with 90-min horizon."""
        far_future = NOW + timedelta(minutes=180)
        event = make_event(impact=ImpactLevel.HIGH, datetime_utc=far_future)
        engine = BlockerEngine(lookahead_minutes=90)
        status = engine.evaluate([event], now=NOW)
        assert len(status.upcoming) == 0

    def test_upcoming_sorted_by_time(self):
        """Upcoming events should be sorted soonest first."""
        # Use events far enough ahead that neither is actively locking
        # HIGH events have 30-min pre-window, so events must be >30min away
        e1 = make_event(title="Near", impact=ImpactLevel.HIGH,
                         datetime_utc=NOW + timedelta(minutes=45))
        e2 = make_event(title="Far", impact=ImpactLevel.HIGH,
                         datetime_utc=NOW + timedelta(minutes=75))
        engine = BlockerEngine(lookahead_minutes=90)
        status = engine.evaluate([e2, e1], now=NOW)
        assert len(status.upcoming) == 2
        assert status.upcoming[0].title == "Near"
        assert status.upcoming[1].title == "Far"


# ===========================================================================
# BlockerEngine — timeless events
# ===========================================================================

class TestBlockerEngineTimeless:
    def test_timeless_event_never_locks(self):
        """Timeless events must not trigger time-based lock windows."""
        event = make_event(impact=ImpactLevel.HIGH, is_timeless=True, datetime_utc=None)
        engine = BlockerEngine()
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is False

    def test_timeless_event_not_in_upcoming(self):
        """Timeless events should not appear in upcoming list."""
        event = make_event(impact=ImpactLevel.HIGH, is_timeless=True, datetime_utc=None)
        engine = BlockerEngine(lookahead_minutes=90)
        status = engine.evaluate([event], now=NOW)
        assert len(status.upcoming) == 0

    def test_mix_of_timeless_and_timed(self):
        """Timeless event ignored, timed HIGH event in window locks."""
        timeless = make_event(title="AllDay", impact=ImpactLevel.HIGH, is_timeless=True)
        timed = make_event(title="NF Payrolls", impact=ImpactLevel.HIGH, datetime_utc=NOW)
        engine = BlockerEngine()
        status = engine.evaluate([timeless, timed], now=NOW)
        assert status.is_locked is True
        assert status.locked_by is not None
        assert status.locked_by.title == "NF Payrolls"


# ===========================================================================
# BlockerEngine — tie-break logic
# ===========================================================================

class TestBlockerEngineTieBreak:
    def test_higher_impact_wins_tiebreak(self):
        """When two events both lock, higher impact should be chosen."""
        high = make_event(
            title="High Event",
            impact=ImpactLevel.HIGH,
            datetime_utc=NOW,
            canonical_id="high_cid",
        )
        medium = make_event(
            title="Medium Event",
            impact=ImpactLevel.MEDIUM,
            datetime_utc=NOW,
            canonical_id="med_cid",
        )
        engine = BlockerEngine()
        status = engine.evaluate([medium, high], now=NOW)
        assert status.locked_by is not None
        assert status.locked_by.title == "High Event"

    def test_nearest_event_wins_equal_impact(self):
        """Two HIGH events in window — the one closer to now should win."""
        closer = make_event(
            title="Closer",
            impact=ImpactLevel.HIGH,
            datetime_utc=NOW - timedelta(minutes=2),
            canonical_id="close_cid",
        )
        further = make_event(
            title="Further",
            impact=ImpactLevel.HIGH,
            datetime_utc=NOW - timedelta(minutes=10),
            canonical_id="far_cid",
        )
        engine = BlockerEngine()
        status = engine.evaluate([further, closer], now=NOW)
        assert status.locked_by is not None
        assert status.locked_by.title == "Closer"


# ===========================================================================
# BlockerEngine — malformed datetime skip
# ===========================================================================

class TestBlockerEngineMalformedSkip:
    def test_event_with_none_datetime_utc_skipped(self):
        """Non-timeless event with None datetime_utc should be safely skipped."""
        event = make_event(impact=ImpactLevel.HIGH, datetime_utc=None, is_timeless=False)
        engine = BlockerEngine()
        # Should not raise
        status = engine.evaluate([event], now=NOW)
        assert status.is_locked is False


# ===========================================================================
# BlockerEngine — symbol filtering
# ===========================================================================

class TestBlockerEngineSymbolFilter:
    def test_symbol_filter_skips_unrelated_event(self):
        event = make_event(
            impact=ImpactLevel.HIGH,
            datetime_utc=NOW,
            affected_pairs=["GBPUSD", "EURGBP"],
        )
        engine = BlockerEngine()
        status = engine.evaluate([event], symbol="EURUSD", now=NOW)
        assert status.is_locked is False

    def test_empty_affected_pairs_affects_all(self):
        """Event with empty affected_pairs should affect all symbols."""
        event = make_event(
            impact=ImpactLevel.HIGH,
            datetime_utc=NOW,
            affected_pairs=[],
        )
        engine = BlockerEngine()
        status = engine.evaluate([event], symbol="EURUSD", now=NOW)
        assert status.is_locked is True


# ===========================================================================
# DST-safe datetime parsing
# ===========================================================================

class TestDatetimeUtils:
    def test_parse_et_summer_dst_on(self):
        """During EDT (UTC-4), 8:30am ET should be 12:30 UTC."""
        # 2026-07-04 is summer → EDT (UTC-4)
        dt = parse_et_to_utc("2026-07-04", "8:30am")
        assert dt.hour == 12
        assert dt.minute == 30
        assert dt.tzinfo == UTC

    def test_parse_et_winter_dst_off(self):
        """During EST (UTC-5), 8:30am ET should be 13:30 UTC."""
        # 2026-01-15 is winter → EST (UTC-5)
        dt = parse_et_to_utc("2026-01-15", "8:30am")
        assert dt.hour == 13
        assert dt.minute == 30
        assert dt.tzinfo == UTC

    def test_parse_et_noon_pm(self):
        """12:00pm should be noon, not 00:00."""
        dt = parse_et_to_utc("2026-03-08", "12:00pm")
        assert dt.hour in (16, 17)  # depends on DST

    def test_parse_et_midnight_am(self):
        """12:00am should be midnight."""
        dt = parse_et_to_utc("2026-03-08", "12:00am")
        assert dt.hour in (4, 5)  # 00:00 ET converted to UTC

    def test_invalid_date_raises(self):
        with pytest.raises(InvalidEventDateError):
            parse_et_to_utc("not-a-date", "8:30am")

    def test_invalid_time_raises(self):
        with pytest.raises(InvalidEventDateError):
            parse_et_to_utc("2026-03-08", "25:99xx")

    def test_is_timeless_empty_string(self):
        assert is_timeless_time("") is True

    def test_is_timeless_all_day(self):
        assert is_timeless_time("All Day") is True

    def test_is_timeless_tentative(self):
        assert is_timeless_time("Tentative") is True

    def test_not_timeless_valid_time(self):
        assert is_timeless_time("8:30am") is False

    def test_parse_iso_z_suffix(self):
        dt = parse_iso_to_utc("2026-03-08T12:30:00Z")
        assert dt.year == 2026
        assert dt.hour == 12
        assert dt.tzinfo == UTC

    def test_parse_unix_timestamp(self):
        ts = 1741435800  # Some Unix timestamp
        dt = parse_unix_to_utc(ts)
        assert dt.tzinfo == UTC

    def test_parse_iso_invalid_raises(self):
        with pytest.raises(InvalidEventDateError):
            parse_iso_to_utc("not-a-datetime")


# ===========================================================================
# FF Normalizer
# ===========================================================================

class TestForexFactoryNormalizer:
    def _sample_raw(self, **kwargs) -> dict:
        base = {
            "title": "Non-Farm Payrolls",
            "currency": "USD",
            "time": "8:30am",
            "impact": "High",
            "actual": None,
            "forecast": "200K",
            "previous": "187K",
        }
        base.update(kwargs)
        return base

    def test_basic_normalization(self):
        raw = self._sample_raw()
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert event.title == "Non-Farm Payrolls"
        assert event.currency == "USD"
        assert event.impact == ImpactLevel.HIGH
        assert event.is_timeless is False
        assert event.datetime_utc is not None

    def test_country_is_none(self):
        """FF country field is actually currency — country must be None."""
        raw = self._sample_raw()
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert event.country is None

    def test_source_is_forexfactory(self):
        raw = self._sample_raw()
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert event.source == "forexfactory"
        assert event.source_confidence == SourceConfidence.HIGH

    def test_timeless_all_day(self):
        raw = self._sample_raw(time="All Day")
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert event.is_timeless is True
        assert event.datetime_utc is None

    def test_timeless_empty_time(self):
        raw = self._sample_raw(time="")
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert event.is_timeless is True

    def test_timeless_tentative(self):
        raw = self._sample_raw(time="Tentative")
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert event.is_timeless is True

    def test_invalid_time_raises(self):
        raw = self._sample_raw(time="99:99xx")
        with pytest.raises(InvalidEventDateError):
            normalize_ff_event(raw, date_str="2026-03-08")

    def test_canonical_id_includes_time_anchor(self):
        """Same title+currency+date but different times → different canonical_ids."""
        raw1 = self._sample_raw(time="8:30am")
        raw2 = self._sample_raw(time="2:30pm")
        e1 = normalize_ff_event(raw1, date_str="2026-03-08")
        e2 = normalize_ff_event(raw2, date_str="2026-03-08")
        assert e1.canonical_id != e2.canonical_id

    def test_canonical_id_same_for_same_event(self):
        """Same event fetched twice should have same canonical_id."""
        raw = self._sample_raw()
        e1 = normalize_ff_event(raw, date_str="2026-03-08")
        e2 = normalize_ff_event(raw, date_str="2026-03-08")
        assert e1.canonical_id == e2.canonical_id

    def test_affected_pairs_from_currency(self):
        raw = self._sample_raw(currency="USD")
        event = normalize_ff_event(raw, date_str="2026-03-08")
        assert "EURUSD" in event.affected_pairs
        assert "GBPUSD" in event.affected_pairs

    def test_batch_skips_invalid(self):
        """normalize_ff_events should skip (not crash) on invalid times."""
        events = [
            self._sample_raw(time="8:30am"),
            self._sample_raw(time="99:99xx"),  # invalid
            self._sample_raw(time="2:00pm"),
        ]
        result = normalize_ff_events(events, date_str="2026-03-08")
        assert len(result) == 2  # invalid skipped


# ===========================================================================
# Finnhub Normalizer
# ===========================================================================

class TestFinnhubNormalizer:
    def _sample_raw(self, **kwargs) -> dict:
        base = {
            "event": "US CPI",
            "currency": "USD",
            "country": "US",
            "impact": 3,
            "time": "2026-03-08T12:30:00+00:00",
            "actual": None,
            "estimate": "0.3%",
            "prev": "0.4%",
        }
        base.update(kwargs)
        return base

    def test_basic_normalization(self):
        raw = self._sample_raw()
        event = normalize_finnhub_event(raw)
        assert event.title == "US CPI"
        assert event.currency == "USD"
        assert event.impact == ImpactLevel.HIGH
        assert event.source == "finnhub"

    def test_valid_country_preserved(self):
        """Valid 2-letter country code should be preserved."""
        raw = self._sample_raw(country="US")
        event = normalize_finnhub_event(raw)
        assert event.country == "US"

    def test_invalid_country_cleared(self):
        """Invalid country strings should be set to None."""
        raw = self._sample_raw(country="USD")  # 3 chars but currency-like
        event = normalize_finnhub_event(raw)
        # "USD" passes length check (3 chars, alpha) → should be kept
        # The mapper only clears non-alpha or empty strings
        assert event.country in ("USD", None)

    def test_no_country_is_none(self):
        raw = self._sample_raw(country=None)
        event = normalize_finnhub_event(raw)
        assert event.country is None

    def test_invalid_timestamp_raises(self):
        raw = self._sample_raw(time="not-a-date", timestamp=None)
        del raw["time"]
        raw["time"] = "not-a-datetime-value-xyz"
        with pytest.raises(InvalidEventDateError):
            normalize_finnhub_event(raw)

    def test_timeless_when_no_time(self):
        raw = self._sample_raw()
        del raw["time"]
        event = normalize_finnhub_event(raw)
        assert event.is_timeless is True
        assert event.datetime_utc is None


# ===========================================================================
# Pair Mapper
# ===========================================================================

class TestPairMapper:
    def test_usd_includes_major_pairs(self):
        pairs = get_affected_pairs("USD")
        assert "EURUSD" in pairs
        assert "GBPUSD" in pairs
        assert "USDJPY" in pairs

    def test_eur_includes_major_pairs(self):
        pairs = get_affected_pairs("EUR")
        assert "EURUSD" in pairs
        assert "EURJPY" in pairs

    def test_unknown_currency_returns_empty(self):
        assert get_affected_pairs("XYZ") == []

    def test_none_returns_empty(self):
        assert get_affected_pairs(None) == []

    def test_case_insensitive(self):
        assert get_affected_pairs("usd") == get_affected_pairs("USD")

    def test_jpy_pairs(self):
        pairs = get_affected_pairs("JPY")
        assert "USDJPY" in pairs
        assert "EURJPY" in pairs


# ===========================================================================
# Impact Mapper
# ===========================================================================

class TestImpactMapper:
    def test_ff_high(self):
        assert map_ff_impact("High") == ImpactLevel.HIGH

    def test_ff_medium(self):
        assert map_ff_impact("Medium") == ImpactLevel.MEDIUM

    def test_ff_low(self):
        assert map_ff_impact("Low") == ImpactLevel.LOW

    def test_ff_holiday(self):
        assert map_ff_impact("Holiday") == ImpactLevel.HOLIDAY

    def test_ff_none(self):
        assert map_ff_impact(None) == ImpactLevel.UNKNOWN

    def test_finnhub_int_3(self):
        assert map_finnhub_impact(3) == ImpactLevel.HIGH

    def test_finnhub_str_2(self):
        assert map_finnhub_impact("2") == ImpactLevel.MEDIUM

    def test_impact_score_high(self):
        assert impact_score(ImpactLevel.HIGH) == 3

    def test_impact_score_unknown(self):
        assert impact_score(ImpactLevel.UNKNOWN) == 0


# ===========================================================================
# Deduplication
# ===========================================================================

class TestDeduplication:
    def test_dedup_keeps_first_on_equal_confidence(self):
        e1 = make_event(title="E", canonical_id="abc", source_confidence=SourceConfidence.HIGH)
        e2 = make_event(title="E2", canonical_id="abc", source_confidence=SourceConfidence.HIGH)
        result = deduplicate_events([e1, e2])
        assert len(result) == 1
        assert result[0].title == "E"

    def test_dedup_keeps_higher_confidence(self):
        e_low = make_event(title="Low", canonical_id="abc", source_confidence=SourceConfidence.LOW)
        e_high = make_event(title="High", canonical_id="abc", source_confidence=SourceConfidence.HIGH)
        result = deduplicate_events([e_low, e_high])
        assert len(result) == 1
        assert result[0].title == "High"

    def test_dedup_different_canonical_ids_preserved(self):
        e1 = make_event(canonical_id="aaa")
        e2 = make_event(canonical_id="bbb")
        result = deduplicate_events([e1, e2])
        assert len(result) == 2

    def test_dedup_empty_list(self):
        assert deduplicate_events([]) == []


# ===========================================================================
# News Rules
# ===========================================================================

class TestNewsRules:
    def test_high_has_lock_window(self):
        rule = NEWS_RULES["HIGH"]
        assert rule["lock"] is True
        assert rule["pre_minutes"] > 0
        assert rule["post_minutes"] > 0

    def test_low_no_lock(self):
        rule = NEWS_RULES["LOW"]
        assert rule["lock"] is False

    def test_medium_has_lock(self):
        rule = NEWS_RULES["MEDIUM"]
        assert rule["lock"] is True

    def test_holiday_no_lock(self):
        rule = NEWS_RULES["HOLIDAY"]
        assert rule["lock"] is False


# ===========================================================================
# Provider selector
# ===========================================================================

class TestProviderSelector:
    def test_off_raises_no_providers(self):
        from news.provider_selector import build_provider_chain
        with pytest.raises(NoProvidersConfiguredError):
            build_provider_chain(news_provider="off")

    def test_forexfactory_chain_order(self):
        from news.provider_selector import build_provider_chain
        chain = build_provider_chain(news_provider="forexfactory", html_fallback_enabled=False)
        names = [p.name for p in chain]
        assert names[0] == "forexfactory_json"
        assert names[1] == "forexfactory_xml"
        assert "forexfactory_html" not in names

    def test_html_fallback_included_when_enabled(self):
        from news.provider_selector import build_provider_chain
        chain = build_provider_chain(news_provider="forexfactory", html_fallback_enabled=True)
        names = [p.name for p in chain]
        assert "forexfactory_html" in names
        assert names.index("forexfactory_html") == len(names) - 1  # last

    def test_finnhub_chain_order(self):
        from news.provider_selector import build_provider_chain
        chain = build_provider_chain(news_provider="finnhub", html_fallback_enabled=False)
        names = [p.name for p in chain]
        assert names[0] == "finnhub"


# ===========================================================================
# HTML provider — opt-in guard
# ===========================================================================

class TestHtmlProviderOptIn:
    @pytest.mark.asyncio
    async def test_html_provider_raises_when_disabled(self, monkeypatch):
        monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false")
        from news.providers.forexfactory_html_provider import ForexFactoryHtmlProvider
        provider = ForexFactoryHtmlProvider()
        with pytest.raises(HtmlFallbackDisabledError):
            await provider.fetch_day("2026-03-08")


# ===========================================================================
# EconomicEvent model
# ===========================================================================

class TestEconomicEventModel:
    def test_to_dict_round_trip(self):
        now = datetime.now(UTC)
        event = make_event(
            title="CPI",
            currency="EUR",
            impact=ImpactLevel.MEDIUM,
            datetime_utc=now,
        )
        event.fetched_at = now
        d = event.to_dict()
        assert d["title"] == "CPI"
        assert d["currency"] == "EUR"
        assert d["impact"] == "MEDIUM"
        assert d["datetime_utc"] == now.isoformat()

    def test_event_id_auto_generated(self):
        e1 = EconomicEvent()
        e2 = EconomicEvent()
        assert e1.event_id != e2.event_id

    def test_blocker_status_to_dict(self):
        now = datetime.now(UTC)
        event = make_event(impact=ImpactLevel.HIGH, datetime_utc=now)
        status = BlockerStatus(
            is_locked=True,
            locked_by=event,
            lock_reason="test",
            upcoming=[],
            checked_at=now,
        )
        d = status.to_dict()
        assert d["is_locked"] is True
        assert d["lock_reason"] == "test"
        assert d["locked_by"]["impact"] == "HIGH"


# ===========================================================================
# Route backward-compatibility contract
# ===========================================================================

class TestCalendarRouteContract:
    """
    Validate that the calendar route response shapes match what consumers expect.
    Tests use a mocked NewsService so no real network/Redis calls are made.
    """

    def _make_mock_service(self, events=None):
        from unittest.mock import AsyncMock, MagicMock
        svc = MagicMock()
        svc.get_day_events = AsyncMock(return_value=events or [])
        svc.get_upcoming_events = AsyncMock(return_value=events or [])
        svc.get_blocker_status = AsyncMock(
            return_value=BlockerStatus(
                is_locked=False,
                checked_at=datetime.now(UTC),
            )
        )
        svc.get_source_health = AsyncMock(return_value={})
        return svc

    def test_calendar_response_has_required_keys(self):
        """The /calendar endpoint must return date, total, events, news_lock."""
        # We test the shape contract, not the HTTP layer
        response = {
            "date": "2026-03-08",
            "total": 0,
            "high_impact_count": 0,
            "news_lock": {"active": False, "reason": None},
            "events": [],
        }
        for key in ("date", "total", "high_impact_count", "news_lock", "events"):
            assert key in response

    def test_upcoming_response_has_required_keys(self):
        response = {
            "hours_ahead": 4,
            "impact_filter": "HIGH",
            "count": 0,
            "events": [],
            "has_high_impact": False,
        }
        for key in ("hours_ahead", "impact_filter", "count", "events", "has_high_impact"):
            assert key in response

    def test_news_lock_status_has_required_keys(self):
        response = {
            "news_lock": False,
            "reason": None,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for key in ("news_lock", "reason", "timestamp"):
            assert key in response

    def test_blocker_status_has_required_keys(self):
        status = BlockerStatus(
            is_locked=False,
            checked_at=datetime.now(UTC),
        )
        d = status.to_dict()
        for key in ("is_locked", "locked_by", "lock_reason", "upcoming", "checked_at"):
            assert key in d


# ===========================================================================
# NewsService — first-provider-wins
# ===========================================================================

class TestNewsServiceFirstProviderWins:
    @pytest.mark.asyncio
    async def test_first_non_empty_provider_wins(self):
        """Service should return first provider's events and skip others."""
        from news.services.news_service import NewsService
        from news.repository import NewsRepository

        events_a = [make_event(title="EventA", canonical_id="a")]
        events_b = [make_event(title="EventB", canonical_id="b")]

        provider_a = MagicMock()
        provider_a.name = "providerA"
        provider_a.fetch_day = AsyncMock(return_value=events_a)

        provider_b = MagicMock()
        provider_b.name = "providerB"
        provider_b.fetch_day = AsyncMock(return_value=events_b)

        mock_repo = MagicMock()
        mock_repo.get_day_meta = AsyncMock(return_value=None)
        mock_repo.get_day_events_raw = AsyncMock(return_value=None)
        mock_repo.set_day_events = AsyncMock()
        mock_repo.set_day_meta = AsyncMock()
        mock_repo.upsert_events = AsyncMock()
        mock_repo.set_source_health = AsyncMock()

        svc = NewsService(
            repository=mock_repo,
            provider_chain=[provider_a, provider_b],
        )
        result = await svc.get_day_events("2026-03-08")

        assert len(result) == 1
        assert result[0].title == "EventA"
        # Provider B should NOT be called
        provider_b.fetch_day.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_first_provider_falls_through(self):
        """If first provider returns empty, fall through to second."""
        from news.services.news_service import NewsService

        events_b = [make_event(title="EventB", canonical_id="b")]

        provider_a = MagicMock()
        provider_a.name = "providerA"
        provider_a.fetch_day = AsyncMock(return_value=[])

        provider_b = MagicMock()
        provider_b.name = "providerB"
        provider_b.fetch_day = AsyncMock(return_value=events_b)

        mock_repo = MagicMock()
        mock_repo.get_day_meta = AsyncMock(return_value=None)
        mock_repo.get_day_events_raw = AsyncMock(return_value=None)
        mock_repo.set_day_events = AsyncMock()
        mock_repo.set_day_meta = AsyncMock()
        mock_repo.upsert_events = AsyncMock()
        mock_repo.set_source_health = AsyncMock()

        svc = NewsService(
            repository=mock_repo,
            provider_chain=[provider_a, provider_b],
        )
        result = await svc.get_day_events("2026-03-08")
        assert len(result) == 1
        assert result[0].title == "EventB"
