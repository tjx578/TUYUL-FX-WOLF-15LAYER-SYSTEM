from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from storage.pressure_outbox import prepare_pressure_event

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "strategy_5scr" / "pressure_emission_v3"


def load_fixture(*parts: str) -> dict[str, object]:
    return json.loads((_FIXTURE_ROOT.joinpath(*parts)).read_text(encoding="utf-8"))


def railway_record(payload: dict[str, object]) -> dict[str, str]:
    return {
        "message": "WARNING signal_json [SignalPressureStateJSON] " + json.dumps(payload, separators=(",", ":")),
        "timestamp": "2026-07-17T13:05:00.100Z",
    }


def live_envelope(payload: dict[str, object]) -> PressureOutboxEnvelope:
    prepared = prepare_pressure_event(payload)
    stored_payload = {**prepared.payload, "lifecycle_sequence": 1}
    now = datetime(2026, 7, 17, 13, 5, tzinfo=UTC)
    return PressureOutboxEnvelope(
        outbox_id=prepared.outbox_id,
        event_id=prepared.event_id,
        schema_version=prepared.schema_version,
        symbol=prepared.symbol,
        lifecycle_id=prepared.lifecycle_id,
        lifecycle_sequence=1,
        source_clean_block_id=prepared.source_clean_block_id,
        source_watch_id=prepared.source_watch_id,
        signal_valid_at=prepared.signal_valid_at,
        payload=stored_payload,
        payload_hash=prepared.payload_hash,
        status="PENDING",
        attempt_count=0,
        available_at=now,
        created_at=now,
    )
