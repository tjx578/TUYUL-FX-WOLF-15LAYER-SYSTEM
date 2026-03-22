"""
Tests for the unified CandleBuilder (ingest/candle_builder.py).

Covers:
- M15 candle building from ticks
- H1 candle aggregation from M15 candles
- Multi-timeframe chaining (tick → M15 → H1)
- Period alignment
- Flush behavior
- Backward-compat import from analysis/
"""

from datetime import UTC, datetime, timedelta

import pytest

from ingest.candle_builder import (
    Candle,
    CandleBuilder,
    MultiTimeframeCandleBuilder,
    Timeframe,
    _align_to_period,
)

# ── Alignment ────────────────────────────────────────────────────────


class TestAlignment:
    def test_m15_alignment(self):
        dt = datetime(2026, 2, 17, 10, 7, 30, tzinfo=UTC)
        aligned = _align_to_period(dt, 15)
        assert aligned == datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

    def test_m15_alignment_on_boundary(self):
        dt = datetime(2026, 2, 17, 10, 15, 0, tzinfo=UTC)
        aligned = _align_to_period(dt, 15)
        assert aligned == datetime(2026, 2, 17, 10, 15, tzinfo=UTC)

    def test_h1_alignment(self):
        dt = datetime(2026, 2, 17, 10, 42, 0, tzinfo=UTC)
        aligned = _align_to_period(dt, 60)
        assert aligned == datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

    def test_h4_alignment(self):
        dt = datetime(2026, 2, 17, 5, 30, 0, tzinfo=UTC)
        aligned = _align_to_period(dt, 240)
        assert aligned == datetime(2026, 2, 17, 4, 0, tzinfo=UTC)

    def test_naive_datetime_treated_as_utc(self):
        dt_naive = datetime(2026, 2, 17, 10, 7, 30)
        dt_aware = datetime(2026, 2, 17, 10, 7, 30, tzinfo=UTC)
        assert _align_to_period(dt_naive, 15) == _align_to_period(dt_aware, 15)


# ── M15 from Ticks ──────────────────────────────────────────────────


class TestM15FromTicks:
    def _make_builder(self):
        return CandleBuilder("EURUSD", Timeframe.M15)

    def test_single_period_no_completion(self):
        b = self._make_builder()
        base = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)
        for i in range(5):
            result = b.on_tick(1.1000 + i * 0.0001, base + timedelta(seconds=i * 60))
            assert result is None  # still in same period

    def test_cross_period_emits_candle(self):
        b = self._make_builder()
        base = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

        # Feed ticks in 10:00–10:14
        b.on_tick(1.1000, base)
        b.on_tick(1.1050, base + timedelta(minutes=5))
        b.on_tick(1.0980, base + timedelta(minutes=10))
        b.on_tick(1.1020, base + timedelta(minutes=14))

        # This tick at 10:15 should trigger completion of the 10:00 candle
        completed = b.on_tick(1.1030, base + timedelta(minutes=15))

        assert completed is not None
        assert completed.complete is True
        assert completed.timeframe == "M15"
        assert completed.open == 1.1000
        assert completed.high == 1.1050
        assert completed.low == 1.0980
        assert completed.close == 1.1020
        assert completed.tick_count == 4
        assert completed.open_time == base
        assert completed.close_time == base + timedelta(minutes=15)

    def test_multiple_periods(self):
        b = self._make_builder()
        base = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

        # Fill 3 periods: 10:00, 10:15, 10:30
        candles = []
        for period in range(3):
            for m in range(15):
                t = base + timedelta(minutes=period * 15 + m)
                c = b.on_tick(1.1000 + period * 0.001, t)
                if c is not None:
                    candles.append(c)

        # Flush the last one
        c = b.flush()
        if c is not None:
            candles.append(c)

        assert len(candles) == 3
        assert candles[0].open_time == base
        assert candles[1].open_time == base + timedelta(minutes=15)
        assert candles[2].open_time == base + timedelta(minutes=30)


# ── H1 from M15 Candles ─────────────────────────────────────────────


class TestH1FromM15:
    def _make_m15_candle(self, open_time: datetime, o: float, h: float, l: float, c: float) -> Candle:  # noqa: E741
        return Candle(
            symbol="EURUSD",
            timeframe="M15",
            open_time=open_time,
            close_time=open_time + timedelta(minutes=15),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=100.0,
            tick_count=50,
            complete=True,
        )

    def test_four_m15_make_one_h1(self):
        b = CandleBuilder("EURUSD", Timeframe.H1)
        base = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

        # Feed 4 M15 candles (10:00, 10:15, 10:30, 10:45)
        m15s = [
            self._make_m15_candle(base, 1.10, 1.12, 1.09, 1.11),
            self._make_m15_candle(base + timedelta(minutes=15), 1.11, 1.13, 1.10, 1.12),
            self._make_m15_candle(base + timedelta(minutes=30), 1.12, 1.14, 1.11, 1.13),
            self._make_m15_candle(base + timedelta(minutes=45), 1.13, 1.15, 1.12, 1.14),
        ]

        results = [b.on_candle(c) for c in m15s]
        # None of them trigger completion yet (all in same hour)
        assert all(r is None for r in results)

        # Feed first M15 of next hour → triggers H1 completion
        next_hour_candle = self._make_m15_candle(base + timedelta(minutes=60), 1.14, 1.16, 1.13, 1.15)
        h1 = b.on_candle(next_hour_candle)

        assert h1 is not None
        assert h1.timeframe == "H1"
        assert h1.complete is True
        assert h1.open == 1.10
        assert h1.high == 1.15
        assert h1.low == 1.09
        assert h1.close == 1.14
        assert h1.volume == 400.0
        assert h1.tick_count == 200
        assert h1.open_time == base
        assert h1.close_time == base + timedelta(minutes=60)

    def test_incomplete_candle_ignored(self):
        b = CandleBuilder("EURUSD", Timeframe.H1)
        incomplete = Candle(
            symbol="EURUSD",
            timeframe="M15",
            open_time=datetime(2026, 2, 17, 10, 0, tzinfo=UTC),
            close_time=datetime(2026, 2, 17, 10, 15, tzinfo=UTC),
            open=1.10,
            high=1.11,
            low=1.09,
            close=1.10,
            complete=False,
        )
        assert b.on_candle(incomplete) is None
        assert len(b.completed_candles) == 0


