"""Shutdown notification must wake an idle event loop, not just queue a callback."""

import asyncio
import signal
import threading
import time

import pytest

from startup.signal_handlers import install_signal_handlers


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_shutdown_handler_wakes_idle_loop(monkeypatch, signum):
    handlers = {}

    def install(number, handler):
        previous = handlers.get(number)
        handlers[number] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install)

    async def run():
        stop = asyncio.Event()
        install_signal_handlers(stop)
        timer = threading.Timer(0.05, handlers[signum], args=(signum, None))
        timer.daemon = True
        timer.start()
        started = time.monotonic()
        try:
            # The timeout is the loop's only scheduled timer. A handler that
            # merely calls stop.set() leaves the loop asleep until that timer.
            await asyncio.wait_for(stop.wait(), timeout=1.5)
            assert time.monotonic() - started < 1.0
        finally:
            timer.cancel()
            timer.join(timeout=1)

    asyncio.run(run())
