from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer
from analysis.strategy_5scr_activity_service import activity_runtime_from_environment
from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
from contracts.strategy_5scr_activity_runtime import ActivityRuntimeBindingV1

START = datetime(2026, 9, 9, tzinfo=UTC)


def binding(**overrides):
    return ActivityRuntimeBindingV1(
        **{
            "ledger_id": "binding-test",
            "deployment_id": "deployment-test",
            "producer_id": "producer-test",
            "source_scope_id": "all-raw-test",
            "coverage_attestor_id": "attestor-test",
            "environment_class": "DISPOSABLE_TEST",
            "window_start_utc": START,
            "maximum_ledger_events": 100,
            "recovery_overlap_seconds": 30,
            **overrides,
        }
    )


def test_factory_does_not_fall_back_to_general_database():
    runtime = activity_runtime_from_environment({"DATABASE_URL": "must-not-be-used"})
    assert runtime.snapshot()["reason_code"] == "ACTIVITY_RUNTIME_BINDING_UNBOUND"


@pytest.mark.parametrize("valid", [True, False])
def test_factory_binds_delivery_scope_or_fails_explicitly(tmp_path, valid):
    from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1
    from storage.strategy_5scr_activity_runtime import PostgresActivityRuntime

    bound = binding()
    source = tmp_path / "binding.json"
    source.write_text(bound.model_dump_json(), encoding="utf-8")
    scope_path = tmp_path / "scope.json"
    scope = ActivityConsumerScopeV1(
        consumer_scope_id="fixture",
        producer_binding_hash=bound.binding_hash if valid else "sha256:" + "0" * 64,
        lifecycle_owner_id="fixture-owner",
        lifecycle_policy_hash="sha256:" + "2" * 64,
        environment_class="DISPOSABLE_TEST",
    )
    scope_path.write_text(scope.model_dump_json(), encoding="utf-8")
    runtime = activity_runtime_from_environment(
        {
            "WOLF15_PAIR_ACTIVITY_BINDING_PATH": str(source),
            "WOLF15_PAIR_ACTIVITY_DATABASE_URL": "never-connected",
            "DEPLOYMENT_ID": bound.deployment_id,
            "WOLF15_PAIR_ACTIVITY_DELIVERY_SCOPE_PATH": str(scope_path),
        }
    )
    if valid:
        assert isinstance(runtime, PostgresActivityRuntime)
        assert runtime._delivery_scope == scope
    else:
        assert runtime.snapshot()["reason_code"] == "ACTIVITY_DELIVERY_SCOPE_INVALID"


def test_factory_missing_dsn_or_wrong_deployment_is_explicit(tmp_path):
    path = tmp_path / "binding.json"
    path.write_text(binding().model_dump_json(), encoding="utf-8")
    env = {"WOLF15_PAIR_ACTIVITY_BINDING_PATH": str(path)}
    assert activity_runtime_from_environment(env).snapshot()["reason_code"] == "ACTIVITY_RUNTIME_DATABASE_UNBOUND"
    env["WOLF15_PAIR_ACTIVITY_DATABASE_URL"] = "never-connected"
    assert activity_runtime_from_environment(env).snapshot()["reason_code"] == "ACTIVITY_RUNTIME_DEPLOYMENT_MISMATCH"


@pytest.mark.parametrize(
    "override",
    [
        {"execution_authority": True},
        {"environment_class": "LIVE"},
        {"ssot_sha256": "wrong"},
        {"recovery_overlap_seconds": -1},
    ],
)
def test_binding_rejects_authority_and_unbound_identity(override):
    with pytest.raises(ValidationError):
        binding(**override)