# ── MultiTimeframeCandleBuilder ─────────────────────────────────────


class TestMultiTimeframe:
    def test_tick_to_m15_and_h1(self):
        results = {"M15": [], "H1": []}

        def on_any(candle: Candle):
            results[candle.timeframe].append(candle)

        mtf = MultiTimeframeCandleBuilder(
            "EURUSD",
            timeframes=[Timeframe.M15, Timeframe.H1],
            on_any_complete=on_any,
        )

        base = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

        # Feed 1 tick per minute for 75 minutes (10:00–11:14)
        # This should produce 5 completed M15 candles by rollover.
        # After flush_all(), the in-progress H1 (11:00 period) is also force-closed.
        for minute in range(75):
            t = base + timedelta(minutes=minute)
            price = 1.1000 + (minute % 15) * 0.0001
            mtf.on_tick(price, t, volume=1.0)

        # Flush remaining
        mtf.flush_all()

        # Count completed M15 candles: periods 10:00,10:15,10:30,10:45,11:00
        # The 10:00 M15 completes when 10:15 arrives, etc.
        # With 75 minutes: 5 full M15 periods completed by rollover
        assert len(results["M15"]) == 5

        # H1 candles:
        # - 10:00 period completes on rollover
        # - 11:00 period is force-closed by flush_all
        assert len(results["H1"]) == 2
        first_h1 = results["H1"][0]
        second_h1 = results["H1"][1]
        assert first_h1.open_time == base
        assert first_h1.timeframe == "H1"
        assert second_h1.open_time == base + timedelta(hours=1)

    def test_default_timeframes(self):
        mtf = MultiTimeframeCandleBuilder("GBPUSD")
        assert "M15" in mtf._builders
        assert "H1" in mtf._builders

    def test_custom_timeframes(self):
        mtf = MultiTimeframeCandleBuilder(
            "USDJPY",
            timeframes=[Timeframe.M5, Timeframe.M15, Timeframe.H4],
        )
        assert "M5" in mtf._builders
        assert "M15" in mtf._builders
        assert "H4" in mtf._builders


# ── Flush ────────────────────────────────────────────────────────────


class TestFlush:
    def test_flush_partial_candle(self):
        b = CandleBuilder("EURUSD", Timeframe.M15)
        base = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)
        b.on_tick(1.10, base)
        b.on_tick(1.12, base + timedelta(minutes=5))

        partial = b.current_partial
        assert partial is not None
        assert partial.complete is False

        flushed = b.flush()
        assert flushed is not None
        assert flushed.complete is True
        assert flushed.open == 1.10
        assert flushed.close == 1.12

    def test_flush_empty(self):
        b = CandleBuilder("EURUSD", Timeframe.M15)
        assert b.flush() is None


# ── Candle.to_dict ───────────────────────────────────────────────────


class TestCandleDict:
    def test_round_trip(self):
        c = Candle(
            symbol="EURUSD",
            timeframe="M15",
            open_time=datetime(2026, 2, 17, 10, 0, tzinfo=UTC),
            close_time=datetime(2026, 2, 17, 10, 15, tzinfo=UTC),
            open=1.10,
            high=1.12,
            low=1.09,
            close=1.11,
            volume=500.0,
            tick_count=100,
            complete=True,
        )
        d = c.to_dict()
        assert d["symbol"] == "EURUSD"
        assert d["complete"] is True
        assert isinstance(d["open_time"], str)


# ── Timeframe enum ───────────────────────────────────────────────────


class TestTimeframe:
    def test_from_str(self):
        assert Timeframe.from_str("m15") == Timeframe.M15
        assert Timeframe.from_str("H1") == Timeframe.H1

    def test_from_str_invalid(self):
        with pytest.raises(ValueError, match="Unknown timeframe"):
            Timeframe.from_str("W1")

    def test_minutes(self):
        assert Timeframe.M15.minutes == 15
        assert Timeframe.H1.minutes == 60
        assert Timeframe.H4.minutes == 240


# ── Backward-compat import from analysis/ ────────────────────────────


class TestBackwardCompat:
    def test_import_from_analysis(self):
        from analysis.candle_builder import (
            Candle as ACandle,
        )
        from analysis.candle_builder import (
            CandleBuilder as ACB,  # noqa: N814
        )
        from analysis.candle_builder import (
            Timeframe as ATF,  # noqa: N814
        )

        # They should be the exact same objects
        assert ACandle is Candle
        assert ACB is CandleBuilder
        assert ATF is Timeframe
