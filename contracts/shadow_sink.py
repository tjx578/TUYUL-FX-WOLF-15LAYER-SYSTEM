"""P1 live wiring — append-only shadow journal sink.

``ShadowJournalSink`` records one JSONL record per shadow build into a
rotating file. **All writes are best-effort**: a write failure is logged
but never propagated, consistent with the P1-A runtime-projection safety
contract (shadow infrastructure must never impact the legacy path).

Flag-gated usage is handled by :mod:`contracts.shadow_hook`. This module
is the low-level writer; callers should not instantiate it directly in
the pipeline — use the hook instead.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts.decision_bundle import DecisionBundle

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "shadow_capture.jsonl"


class ShadowJournalSink:
    """Append-only JSONL sink for shadow ``DecisionBundle`` audits.

    File format: one JSON object per line with keys
    ``recorded_at``, ``summary`` (:meth:`ShadowCaptureSession.summary`),
    and ``bundle`` (``DecisionBundle.model_dump(mode="json")`` or
    ``None`` when the build failed).

    Thread-safe for concurrent pipeline workers via an internal lock.
    **Never raises** out of :meth:`record`.
    """

    def __init__(self, *, path: str | Path | None = None) -> None:
        raw = path or os.getenv("WOLF_SHADOW_JOURNAL_PATH", _DEFAULT_PATH)
        self._path = Path(raw)
        self._lock = threading.Lock()
        self._write_count = 0
        self._error_count = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def write_count(self) -> int:
        return self._write_count

    @property
    def error_count(self) -> int:
        return self._error_count

    def record(
        self,
        summary: dict[str, Any],
        bundle: DecisionBundle | None,
    ) -> bool:
        """Append one shadow record. Returns True on success, False on failure.

        Failures are counted and logged at DEBUG to keep production logs
        quiet — callers already handle ``False`` by ignoring it.
        """
        try:
            payload = {
                "recorded_at": datetime.now(tz=UTC).isoformat(),
                "summary": _jsonable(summary),
                "bundle": bundle.model_dump(mode="json") if bundle is not None else None,
            }
            line = json.dumps(payload, sort_keys=True, default=str)
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            logger.debug("ShadowJournalSink serialize failed: %s", exc)
            return False

        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self._write_count += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            logger.debug("ShadowJournalSink write failed: %s", exc)
            return False


def _jsonable(value: Any) -> Any:
    """Best-effort coercion to JSON-serializable form.

    Preserves dict/list shape; falls back to ``str(value)`` for scalars
    the encoder cannot handle natively. ``default=str`` on
    :func:`json.dumps` is the final safety net.
    """
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


__all__ = ["ShadowJournalSink"]
