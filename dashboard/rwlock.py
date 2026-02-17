"""
Read-Write Lock implementation.

Allows multiple concurrent readers OR a single exclusive writer.
Prevents read-read blocking under high tick rates while maintaining
write safety for state mutations.

Zone: dashboard/ — infrastructure utility.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager


class RWLock:
    """
    A Read-Write Lock (multiple readers, single writer).

    Usage:
        lock = RWLock()

        with lock.read():
            # multiple threads can be here simultaneously
            data = shared_state.copy()

        with lock.write():
            # exclusive access
            shared_state["key"] = value
    """

    def __init__(self) -> None:
        self._read_ready = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writers_waiting: int = 0
        self._writer_active: bool = False

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        """Acquire read lock. Multiple readers allowed concurrently."""
        with self._read_ready:
            # Wait if a writer is active or waiting (writer priority to prevent starvation)
            while self._writer_active or self._writers_waiting > 0:
                self._read_ready.wait()
            self._readers += 1

        try:
            yield
        finally:
            with self._read_ready:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        """Acquire write lock. Exclusive access — blocks all readers and writers."""
        with self._read_ready:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                self._read_ready.wait()
            self._writers_waiting -= 1
            self._writer_active = True

        try:
            yield
        finally:
            with self._read_ready:
                self._writer_active = False
                self._read_ready.notify_all()
