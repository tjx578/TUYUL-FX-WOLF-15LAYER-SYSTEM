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

    Write-preferring: when a writer is waiting, new readers queue behind it
    to prevent writer starvation.

    Usage:
        lock = RWLock()

        with lock.read():
            # concurrent read access
            ...

        with lock.write():
            # exclusive write access
            ...
    """

    _TIMEOUT: float = 10.0  # seconds — safety net against deadlocks

    def __init__(self) -> None:
        super().__init__()
        self._cond = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writers_waiting: int = 0
        self._writer_active: bool = False

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        """Acquire shared read lock. Blocks while a writer is active or waiting."""
        with self._cond:
            if not self._cond.wait_for(
                lambda: not self._writer_active and self._writers_waiting == 0,
                timeout=self._TIMEOUT,
            ):
                raise TimeoutError("RWLock.read: timed out waiting for writer")
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        """Acquire exclusive write lock. Blocks until all readers release."""
        with self._cond:
            self._writers_waiting += 1
            try:
                if not self._cond.wait_for(
                    lambda: self._readers == 0 and not self._writer_active,
                    timeout=self._TIMEOUT,
                ):
                    raise TimeoutError("RWLock.write: timed out waiting for readers")
                self._writer_active = True
            finally:
                self._writers_waiting -= 1
            try:
                yield
            finally:
                self._writer_active = False
                self._cond.notify_all()
