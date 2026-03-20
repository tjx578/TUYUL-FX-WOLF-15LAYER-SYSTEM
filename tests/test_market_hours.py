"""Tests for utils.market_hours — forex market open/close and weekend gap calc."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from utils.market_hours import is_forex_market_open, weekend_gap_seconds

# ── is_forex_market_open ────────────────────────────────────────


class TestIsForexMarketOpen:
    @pytest.mark.parametrize(
        "dow,hour,expected",
        [
            (0, 0, True),  # Mon 00:00
            (0, 12, True),  # Mon 12:00
            (1, 23, True),  # Tue 23:00
            (3, 5, True),  # Thu 05:00
            (4, 0, True),  # Fri 00:00
            (4, 21, True),  # Fri 21:59
            (4, 22, False),  # Fri 22:00 — closed
            (4, 23, False),  # Fri 23:00 — closed
            (5, 0, False),  # Sat 00:00
            (5, 12, False),  # Sat 12:00
            (5, 23, False),  # Sat 23:00
            (6, 0, False),  # Sun 00:00
            (6, 21, False),  # Sun 21:00
            (6, 22, True),  # Sun 22:00 — open
            (6, 23, True),  # Sun 23:00
        ],
    )
    def test_market_hours(self, dow: int, hour: int, expected: bool) -> None:
        # 2026-01-05 is Monday (weekday=0)
        base_monday = datetime(2026, 1, 5, tzinfo=UTC)
        dt = base_monday.replace(day=5 + dow, hour=hour, minute=0, second=0)
        assert dt.weekday() == dow
        assert is_forex_market_open(dt) is expected


# ── weekend_gap_seconds ─────────────────────────────────────────


class TestWeekendGapSeconds:
    """Validate weekend-gap subtraction from staleness intervals."""

    @staticmethod
    def _ts(dt: datetime) -> float:
        return dt.timestamp()

    def test_no_gap_within_weekday(self) -> None:
        """Wed 10:00 → Wed 20:00 — no weekend in between."""
        wed_10 = datetime(2026, 1, 7, 10, 0, tzinfo=UTC)  # Wednesday
        wed_20 = datetime(2026, 1, 7, 20, 0, tzinfo=UTC)
        assert weekend_gap_seconds(self._ts(wed_10), self._ts(wed_20)) == 0.0

    def test_full_weekend_gap(self) -> None:
        """Fri 21:00 → Mon 00:00 — spans full 48h weekend gap."""
        fri_21 = datetime(2026, 1, 9, 21, 0, tzinfo=UTC)  # Fri before close
        mon_00 = datetime(2026, 1, 12, 0, 0, tzinfo=UTC)  # Mon midnight
        gap = weekend_gap_seconds(self._ts(fri_21), self._ts(mon_00))
        assert gap == 48.0 * 3600.0  # full 48h

    def test_partial_weekend_gap_starts_saturday(self) -> None:
        """Sat 12:00 → Mon 06:00 — only the overlap counts."""
        sat_12 = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)  # Saturday noon
        mon_06 = datetime(2026, 1, 12, 6, 0, tzinfo=UTC)  # Monday morning
        gap = weekend_gap_seconds(self._ts(sat_12), self._ts(mon_06))
        # gap = Sat 12:00 → Sun 22:00 = 34h
        assert gap == 34.0 * 3600.0

    def test_partial_weekend_gap_ends_before_sunday_open(self) -> None:
        """Fri 20:00 → Sun 10:00 — gap is Fri 22:00 → Sun 10:00 = 36h."""
        fri_20 = datetime(2026, 1, 9, 20, 0, tzinfo=UTC)
        sun_10 = datetime(2026, 1, 11, 10, 0, tzinfo=UTC)
        gap = weekend_gap_seconds(self._ts(fri_20), self._ts(sun_10))
        assert gap == 36.0 * 3600.0

    def test_no_gap_before_friday_close(self) -> None:
        """Thu 08:00 → Fri 21:00 — entirely before close."""
        thu_08 = datetime(2026, 1, 8, 8, 0, tzinfo=UTC)
        fri_21 = datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
        assert weekend_gap_seconds(self._ts(thu_08), self._ts(fri_21)) == 0.0

    def test_two_weekends(self) -> None:
        """Fri 21:00 week1 → Mon 00:00 week2 — two full 48h gaps."""
        fri_21_w1 = datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
        mon_00_w3 = datetime(2026, 1, 19, 0, 0, tzinfo=UTC)
        gap = weekend_gap_seconds(self._ts(fri_21_w1), self._ts(mon_00_w3))
        assert gap == 2 * 48.0 * 3600.0

    def test_now_before_last_update_returns_zero(self) -> None:
        """Reversed timestamps return 0."""
        later = datetime(2026, 1, 12, 10, 0, tzinfo=UTC).timestamp()
        earlier = datetime(2026, 1, 10, 10, 0, tzinfo=UTC).timestamp()
        assert weekend_gap_seconds(later, earlier) == 0.0

    def test_same_timestamp_returns_zero(self) -> None:
        ts = datetime(2026, 1, 10, 12, 0, tzinfo=UTC).timestamp()
        assert weekend_gap_seconds(ts, ts) == 0.0


# ── DQ gate integration (weekend-aware staleness) ───────────────


class TestDataQualityGateWeekendAware:
    """Data quality gate should not flag staleness during weekend closure."""

    def test_h1_not_stale_over_weekend(self) -> None:
        """H1 candle from Fri 21:00 assessed on Sun 10:00 — not stale after
        subtracting the 36h weekend gap."""
        import time as _time
        from unittest.mock import patch

        from analysis.data_quality_gate import DataQualityGate

        gate = DataQualityGate()
        candles = [
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "tick_count": 10, "has_gap": False} for _ in range(50)
        ]

        fri_21 = datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
        sun_10 = datetime(2026, 1, 11, 10, 0, tzinfo=UTC)

        with patch.object(_time, "time", return_value=sun_10.timestamp()):
            report = gate.assess("EURUSD", "H1", candles, last_update_ts=fri_21.timestamp())

        # Raw age = 37h, but weekend gap = 36h → effective staleness = 1h
        # H1 threshold = 10800s = 3h.  1h < 3h → fresh.
        assert report.freshness_state == "fresh"
        assert report.degraded is False

    def test_h1_stale_on_monday_morning(self) -> None:
        """H1 candle from Fri 12:00, assessed Mon 10:00 — effective staleness
        is 18h (raw 70h minus 48h gap + 4h before close).  18h > 3h → stale."""
        import time as _time
        from unittest.mock import patch

        from analysis.data_quality_gate import DataQualityGate

        gate = DataQualityGate()
        candles = [
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "tick_count": 10, "has_gap": False} for _ in range(50)
        ]

        fri_12 = datetime(2026, 1, 9, 12, 0, tzinfo=UTC)
        mon_10 = datetime(2026, 1, 12, 10, 0, tzinfo=UTC)

        with patch.object(_time, "time", return_value=mon_10.timestamp()):
            report = gate.assess("EURUSD", "H1", candles, last_update_ts=fri_12.timestamp())

        # Raw=70h, weekend gap=48h, effective=22h=79200s > 10800s → stale
        assert report.degraded is True
        assert any("stale_data" in r for r in report.reasons)

    def test_weekday_staleness_unchanged(self) -> None:
        """Normal weekday staleness is unaffected (no weekend gap to subtract)."""
        import time as _time
        from unittest.mock import patch

        from analysis.data_quality_gate import DataQualityGate

        gate = DataQualityGate()
        candles = [
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "tick_count": 10, "has_gap": False} for _ in range(50)
        ]

        wed_08 = datetime(2026, 1, 7, 8, 0, tzinfo=UTC)
        wed_14 = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)

        with patch.object(_time, "time", return_value=wed_14.timestamp()):
            report = gate.assess("EURUSD", "H1", candles, last_update_ts=wed_08.timestamp())

        # 6h = 21600s > 10800s threshold → still stale (no weekend gap)
        assert report.degraded is True
        assert any("stale_data" in r for r in report.reasons)
