"""Adapter for already-durable, contract-valid LIVE pressure outbox rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from analysis.strategy_5scr_v3.pressure.canonical_emission import _build_canonical_emission
from analysis.strategy_5scr_v3.pressure.normalization_errors import (
    PressureEmissionNormalizationError,
)
from contracts.strategy_5scr_pressure_emission_v3 import CanonicalPressureEmissionV3
from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from storage.pressure_outbox import pressure_payload_hash


class LivePressureOutboxAdapter:
    """Normalize a validated outbox envelope without creating domain state."""

    def normalize(
        self,
        source: PressureOutboxEnvelope | Mapping[str, Any],
    ) -> CanonicalPressureEmissionV3:
        envelope = (
            source if isinstance(source, PressureOutboxEnvelope) else PressureOutboxEnvelope.model_validate(source)
        )
        if pressure_payload_hash(envelope.payload) != envelope.payload_hash:
            raise PressureEmissionNormalizationError("LIVE_PRESSURE_OUTBOX_PAYLOAD_HASH_MISMATCH")
        return _build_canonical_emission(
            envelope.payload,
            profile="LIVE_PRESSURE_OUTBOX",
            transport_event_id=str(envelope.event_id),
            received_at_utc=envelope.created_at,
            envelope_lineage={
                "source_clean_block_id": envelope.source_clean_block_id,
                "source_watch_id": envelope.source_watch_id,
            },
        )


__all__ = ["LivePressureOutboxAdapter"]
