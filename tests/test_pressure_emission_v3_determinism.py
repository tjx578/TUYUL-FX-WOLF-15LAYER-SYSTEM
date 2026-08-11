from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.strategy_5scr_v3.pressure.legacy_580_adapter import Legacy580PressureAdapter
from tests.pressure_emission_v3_helpers import load_fixture, railway_record


def test_repeated_normalization_is_byte_identical() -> None:
    record = railway_record(load_fixture("legacy_580", "equivalent_chfjpy.json"))
    adapter = Legacy580PressureAdapter()

    serializations = {adapter.normalize(record).canonical_bytes() for _ in range(100)}

    assert len(serializations) == 1


def test_representative_580_record_cohort_has_no_silent_drop_or_adapter_duplicate() -> None:
    base = load_fixture("legacy_580", "equivalent_chfjpy.json")
    start = datetime(2026, 7, 17, 13, 5, tzinfo=UTC)
    records = []
    for index in range(580):
        payload = dict(base)
        event_time = start + timedelta(seconds=index)
        payload["signal_valid_time_utc"] = event_time.isoformat()
        payload["cluster_id"] = f"CHFJPY_LEGACY_580_{index:04d}"
        records.append(railway_record(payload))

    normalized = [Legacy580PressureAdapter().normalize(record) for record in records]

    assert len(normalized) == 580
    assert len({item.identity.transport_event_id for item in normalized}) == 580
    assert all(item.source_safety.final_direction == "WAIT" for item in normalized)
    assert all(item.source_safety.valid_for_execution is False for item in normalized)
    assert all(item.execution_authority is False for item in normalized)
