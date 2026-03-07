from __future__ import annotations

from context.live_context_bus import LiveContextBus
from ingest.dependencies import _update_realtime_conditioning


def test_live_context_bus_conditioned_returns_roundtrip() -> None:
    bus = LiveContextBus()
    bus.reset_state()

    bus.update_conditioned_returns(
        "EURUSD",
        [0.001, -0.0005, 0.0008],
        diagnostics={"source": "unit_test", "samples_out": 3},
    )

    returns = bus.get_conditioned_returns("EURUSD")
    meta = bus.get_conditioning_meta("EURUSD")

    assert returns == [0.001, -0.0005, 0.0008]
    assert meta is not None
    assert meta["source"] == "unit_test"
    assert meta["samples_out"] == 3


def test_realtime_tick_path_publishes_conditioned_returns() -> None:
    bus = LiveContextBus()
    bus.reset_state()

    symbol = "EURUSD_RT_TEST"
    base = 1.1000

    # Fill enough prices to cross realtime_min_prices threshold.
    for i in range(30):
        _update_realtime_conditioning(
            context_bus=bus,
            symbol=symbol,
            price=base + (i * 0.00005),
            ts=1700000000.0 + i,
        )

    returns = bus.get_conditioned_returns(symbol)
    meta = bus.get_conditioning_meta(symbol)

    assert len(returns) > 0
    assert meta is not None
    assert meta.get("source") == "tick_realtime"
    assert int(meta.get("samples_out", 0)) > 0
