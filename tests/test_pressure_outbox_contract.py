from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from analysis.signal_pressure_state_emitter import (
    build_signal_pressure_state_payload,
    emit_signal_pressure_state,
)
from analysis.strategy_5scr_pressure_to_tradeplan import (
    PressureEventNormalizer,
    replay_pressure_outbox_events,
)
from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from storage.pressure_outbox import (
    PressureOutboxContractError,
    prepare_pressure_event,
    pressure_payload_hash,
)


def _raw_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "EURUSD",
        "source_clean_block_id": "EURUSD:clean:20260720T010000Z",
        "pair_admission_id": "5scr-admission:0123456789abcdef0123456789abcdef",
        "pair_admission_status": "GRANTED",
        "pair_admission_rule_version": "5scr.pair-admission.raw-ledger.v2",
        "pair_admission_granted_at_utc": "2026-07-20T01:05:00+00:00",
        "pair_admission_expires_at_utc": "2026-07-20T01:20:00+00:00",
        "pair_admission_source_ledger_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "radar_manifest_id": "5scr-radar:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "radar_status": "ANALYSIS_READY",
        "pressure_selection_confirmed": True,
        "cluster_id": "EURUSD_CLUSTER_1",
        "signal_valid_time_utc": "2026-07-20T01:05:00+00:00",
        "promotion_stage": "PRESSURE_ONLY",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "pressure_seen": True,
        "pair_eligible_for_analysis": True,
        "pressure_event_count": 5,
        "raw_direction": "BUY",
    }
    payload.update(updates)
    return payload


def _envelope(payload: dict[str, object]) -> PressureOutboxEnvelope:
    prepared = prepare_pressure_event(payload)
    stored_payload = {**prepared.payload, "lifecycle_sequence": 1}
    now = datetime(2026, 7, 20, 1, 5, tzinfo=UTC)
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


def test_pressure_identity_is_deterministic_and_non_executable() -> None:
    first = prepare_pressure_event(_raw_payload())
    second = prepare_pressure_event(_raw_payload())

    assert first.event_id == second.event_id
    assert first.outbox_id == second.outbox_id
    assert first.payload_hash == second.payload_hash
    assert first.lifecycle_id == "5scr-admission:0123456789abcdef0123456789abcdef"
    assert first.payload["final_direction"] == "WAIT"
    assert first.payload["valid_for_execution"] is False
    assert first.payload["execution_valid_now"] is False
    assert first.payload["is_final_signal"] is False


def test_pressure_hash_ignores_runtime_and_transport_but_not_semantics() -> None:
    base = _raw_payload()
    runtime_variant = {
        **base,
        "deployment_id": "deploy-2",
        "commit_sha": "abc",
        "replica_id": "replica-9",
        "generated_at_utc": "2026-07-20T02:00:00+00:00",
        "event_id": "c49d639d-f1aa-4a32-aa92-1b61aa9b59e1",
        "lifecycle_sequence": 99,
    }
    semantic_variant = {**base, "pressure_event_count": 6}

    assert pressure_payload_hash(base) == pressure_payload_hash(runtime_variant)
    assert pressure_payload_hash(base) != pressure_payload_hash(semantic_variant)


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"source_clean_block_id": None}, "PRESSURE_CANONICAL_LINEAGE_MISSING"),
        ({"pair_admission_status": "NOT_GRANTED"}, "PRESSURE_PAIR_ADMISSION_REQUIRED"),
        ({"pair_admission_id": "forged-admission"}, "PRESSURE_PAIR_ADMISSION_REQUIRED"),
        ({"pair_admission_source_ledger_hash": "sha256:forged"}, "PRESSURE_PAIR_ADMISSION_REQUIRED"),
        ({"pair_admission_rule_version": "legacy"}, "PRESSURE_PAIR_ADMISSION_REQUIRED"),
        ({"pair_admission_expires_at_utc": None}, "PRESSURE_PAIR_ADMISSION_REQUIRED"),
        (
            {"pair_admission_expires_at_utc": "2026-07-20T01:05:00+00:00"},
            "PRESSURE_PAIR_ADMISSION_REQUIRED",
        ),
        (
            {"pair_admission_expires_at_utc": "2026-07-20T01:20:01+00:00"},
            "PRESSURE_PAIR_ADMISSION_REQUIRED",
        ),
        ({"pressure_selection_confirmed": False}, "PRESSURE_RADAR_SELECTION_PROOF_REQUIRED"),
        ({"valid_for_execution": True}, "PRESSURE_EXECUTION_FLAG_TRUE"),
        ({"final_direction": "BUY"}, "PRESSURE_FINAL_DIRECTION_NOT_WAIT"),
        ({"signal_valid_time_utc": None}, "PRESSURE_SIGNAL_VALID_AT_MISSING"),
    ],
)
def test_pressure_outbox_rejects_noncanonical_live_input(updates: dict[str, object], reason: str) -> None:
    with pytest.raises(PressureOutboxContractError, match=reason):
        prepare_pressure_event(_raw_payload(**updates))


def test_outbox_payload_and_observability_log_are_byte_semantically_identical(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deploy-shadow")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "3464baa")
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-shadow")
    canonical = build_signal_pressure_state_payload(_raw_payload())
    envelope = _envelope(canonical)

    caplog.set_level(logging.INFO, logger="signal_json")
    assert emit_signal_pressure_state(envelope.payload)
    message = next(record.message for record in caplog.records if "[SignalPressureStateJSON]" in record.message)
    logged = json.loads(message.split("[SignalPressureStateJSON]", 1)[1].strip())

    assert logged == envelope.payload
    normalized = PressureEventNormalizer(input_mode="LIVE").normalize(logged)
    assert normalized.event_id == str(envelope.event_id)
    assert normalized.campaign_anchor == envelope.lifecycle_id


def test_replay_uses_canonical_outbox_sequence() -> None:
    first = _envelope(_raw_payload())
    second_prepared = prepare_pressure_event(_raw_payload(pressure_event_count=6, cluster_id="EURUSD_CLUSTER_2"))
    second_payload = {**second_prepared.payload, "lifecycle_sequence": 2}
    second = first.model_copy(
        update={
            "outbox_id": second_prepared.outbox_id,
            "event_id": second_prepared.event_id,
            "lifecycle_sequence": 2,
            "signal_valid_at": datetime(2026, 7, 20, 1, 6, tzinfo=UTC),
            "payload": second_payload,
            "payload_hash": second_prepared.payload_hash,
        }
    )

    lifecycles = replay_pressure_outbox_events([second, first])

    assert len(lifecycles) == 1
    assert lifecycles[0].campaign_id == first.lifecycle_id
    assert lifecycles[0].event_ids == (str(first.event_id), str(second.event_id))


def test_replay_rejects_lifecycle_sequence_gap() -> None:
    envelope = _envelope(_raw_payload()).model_copy(
        update={"lifecycle_sequence": 2, "payload": {**_envelope(_raw_payload()).payload, "lifecycle_sequence": 2}}
    )

    with pytest.raises(ValueError, match="PRESSURE_OUTBOX_LIFECYCLE_SEQUENCE_GAP"):
        replay_pressure_outbox_events([envelope])
