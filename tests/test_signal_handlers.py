import asyncio
import signal
import threading
import time
from unittest.mock import Mock

import pytest

from startup.signal_handlers import install_signal_handlers


def test_install_signal_handlers_prefers_running_loop(monkeypatch):
    shutdown_event = asyncio.Event()
    callbacks = {}

    class Loop:
        def add_signal_handler(self, signum, callback, *args):
            callbacks[signum] = (callback, args)

    loop = Loop()
    signal_signal = Mock()
    monkeypatch.setattr("startup.signal_handlers.asyncio.get_running_loop", lambda: loop)
    monkeypatch.setattr("startup.signal_handlers.signal.signal", signal_signal)

    install_signal_handlers(shutdown_event)

    assert set(callbacks) == {signal.SIGINT, signal.SIGTERM}
    signal_signal.assert_not_called()
    callback, args = callbacks[signal.SIGTERM]
    callback(*args)
    assert shutdown_event.is_set()


def test_install_signal_handlers_falls_back_to_signal_module(monkeypatch):
    shutdown_event = asyncio.Event()
    handlers = {}
    scheduled = []

    class Loop:
        def add_signal_handler(self, signum, callback, *args):
            raise NotImplementedError

        def call_soon_threadsafe(self, callback, *args):
            scheduled.append((callback, args))

        def is_closed(self):
            return False

    monkeypatch.setattr("startup.signal_handlers.asyncio.get_running_loop", lambda: Loop())
    monkeypatch.setattr(
        "startup.signal_handlers.signal.signal", lambda signum, handler: handlers.setdefault(signum, handler)
    )

    install_signal_handlers(shutdown_event)

    assert set(handlers) == {signal.SIGINT, signal.SIGTERM}
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert scheduled == [(shutdown_event.set, ())]
    assert not shutdown_event.is_set()
    scheduled[0][0](*scheduled[0][1])
    assert shutdown_event.is_set()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_shutdown_handler_wakes_idle_loop(monkeypatch, signum):
    handlers = {}

    def install(number, handler):
        previous = handlers.get(number)
        handlers[number] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install)

    async def run():
        def unsupported(*args):
            raise NotImplementedError

        monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", unsupported)
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
