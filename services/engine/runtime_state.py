"""Shared engine readiness and process shutdown state; no trading authority."""

from __future__ import annotations

import os
import threading


class EngineRuntimeState:
    def __init__(self):
        self._lock = threading.RLock()
        self._bootstrapped = False
        self._analysis_ready = False
        self._analysis_generation = 0
        self._states = {}
        self._stopping = False
        self._fatal = False
        self._deadline = None

    def ready(self):
        with self._lock:
            return (
                self._bootstrapped
                and self._analysis_ready
                and not self._stopping
                and not self._fatal
                and all(state == "STARTING" for state in self._states.values())
            )

    def task_state(self, name, state):
        with self._lock:
            self._states[name] = state
            # Every restart requires evidence from a subsequent analysis cycle.
            self._analysis_ready = False
            if state == "FAILED":
                self.begin_shutdown(fatal=True)

    def bootstrap_complete(self):
        with self._lock:
            self._bootstrapped = True

    def begin_analysis(self):
        with self._lock:
            self._analysis_generation += 1
            self._analysis_ready = False
            return self._analysis_generation

    def analysis_cycle(self, generation):
        with self._lock:
            if generation == self._analysis_generation and not self._stopping:
                self._analysis_ready = True

    def end_analysis(self, generation):
        with self._lock:
            if generation == self._analysis_generation:
                self._analysis_ready = False

    def begin_shutdown(self, *, fatal=False):
        with self._lock:
            self._stopping = True
            self._fatal |= fatal
            self._analysis_ready = False
            if self._deadline is None:
                # Matches the API process bound and survives asyncio.run cleanup.
                self._deadline = threading.Timer(45, lambda: os._exit(1))
                self._deadline.daemon = True
                self._deadline.start()

    def cancel_process_deadline(self):
        """Only the synchronous process owner calls this after asyncio.run exits."""
        with self._lock:
            if self._deadline is not None:
                self._deadline.cancel()
