"""
dashboard/rwlock.py — Reader/Writer Lock

Thread-safe read-write lock implementation.
Multiple readers are allowed concurrently; writers get exclusive access.

Authority: Dashboard-layer utility. No market decisions.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager


class RWLock:
    """Reader/Writer lock — allows concurrent reads, exclusive writes.

    Usage:
        lock = RWLock()

        with lock.read():
            # concurrent read access
            ...

        with lock.write():
            # exclusive write access
            ...
    """

    def __init__(self) -> None:
        super().__init__()
        self._read_ready = threading.Condition(threading.Lock())
        self._readers: int = 0

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        """Acquire shared read lock. Multiple readers allowed simultaneously."""
        with self._read_ready:
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
        """Acquire exclusive write lock. Blocks until all readers release."""
        with self._read_ready:
            while self._readers > 0:
                self._read_ready.wait()
            yield
