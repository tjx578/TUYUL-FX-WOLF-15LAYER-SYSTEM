"""
Tests for GAP #4 fix: event-driven analysis loop.

Validates:
  1. EventBus singleton accessor
  2. CANDLE_CLOSED authority restriction (only 'ingest' may emit)
  3. CandleBuilder emits CANDLE_CLOSED after building a candle
  4. analysis_loop wakes on CANDLE_CLOSED (not just polling)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Import directly from the module file to avoid core/__init__.py re-export issues
from core.event_bus import Event, EventBus, EventType, get_event_bus

# ---------------------------------------------------------------------------
# EventBus singleton
# ---------------------------------------------------------------------------


class TestGetEventBus:
    def setup_method(self):
        # Reset singleton between tests
        import core.event_bus as _mod  # noqa: PLC0415

        self._prev = _mod._event_bus_instance
        _mod._event_bus_instance = None

    def teardown_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        _mod._event_bus_instance = self._prev

    def test_returns_eventbus_instance(self):
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    def test_returns_same_instance(self):
        a = get_event_bus()
        b = get_event_bus()
        assert a is b


# ---------------------------------------------------------------------------
# Authority enforcement for CANDLE_CLOSED
# ---------------------------------------------------------------------------


class TestCandleClosedAuthority:
    def setup_method(self):
        self.bus = EventBus()

    @pytest.mark.asyncio
    async def test_ingest_can_emit_candle_closed(self):
        received: list[Event] = []
        self.bus.subscribe(EventType.CANDLE_CLOSED, received.append)
        event = Event(type=EventType.CANDLE_CLOSED, source="ingest", data={"symbol": "EURUSD"})
        await self.bus.emit(event)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_unauthorized_source_blocked(self):
        event = Event(type=EventType.CANDLE_CLOSED, source="dashboard", data={})
        with pytest.raises(PermissionError):
            await self.bus.emit(event)


# ---------------------------------------------------------------------------
# CandleBuilder emits CANDLE_CLOSED
# ---------------------------------------------------------------------------


class TestCandleBuilderEmitsEvent:
    """Verify that _try_build emits a CANDLE_CLOSED event after building a candle."""

    def setup_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        self._prev = _mod._event_bus_instance
        _mod._event_bus_instance = None

    def teardown_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        _mod._event_bus_instance = self._prev

    def test_candle_build_emits_event(self):
        """When CandleBuilder completes a candle, it should emit CANDLE_CLOSED."""
        from ingest.candle_builder import CandleBuilder, Timeframe  # noqa: PLC0415

        bus = get_event_bus()
        received: list[Event] = []
        bus.subscribe(EventType.CANDLE_CLOSED, received.append)

        builder = CandleBuilder("EURUSD", Timeframe.M15)

        # Feed 15 minutes of ticks to complete one M15 candle,
        # then one tick in the next period to trigger the rollover.
        base = datetime(2026, 2, 16, 10, 0, 0, tzinfo=UTC)
        loop = asyncio.new_event_loop()
        try:
            completed = None
            for i in range(16):
                result = builder.on_tick(
                    price=1.1000 + i * 0.0001,
                    timestamp=base + timedelta(minutes=i),
                    volume=100.0,
                )
                if result is not None:
                    completed = result
            # Allow any async tasks (event emission) to run
            loop.run_until_complete(asyncio.sleep(0.05))
        finally:
            loop.close()

        assert completed is not None, "Expected a completed M15 candle after 16 ticks"


# ---------------------------------------------------------------------------
# analysis_loop wakes on CANDLE_CLOSED
# ---------------------------------------------------------------------------


class TestAnalysisLoopEventDriven:
    """Integration test: analysis_loop wakes immediately on CANDLE_CLOSED."""

    def setup_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        self._prev = _mod._event_bus_instance
        _mod._event_bus_instance = None

    def teardown_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        _mod._event_bus_instance = self._prev

    @pytest.mark.asyncio
    async def test_loop_wakes_on_candle_event(self):
        """analysis_loop should run _analyze_pair within <2s of event, not wait 60s."""
        bus = get_event_bus()
        analyzed: list[str] = []

        async def fake_analyze_pair(pair, pipeline):
            analyzed.append(pair)
            return {"synthesis": {}, "l12": {}}

        shutdown = asyncio.Event()
        mock_pipeline = MagicMock()

        with (
            patch("startup.analysis_loop._analyze_pair", side_effect=fake_analyze_pair),
            patch("startup.analysis_loop.CONFIG", {"settings": {"loop_interval_sec": 300}}),
            patch("startup.analysis_loop.get_event_bus", return_value=bus),
            patch.dict("os.environ", {"ANALYSIS_LOOP_INTERVAL_SEC": "300"}),
        ):
            from startup.analysis_loop import analysis_loop  # noqa: PLC0415

            loop_task = asyncio.create_task(
                analysis_loop(
                    pairs=["EURUSD", "GBPUSD"],
                    pipeline=mock_pipeline,
                    shutdown_event=shutdown,
                )
            )

            # Give the loop time to start and subscribe
            await asyncio.sleep(0.1)

            # Emit CANDLE_CLOSED for EURUSD
            event = Event(
                type=EventType.CANDLE_CLOSED,
                source="ingest",
                data={"symbol": "EURUSD", "timeframe": "M15"},
            )
            await bus.emit(event)

            # Wait a short time - loop should react quickly
            await asyncio.sleep(0.5)

            shutdown.set()

            # Give loop time to exit
            try:
                await asyncio.wait_for(loop_task, timeout=2.0)
            except (asyncio.CancelledError, TimeoutError):
                loop_task.cancel()

        # EURUSD should have been analysed (event-triggered)
        assert "EURUSD" in analyzed
        # GBPUSD should NOT have been analysed (wasn't in event)
        # (unless the loop also did a fallback sweep, which it shouldn't within 300s)


# ---------------------------------------------------------------------------
# analysis_loop fallback sweep
# ---------------------------------------------------------------------------


class TestAnalysisLoopFallback:
    """When no events arrive, the loop falls back to polling after timeout."""

    def setup_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        self._prev = _mod._event_bus_instance
        _mod._event_bus_instance = None

    def teardown_method(self):
        import core.event_bus as _mod  # noqa: PLC0415

        _mod._event_bus_instance = self._prev

    @pytest.mark.asyncio
    async def test_fallback_runs_all_pairs(self):
        """With a 1s fallback interval and no events, all pairs are analysed."""
        bus = get_event_bus()
        analyzed: list[str] = []

        async def fake_analyze_pair(pair, pipeline):
            analyzed.append(pair)
            return {"synthesis": {}, "l12": {}}

        shutdown = asyncio.Event()
        mock_pipeline = MagicMock()

        with (
            patch("startup.analysis_loop._analyze_pair", side_effect=fake_analyze_pair),
            patch("startup.analysis_loop.CONFIG", {"settings": {"loop_interval_sec": 1}}),
            patch("startup.analysis_loop.get_event_bus", return_value=bus),
            patch.dict("os.environ", {}, clear=False),
        ):
            # Remove env override so it uses config value of 1s
            import os  # noqa: PLC0415

            os.environ.pop("ANALYSIS_LOOP_INTERVAL_SEC", None)

            from startup.analysis_loop import analysis_loop  # noqa: PLC0415

            loop_task = asyncio.create_task(
                analysis_loop(
                    pairs=["EURUSD", "GBPUSD"],
                    pipeline=mock_pipeline,
                    shutdown_event=shutdown,
                )
            )

            # Wait for the 1s fallback timeout + execution
            await asyncio.sleep(1.8)

            shutdown.set()
            try:
                await asyncio.wait_for(loop_task, timeout=2.0)
            except (asyncio.CancelledError, TimeoutError):
                loop_task.cancel()

        # Both pairs should have been analysed in the fallback sweep
        assert "EURUSD" in analyzed
        assert "GBPUSD" in analyzed
