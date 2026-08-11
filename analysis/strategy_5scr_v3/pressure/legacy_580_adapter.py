"""Replay-only adapter for historical Railway pressure log records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from analysis.strategy_5scr_v3.pressure.canonical_emission import (
    build_canonical_emission,
    parse_datetime,
)
from analysis.strategy_5scr_v3.pressure.normalization_errors import (
    PressureEmissionNormalizationError,
)
from contracts.strategy_5scr_pressure_emission_v3 import CanonicalPressureEmissionV3

PRESSURE_LOG_MARKER = "[SignalPressureStateJSON]"


class Legacy580PressureAdapter:
    """Extract source facts without reconstructing canonical LIVE authority."""

    def normalize(self, record: Mapping[str, Any] | str) -> CanonicalPressureEmissionV3:
        payload, wrapper_timestamp = self._extract(record)
        received_at = parse_datetime(wrapper_timestamp)
        return build_canonical_emission(
            payload,
            profile="LEGACY_580",
            received_at_utc=received_at,
            fallback_event_time_utc=received_at,
        )

    @staticmethod
    def _extract(record: Mapping[str, Any] | str) -> tuple[Mapping[str, Any], Any]:
        wrapper_timestamp: Any = None
        if isinstance(record, Mapping):
            wrapper_timestamp = record.get("timestamp")
            if record.get("event") is not None and record.get("message") is None:
                return record, wrapper_timestamp
            raw = record.get("message")
            if not isinstance(raw, str):
                raise PressureEmissionNormalizationError("LEGACY_580_MESSAGE_MISSING")
        elif isinstance(record, str):
            raw = record
        else:
            raise PressureEmissionNormalizationError("LEGACY_580_RECORD_TYPE_UNSUPPORTED")

        if PRESSURE_LOG_MARKER not in raw:
            raise PressureEmissionNormalizationError("LEGACY_580_PRESSURE_MARKER_MISSING")
        serialized = raw.split(PRESSURE_LOG_MARKER, 1)[1].strip()
        try:
            payload = json.loads(serialized)
        except json.JSONDecodeError as exc:
            raise PressureEmissionNormalizationError("LEGACY_580_JSON_INVALID") from exc
        if not isinstance(payload, Mapping):
            raise PressureEmissionNormalizationError("LEGACY_580_PAYLOAD_NOT_OBJECT")
        return payload, wrapper_timestamp


__all__ = ["Legacy580PressureAdapter", "PRESSURE_LOG_MARKER"]
