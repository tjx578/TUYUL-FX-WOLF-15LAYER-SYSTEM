"""Canonical reducer and safety gates for durable Microboost P2."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_microboost_pulse_engine import MicroboostPulseEngine, MicroboostPulsePolicy
from analysis.strategy_5scr_v3.pressure.legacy_580_adapter import Legacy580PressureAdapter
from analysis.strategy_5scr_v3.pressure.live_outbox_adapter import LivePressureOutboxAdapter
from contracts.strategy_5scr_microboost_pulse import MicroboostState
from storage.strategy_5scr_microboost_v1_repository import MicroboostV1RuntimeConfig
from tests.pressure_emission_v3_helpers import live_envelope, load_fixture

LIFECYCLE = "5scr-lifecycle:11111111111111111111111111111111"
START = datetime(2026, 7, 17, 13, 5, tzinfo=UTC)


def _emission(
    *,
    at: datetime = START,
    detected: bool = True,
    ticks: int = 7,
    block: str = "CHFJPY:clean:block-a",
    direction: str = "SELL",
    context_hash: str = "sha256:" + "b" * 64,
    stage: str = "MICROBOOST",
    family: str = "REPEATED_MICROBOOST",
    deployment_id: str = "deploy-a",
    commit_sha: str = "a" * 40,
):
    payload = load_fixture("live_equivalents", "equivalent_chfjpy.json")
    payload.update(
        {
            "signal_valid_time_utc": at.isoformat(),
            "microboost_detected": detected,
            "effective_ticks": ticks,
            "source_clean_block_id": block,
            "raw_direction": direction,
            "candidate_direction": direction,
            "watch_direction": direction,
            "block_direction": direction,
            "material_context_hash": context_hash,
            "source_stage": stage,
            "source_family": family,
            "deployment_id": deployment_id,
            "commit_sha": commit_sha,
        }
    )
    return LivePressureOutboxAdapter().normalize(live_envelope(payload))


def test_canonical_sticky_true_is_one_formed_pulse() -> None:
    engine = MicroboostPulseEngine(LIFECYCLE, "CHFJPY")

    for offset in range(100):
        engine.ingest_canonical(_emission(at=START + timedelta(seconds=offset)))

    assert [pulse.transition for pulse in engine.pulses] == ["FORMED"]
    assert engine.state.independent_pulse_count == 1
    assert engine.state.reinforcement_count == 0
    assert engine.state.observed_snapshot_count == 100
    assert engine.state.carried_snapshot_count == 99


def test_synthetic_580_legacy_cohort_is_not_580_pulses() -> None:
    engine = MicroboostPulseEngine(LIFECYCLE, "CHFJPY")
    adapter = Legacy580PressureAdapter()
    payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    base = adapter.normalize(
        {
            "message": "WARNING signal_json [SignalPressureStateJSON] " + json.dumps(payload, separators=(",", ":")),
            "timestamp": START.isoformat(),
        }
    )

    for offset in range(580):
        at = START + timedelta(seconds=offset)
        emission = base.model_copy(
            update={
                "identity": base.identity.model_copy(
                    update={
                        "transport_event_id": f"legacy-580:{offset:04d}",
                        "source_payload_hash": "sha256:" + hashlib.sha256(str(offset).encode()).hexdigest(),
                    }
                ),
                "time": base.time.model_copy(update={"event_time_utc": at}),
            }
        )
        engine.ingest_canonical(emission)

    assert [pulse.transition for pulse in engine.pulses] == ["FORMED"]
    assert engine.state.independent_pulse_count == 1
    assert engine.state.carried_snapshot_count == 579


def test_broad_p1_semantic_hash_change_is_not_automatic_reinforcement() -> None:
    first = _emission(context_hash="sha256:" + "a" * 64)
    second = _emission(
        at=START + timedelta(seconds=120),
        context_hash="sha256:" + "c" * 64,
    )
    assert first.identity.semantic_projection_hash != second.identity.semantic_projection_hash

    engine = MicroboostPulseEngine(LIFECYCLE, "CHFJPY")
    assert [item.transition for item in engine.ingest_canonical(first)] == ["FORMED"]
    assert engine.ingest_canonical(second) == ()
    assert engine.state.reinforcement_count == 0


def test_context_only_change_after_expiry_does_not_rearm_sticky_pulse() -> None:
    first = _emission(context_hash="sha256:" + "a" * 64)
    context_changed = _emission(
        at=START + timedelta(seconds=301),
        context_hash="sha256:" + "c" * 64,
    )
    repeated = _emission(
        at=START + timedelta(seconds=302),
        context_hash="sha256:" + "d" * 64,
    )
    assert first.identity.semantic_projection_hash != context_changed.identity.semantic_projection_hash

    engine = MicroboostPulseEngine(
        LIFECYCLE,
        "CHFJPY",
        policy=MicroboostPulsePolicy(ttl_seconds=300.0),
    )
    engine.ingest_canonical(first)
    boundary = engine.ingest_canonical(context_changed)

    assert [item.transition for item in boundary] == ["EXPIRED"]
    assert engine.ingest_canonical(repeated) == ()
    assert engine.state.state == "EXPIRED"
    assert engine.state.independent_pulse_count == 1


def test_publisher_and_context_refresh_stay_expired_across_restart() -> None:
    first = _emission(
        stage="MICROBOOST",
        family="REPEATED_MICROBOOST",
        context_hash="sha256:" + "a" * 64,
        deployment_id="deploy-a",
        commit_sha="a" * 40,
    )
    boundary = _emission(
        at=START + timedelta(seconds=301),
        stage="SIGNAL_THROTTLE_INTEL",
        family="PRESSURE_REFRESH",
        context_hash="sha256:" + "b" * 64,
        deployment_id="deploy-b",
        commit_sha="b" * 40,
    )
    later_publishers = (
        _emission(
            at=START + timedelta(seconds=302),
            stage="BLOCK_FINALIZER",
            family="BLOCK_REFRESH",
            context_hash="sha256:" + "c" * 64,
            deployment_id="deploy-c",
            commit_sha="c" * 40,
        ),
        _emission(
            at=START + timedelta(seconds=303),
            stage="EXECUTION_GATE",
            family="GATE_REFRESH",
            context_hash="sha256:" + "d" * 64,
            deployment_id="deploy-d",
            commit_sha="d" * 40,
        ),
    )

    engine = MicroboostPulseEngine(
        LIFECYCLE,
        "CHFJPY",
        policy=MicroboostPulsePolicy(ttl_seconds=300.0),
    )
    formed = engine.ingest_canonical(first)
    expired = engine.ingest_canonical(boundary)
    assert formed[0].source_deployment_id == "deploy-a"
    assert formed[0].source_stage == "MICROBOOST"
    assert formed[0].source_family == "REPEATED_MICROBOOST"
    assert [item.transition for item in expired] == ["EXPIRED"]
    assert expired[0].source_deployment_id == "deploy-b"
    assert expired[0].source_stage == "SIGNAL_THROTTLE_INTEL"
    assert expired[0].source_family == "PRESSURE_REFRESH"

    restarted = MicroboostPulseEngine(
        LIFECYCLE,
        "CHFJPY",
        policy=MicroboostPulsePolicy(ttl_seconds=300.0),
        initial_state=engine.state,
    )
    for emission in later_publishers:
        assert restarted.ingest_canonical(emission) == ()

    assert restarted.state.state == "EXPIRED"
    assert restarted.state.independent_pulse_count == 1


def test_recovered_state_rejects_duplicate_and_continues_deterministically() -> None:
    first = _emission()
    carried = _emission(at=START + timedelta(seconds=30))
    reinforced = _emission(at=START + timedelta(seconds=120), ticks=25)

    continuous = MicroboostPulseEngine(LIFECYCLE, "CHFJPY")
    continuous.ingest_canonical(first)
    continuous.ingest_canonical(carried)
    continuous.ingest_canonical(reinforced)

    before_restart = MicroboostPulseEngine(LIFECYCLE, "CHFJPY")
    before_restart.ingest_canonical(first)
    before_restart.ingest_canonical(carried)
    recovered_state = before_restart.state

    restarted = MicroboostPulseEngine(
        LIFECYCLE,
        "CHFJPY",
        initial_state=recovered_state,
    )
    assert restarted.ingest_canonical(carried) == ()
    assert restarted.state == recovered_state
    restarted.ingest_canonical(reinforced)

    assert restarted.state == continuous.state
    assert [item.transition for item in restarted.pulses] == ["REINFORCED"]


def test_pulse_and_state_are_non_executable_authority() -> None:
    engine = MicroboostPulseEngine(LIFECYCLE, "CHFJPY")
    engine.ingest_canonical(_emission())

    assert engine.state.valid_for_execution is False
    assert engine.state.execution_authority is False
    assert all(item.valid_for_execution is False for item in engine.pulses)
    assert all(item.execution_authority is False for item in engine.pulses)


def test_noncanonical_lifecycle_identity_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MicroboostState(strategy_lifecycle_id="clean-block-is-not-authority", symbol="CHFJPY")


def test_runtime_config_defaults_off_and_requires_shadow_only() -> None:
    default = MicroboostV1RuntimeConfig.from_env({})
    assert default == MicroboostV1RuntimeConfig(enabled=False, shadow_only=True)
    default.validate()

    enabled = MicroboostV1RuntimeConfig.from_env(
        {
            "STRATEGY_5SCR_MICROBOOST_V1_WRITER_ENABLED": "true",
            "STRATEGY_5SCR_MICROBOOST_V1_SHADOW_ONLY": "false",
        }
    )
    with pytest.raises(RuntimeError, match="MICROBOOST_V1_SHADOW_ONLY_REQUIRED"):
        enabled.validate()