def test_live_caller_persists_enriched_fact_and_exposes_runtime_reason(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ID", "deployment-test")
    runtime = Mock()
    runtime.snapshot.return_value = {
        "status": "RECOVERY_REQUIRED",
        "reason_code": "RAW_DURABILITY_WRITE_FAILED",
        "execution_authority": False,
    }
    caller = SignalThrottleLiveAnalyzer(pair_activity_runtime=runtime)
    caller.record_allowed(symbol="EURUSD", verdict="EXECUTE_BUY", timestamp=START, observation_id="source-1")
    persisted = runtime.record.call_args.args[0]
    assert persisted.deployment_id == "deployment-test"
    assert persisted.scanner_cycle_id and persisted.source_observation_id == "source-1"
    assert caller.snapshot()["pair_activity_v31"]["reason_code"] == "RAW_DURABILITY_WRITE_FAILED"


def test_real_producer_twins_share_observation_but_preserve_two_raw_facts(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ID", "deployment-test")
    caller = SignalThrottleLiveAnalyzer()
    caller.record_throttled(symbol="EURUSD", verdict="EXECUTE_BUY", timestamp=START, observation_id="source-twin")
    normalized = normalize_pair_activity_observations(caller._events)
    assert normalized.raw_event_count == 2
    assert normalized.logical_observation_count == 1
    caller.record_throttled(symbol="EURUSD", verdict="EXECUTE_BUY", timestamp=START, observation_id="source-twin")
    replay = normalize_pair_activity_observations(caller._events)
    assert replay.raw_event_count == 2 and replay.logical_observation_count == 1
    assert replay.duplicate_delivery_count == 2


def test_distinct_real_producer_calls_at_same_time_remain_distinct(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ID", "deployment-test")
    caller = SignalThrottleLiveAnalyzer()
    for source_id in ("one", "two"):
        caller.record_allowed(symbol="EURUSD", verdict="EXECUTE_BUY", timestamp=START, observation_id=source_id)
    normalized = normalize_pair_activity_observations(caller._events)
    assert normalized.logical_observation_count == normalized.raw_event_count == 2


@pytest.mark.parametrize("method", ["record_allowed", "record_throttled", "record_downgraded"])
@pytest.mark.parametrize("source_id", ["", "   ", 42, "x" * 201])
def test_invalid_explicit_producer_identity_is_rejected_before_runtime_write(method, source_id):
    runtime = Mock()
    caller = SignalThrottleLiveAnalyzer(pair_activity_runtime=runtime)
    with pytest.raises(ValueError, match="source observation identity"):
        getattr(caller, method)(symbol="EURUSD", verdict="EXECUTE_BUY", timestamp=START, observation_id=source_id)
    runtime.record.assert_not_called()
    assert not caller._events


def test_raw_emit_parse_replay_preserves_explicit_identity_and_source_time(monkeypatch, caplog):
    from datetime import timedelta

    from analysis.signal_throttle_log_analyzer import parse_signal_throttle_rows

    monkeypatch.setenv("DEPLOYMENT_ID", "deployment-test")
    monkeypatch.setenv("SIGNAL_THROTTLE_RAW_SAMPLE_SECONDS", "0")
    monkeypatch.setenv("SIGNAL_THROTTLE_RAW_LOG_ENABLED", "true")
    caller = SignalThrottleLiveAnalyzer()
    calls = [
        (0, "record_allowed", "EXECUTE_BUY"),
        (150, "record_throttled", "EXECUTE_SELL"),
        (300, "record_downgraded", "EXECUTE_BUY"),
    ]
    for second, method, verdict in calls:
        getattr(caller, method)(
            symbol="EURUSD",
            verdict=verdict,
            timestamp=START + timedelta(seconds=second),
            observation_id=f" source {second} ",
        )
    rows = [
        {"timestamp": (START + timedelta(hours=1)).isoformat(), "message": record.getMessage()}
        for record in caplog.records
        if "source_observation_schema" in record.getMessage()
    ]
    restored = parse_signal_throttle_rows(rows)
    original = normalize_pair_activity_observations(caller._events)
    replay = normalize_pair_activity_observations(restored)
    assert len(rows) == len(restored) == original.raw_event_count == 4
    assert replay.raw_population_hash == original.raw_population_hash
    assert replay.logical_observations == original.logical_observations
    assert replay.logical_observation_count == 3
    assert [event.timestamp for event in restored] == [event.timestamp for event in caller._events]


@pytest.mark.parametrize(
    "metadata",
    [
        {"source_observation_id": "", "source_observation_schema": "signal-throttle-observation.v1"},
        {"source_observation_id": "one"},
        {"source_observation_schema": "signal-throttle-observation.v1"},
        {"source_observation_id": "one", "source_observation_schema": "unsupported.v2"},
        {
            "source_observation_id": "one",
            "source_observation_schema": "signal-throttle-observation.v1",
            "source_observed_at_utc": "not-a-time",
        },
        {
            "source_observation_id": "one",
            "source_observation_schema": "signal-throttle-observation.v1",
            "source_observed_at_utc": "2026-09-09T00:00:00",
        },
    ],
)
def test_raw_parser_does_not_silently_drop_invalid_source_metadata(metadata):
    import json

    from analysis.signal_throttle_log_analyzer import parse_signal_throttle_row

    row = {
        "timestamp": START.isoformat(),
        "message": "[SignalThrottle] EURUSD allowed - verdict EXECUTE_BUY " + json.dumps(metadata),
    }
    with pytest.raises(ValueError, match="source observation"):
        parse_signal_throttle_row(row)
