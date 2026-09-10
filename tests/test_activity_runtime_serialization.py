from __future__ import annotations

import json
from dataclasses import asdict, replace
from unittest.mock import Mock

import pytest

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations, pair_activity_raw_event_id
from storage.strategy_5scr_activity_runtime import PostgresActivityRuntime, _event_payload
from tests.test_activity_runtime_binding import binding
from tests.test_strategy_5scr_raw_admission_blocks import _raw


def test_dataclass_and_mapping_preserve_payload_identity_and_replay_hash():
    event = replace(
        _raw(0),
        source_observation_id="serialization-source",
        source_observation_schema="signal-throttle-observation.v1",
    )
    original = asdict(event)
    expected = json.loads(json.dumps(original, default=lambda value: value.isoformat()))
    payload = _event_payload(event)

    assert payload == _event_payload(original) == _event_payload(expected) == expected
    assert asdict(event) == original
    assert pair_activity_raw_event_id(payload) == pair_activity_raw_event_id(event)
    first = normalize_pair_activity_observations([event])
    replay = normalize_pair_activity_observations([payload, expected])
    assert replay.raw_population_hash == first.raw_population_hash
    assert replay.logical_observations == first.logical_observations
    assert replay.raw_event_count == 1
    assert replay.duplicate_delivery_count == 1


def test_dataclass_class_is_rejected_before_connection_and_latches_recovery(monkeypatch):
    runtime = PostgresActivityRuntime(dsn="never-connected", binding=binding(), checkpoint_provider=lambda: None)
    connect = Mock(side_effect=AssertionError("invalid payload must fail before connecting"))
    monkeypatch.setattr(runtime, "_connect", connect)

    with pytest.raises(TypeError):
        _event_payload(SignalThrottleLogEvent)
    with pytest.raises(TypeError):
        runtime.append([SignalThrottleLogEvent])

    runtime.record(SignalThrottleLogEvent)
    runtime.record(_raw(0))
    snapshot = runtime.snapshot()
    assert snapshot["status"] == "RECOVERY_REQUIRED"
    assert snapshot["reason_code"] == "RAW_DURABILITY_WRITE_FAILED"
    assert snapshot["replay_required"] is True
    assert all(snapshot[key] is False for key in ("hypothesis_authority", "risk_authority", "execution_authority"))
    connect.assert_not_called()
