"""Synthetic canonical V1 engineering replay, never strategy/DEMO approval.

The raw grant is computed from actual raw-ledger functions. No candidate,
strategy evidence, risk reservation, final signal or command is SQL-seeded.
Only a disposable SHADOW executor/account fixture is seeded. Frozen candle
input uses the existing replay store and the actual closed-candle provider.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_closed_candle_provider import Strategy5SCRClosedCandleEvidenceProvider
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_pressure_radar import PressureRadarAssembler, canonical_radar_payload
from analysis.strategy_5scr_pressure_to_tradeplan import PressureEventNormalizer, PressureLifecycleAccumulator
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population
from analysis.strategy_5scr_replay import FrozenClosedCandleStore
from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    CommandSource,
    SignedExecutionEnvelopeV2,
    SymbolCapability,
    verify_signed_execution_envelope_with_root,
)
from contracts.mt5_operator_shadow import OperatorShadowRequest
from contracts.strategy_5scr_execution_policy import FX_LEGACY_6P_V1
from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from execution.execution_plane_flags import ExecutionPlaneFlags
from execution.mt5_operator_shadow_wiring import OperatorControlledShadowAuthorityV1
from execution.mt5_risk_command_producer import MT5RiskCommandProducer
from services.pressure_outbox.evidence_worker import (
    EvidenceRuntimeConfig,
    PostgresEvidenceRepository,
    Strategy5SCREvidenceWorker,
)
from storage.pair_admission_evaluations import PairAdmissionEvaluationRepository
from storage.pressure_outbox import PressureOutboxRepository, prepare_pressure_event
from storage.pressure_outbox_worker import PressureOutboxWorker
from storage.pressure_radar_manifest import PressureRadarManifestRepository
from storage.strategy_5scr_pressure_inbox import Strategy5SCRInboxConsumer, Strategy5SCRPressureProcessor
from storage.strategy_5scr_risk_reservation_repository import Strategy5SCRRiskReservationRepository
from tests.integration.test_5scr_risk_reservation_postgres import _PoolBackedPostgres, _snapshot
from tests.test_pressure_radar_manifest_repository import _qualifying_payload
from tests.test_strategy_5scr_closed_candle_evidence import DECISION_AT
from tests.test_strategy_5scr_closed_candle_evidence import _snapshot as _candle_snapshot

pytest_plugins = ("tests.integration.test_5scr_risk_reservation_postgres",)

START = datetime(2026, 7, 20, 5, 50, tzinfo=UTC)
DEPLOYMENT = "SYNTHETIC_DISPOSABLE_P5_V1_REPLAY"
SYMBOL = "NZDUSD"
EXECUTOR = UUID("deaf9500-6330-47b3-a0a1-c79c1c39919a")
ACCOUNT = "synthetic-p5-v1-no-broker"
COMMAND_SECRET = "synthetic-p5-v1-local-signing-fixture-only"
COMMAND_KEY = "synthetic-p5-v1.key"
RULE_TUPLE = {
    "pair_admission": "5scr.pair-admission.raw-ledger.v2",
    "strategy": "5scr.final.2026-07-19",
    "execution_policy": "FX_LEGACY_6P_V1",
    "risk_policy": "5scr.production-adjusted.parent-only.v1",
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _raw_events() -> tuple[SignalThrottleLogEvent, ...]:
    return tuple(
        SignalThrottleLogEvent(
            timestamp=START + timedelta(seconds=seconds),
            severity="warning",
            message="SYNTHETIC_DISPOSABLE_TEST raw observation; no broker",
            symbol=SYMBOL,
            event_type="ALLOWED",
            verdict="EXECUTE_BUY",
            direction="BUY",
            pressure_source="SignalThrottle",
            source_stream="ALLOWED",
            deployment_id=DEPLOYMENT,
            scanner_cycle_id=f"SYNTHETIC_SCAN_{seconds}",
            eligible_for_pressure_block=True,
            eligible_for_execution=False,
        )
        for seconds in (0, 150, 300)
    )


def _fixture() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    events = _raw_events()
    population = build_raw_admission_population(events)
    clean_id = f"{SYMBOL}_{START:%Y%m%dT%H%M%SZ}_{START + timedelta(minutes=5):%Y%m%dT%H%M%SZ}"
    audit = build_pair_admission_audit(
        population.blocks,
        raw_events=population.events,
        clean_block_ids={(SYMBOL, START.isoformat(), (START + timedelta(minutes=5)).isoformat()): clean_id},
    )
    assert len(audit.grants) == 1, audit.to_payload()
    grant = audit.grants[0]
    qualifying = _qualifying_payload(
        deployment_id=DEPLOYMENT,
        replica_id="SYNTHETIC_REPLAY_ONLY",
        commit_sha=os.getenv("WOLF15_P5_REPLAY_SOURCE_COMMIT", "3760cef17be097855e9491db164618fadfb89517"),
        symbol=SYMBOL,
        cluster_id=f"{SYMBOL}:synthetic-qualifying",
        signal_valid_time_utc=(START + timedelta(seconds=150)).isoformat(),
        generated_at_utc=(START + timedelta(seconds=151)).isoformat(),
        raw_direction_expires_at_utc=(START + timedelta(hours=4)).isoformat(),
        pressure_seen=True,
        pressure_event_count=3,
    )
    lineage = dict(qualifying)
    lineage.update(
        cluster_id=f"{SYMBOL}:synthetic-raw-lineage",
        signal_valid_time_utc=(START + timedelta(minutes=6)).isoformat(),
        generated_at_utc=(START + timedelta(minutes=6, seconds=1)).isoformat(),
        source_stage="SIGNAL_THROTTLE_INTEL",
        current_block_effective_ticks=1,
        source_clean_block_id=clean_id,
        pair_admission_grant=grant.model_dump(mode="json"),
    )
    return audit, qualifying, lineage


def _provider() -> Strategy5SCRClosedCandleEvidenceProvider:
    candles = tuple(c for batch in _candle_snapshot().values() for c in batch)
    return Strategy5SCRClosedCandleEvidenceProvider(FrozenClosedCandleStore(candles), mode="SHADOW")


def _pure_envelope() -> tuple[Any, PressureOutboxEnvelope]:
    audit, qualifying, lineage = _fixture()
    assembler = PressureRadarAssembler()
    assert assembler.ingest(qualifying).transition == "WAITING_CANONICAL_LINEAGE"
    ready = assembler.ingest(lineage)
    assert ready.transition == "ANALYSIS_READY" and ready.manifest is not None
    prepared = prepare_pressure_event(canonical_radar_payload(ready.manifest, qualifying))
    return audit, PressureOutboxEnvelope(
        outbox_id=UUID("42698d19-1253-46ee-89b7-d15183519b64"),
        event_id=prepared.event_id,
        schema_version=prepared.schema_version,
        symbol=prepared.symbol,
        lifecycle_id=prepared.lifecycle_id,
        lifecycle_sequence=1,
        source_clean_block_id=prepared.source_clean_block_id,
        source_watch_id=prepared.source_watch_id,
        signal_valid_at=prepared.signal_valid_at,
        payload={**prepared.payload, "lifecycle_sequence": 1},
        payload_hash=prepared.payload_hash,
    )


@pytest.mark.asyncio
async def test_frozen_raw_fixture_reaches_ready_without_legacy_episode_coercion() -> None:
    audit, envelope = _pure_envelope()
    event = PressureEventNormalizer(input_mode="LIVE").normalize(envelope.payload)
    lifecycle, _ = PressureLifecycleAccumulator().ingest(event)
    assert lifecycle.input_mode == "LIVE"
    assert lifecycle.campaign_anchor_source == "PAIR_ADMISSION_ID"
    assert lifecycle.campaign_anchor_execution_grade is True
    assert lifecycle.campaign_id == audit.grants[0].pair_admission_id == envelope.lifecycle_id
    evidence = await _provider().provide(
        symbol=SYMBOL, decision_at_utc=DECISION_AT, lifecycle_anchor_utc=lifecycle.started_at_utc
    )
    assert evidence is not None
    outcome = Strategy5SCRPressureProcessor(execution_policy=FX_LEGACY_6P_V1).process(envelope, evidence=evidence)
    assert outcome.decision == "READY", outcome.reasons
    assert outcome.candidate_payload is not None
    candidate = outcome.candidate_payload
    assert candidate["strategy_rule_version"] == RULE_TUPLE["strategy"]
    assert candidate["tradeplan_preview"]["execution_policy_id"] == RULE_TUPLE["execution_policy"]
    assert candidate["evidence_snapshot_id"] == evidence.evidence_snapshot_id
    assert candidate["valid_for_execution"] is False
    assert candidate["strategy_5scr"]["out_of_sample_status"] == "NOT_YET_VALIDATED"
    assert len(evidence.source_candles) > 0
    assert max(evidence.source_candle_close_times) <= DECISION_AT


def test_mixed_deployment_raw_evidence_cannot_create_admission() -> None:
    events = _raw_events()
    population = build_raw_admission_population(events)
    mixed = (events[0], replace(events[1], deployment_id="OTHER_SYNTHETIC_DEPLOYMENT"), events[2])
    rejected = build_pair_admission_audit(population.blocks, raw_events=mixed)
    assert rejected.grants == ()


async def _seed_shadow_executor(pg: _PoolBackedPostgres) -> None:
    base = _snapshot(EXECUTOR, ACCOUNT).model_dump(mode="python")
    base.update(
        captured_at_utc=DECISION_AT,
        symbols=[
            SymbolCapability(
                canonical_symbol=SYMBOL,
                broker_symbol=SYMBOL,
                digits=5,
                point=0.00001,
                tick_size=0.00001,
                tick_value_profit=1.0,
                tick_value_loss=1.0,
                volume_min=0.01,
                volume_max=50.0,
                volume_step=0.01,
                stops_level_points=0,
                freeze_level_points=0,
                expiration_modes=["SPECIFIED"],
            )
        ],
    )
    snapshot = AccountSnapshotV1.model_validate(base)
    await pg.execute(
        """INSERT INTO ea_agents (id,agent_name,ea_class,ea_subtype,execution_mode,reporter_mode,status,locked)
        VALUES ($1::uuid,'SYNTHETIC_NO_BROKER','PRIMARY','EDUMB','SHADOW','FULL','OFFLINE',false)""",
        str(EXECUTOR),
    )
    await pg.execute(
        """INSERT INTO executor_instances (
        executor_id,account_id,login_hash,broker_server,terminal_build,ea_version,protocol_version,
        execution_mode,status,last_heartbeat_at)
        VALUES ($1::uuid,$2,$3,'SYNTHETIC_NO_BROKER',5000,'SYNTHETIC','wolf15.mt5.exec.v1','SHADOW','ONLINE',$4)""",
        str(EXECUTOR),
        ACCOUNT,
        "sha256:" + "a" * 64,
        DECISION_AT,
    )
    await pg.execute(
        """INSERT INTO executor_account_snapshots (
        snapshot_id,executor_id,account_id,captured_at,balance,equity,floating_pnl,used_margin,free_margin,
        margin_level_pct,margin_mode,trade_allowed,autotrading_enabled,payload)
        VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)""",
        snapshot.snapshot_id,
        str(EXECUTOR),
        ACCOUNT,
        snapshot.captured_at_utc,
        snapshot.balance,
        snapshot.equity,
        snapshot.floating_pnl,
        snapshot.used_margin,
        snapshot.free_margin,
        snapshot.margin_level_pct,
        snapshot.margin_mode.value,
        snapshot.trade_allowed,
        snapshot.autotrading_enabled,
        _json(snapshot.model_dump(mode="json")),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_canonical_raw_to_durable_shadow_command_one_lineage(postgres: _PoolBackedPostgres) -> None:
    from tests.integration.postgres_test_guard import verify_operational_tables_empty

    async with postgres._pool.acquire() as connection:
        await verify_operational_tables_empty(connection)
    audit, qualifying, lineage = _fixture()
    grant = audit.grants[0]
    await PairAdmissionEvaluationRepository(pg=cast(Any, postgres)).ingest(audit.evaluations[0])
    radar = PressureRadarManifestRepository(pg=cast(Any, postgres))
    assert (await radar.ingest(qualifying)).transition == "WAITING_CANONICAL_LINEAGE"
    ready = await radar.ingest(lineage)
    assert ready.transition == "ANALYSIS_READY" and ready.envelope is not None and ready.manifest is not None
    envelope = ready.envelope
    assert envelope.lifecycle_id == grant.pair_admission_id
    processor = Strategy5SCRPressureProcessor(execution_policy=FX_LEGACY_6P_V1)
    consumer = Strategy5SCRInboxConsumer(pg=cast(Any, postgres), processor=processor)
    dispatcher = PressureOutboxWorker(
        worker_id="synthetic-p5-v1-dispatcher",
        repository=PressureOutboxRepository(pg=cast(Any, postgres)),
        consumer=consumer,
        master_enabled=True,
        dispatch_enabled=True,
        consumer_enabled=True,
        batch_size=1,
    )
    assert await dispatcher.process_once() == 1
    waiting = await postgres.fetchrow(
        "SELECT status FROM strategy_5scr_inbox WHERE event_id=$1::uuid", str(envelope.event_id)
    )
    assert waiting is not None and waiting["status"] == "WAITING_EVIDENCE"
    worker = Strategy5SCREvidenceWorker(
        repository=PostgresEvidenceRepository(pg=cast(Any, postgres)),
        provider=_provider(),
        processor=processor,
        config=EvidenceRuntimeConfig(enabled=True, live_allowed=True, activation_requested=True),
        clock=lambda: DECISION_AT,
    )
    assert await worker.process_once() == 1
    candidate_row = await postgres.fetchrow(
        "SELECT * FROM strategy_5scr_tradeplan_candidates WHERE event_id=$1::uuid", str(envelope.event_id)
    )
    inbox = await postgres.fetchrow("SELECT * FROM strategy_5scr_inbox WHERE event_id=$1::uuid", str(envelope.event_id))
    assert candidate_row is not None, dict(inbox or {})
    candidate = json.loads(candidate_row["payload"])
    assert candidate["strategy_rule_version"] == RULE_TUPLE["strategy"]
    assert candidate["tradeplan_preview"]["execution_policy_id"] == RULE_TUPLE["execution_policy"]
    assert candidate["valid_for_execution"] is False
    assert candidate["source_pressure_event_ids"] == [str(envelope.event_id)]
    assert inbox is not None and inbox["status"] == "PROCESSED"
    assert inbox["evidence_snapshot_id"] == candidate_row["evidence_snapshot_id"] == candidate["evidence_snapshot_id"]
    assert hashlib.sha256(_json(candidate).encode()).hexdigest() == candidate_row["payload_hash"]
    tradeplan_id = str(candidate_row["tradeplan_id"])
    await _seed_shadow_executor(postgres)
    flags = ExecutionPlaneFlags(
        execution_enabled=True,
        signed_command_bridge_enabled=True,
        execution_command_producer_enabled=True,
        risk_reservation_enabled=True,
        trade_outbox_write_enabled=True,
        ea_command_delivery_enabled=True,
        mt5_order_send_enabled=False,
    )
    governance = await postgres.fetchrow("SELECT * FROM executor_bridge_governance WHERE singleton_id=1")
    assert governance is not None and governance["kill_switch_active"] is True
    commands = MT5RiskCommandProducer(
        pg=cast(Any, postgres),
        flags=flags,
        clock=lambda: DECISION_AT,
        environ={"EXECUTOR_COMMAND_SIGNING_SECRET": COMMAND_SECRET, "EXECUTOR_COMMAND_SIGNING_KEY_ID": COMMAND_KEY},
    )
    authority = OperatorControlledShadowAuthorityV1(
        pg=cast(Any, postgres),
        flags=flags,
        commands=commands,
        clock=lambda: DECISION_AT,
        reservations=Strategy5SCRRiskReservationRepository(pg=cast(Any, postgres), clock=lambda: DECISION_AT),
    )
    request = OperatorShadowRequest(
        operator_run_id="synthetic-p5-v1-once",
        confirm_run_id="synthetic-p5-v1-once",
        actor="operator:disposable-test-only",
        reason="Synthetic canonical V1 engineering replay; no DEMO authority",
        tradeplan_id=tradeplan_id,
        executor_id=EXECUTOR,
        broker_symbol=SYMBOL,
        expected_governance_version=int(governance["governance_version"]),
        requested_at_utc=DECISION_AT,
        expires_at_utc=DECISION_AT + timedelta(minutes=5),
    )
    manifest = await authority.issue(request)
    assert manifest.execution_mode == "SHADOW" and manifest.broker_execution == "FORBIDDEN"
    assert await authority.issue(request) == manifest
    assert await worker.process_once() == 0
    assert (await consumer.consume(envelope)).duplicate is True
    assert await commands.produce_next() is None
    row = await postgres.fetchrow(
        """SELECT c.*, r.state AS reservation_state, r.policy_id AS reservation_policy,
        o.status AS outbox_status, e.payload AS evidence_payload, e.payload_hash AS evidence_hash,
        p.payload_hash AS candidate_hash, p.lifecycle_id AS canonical_lifecycle_id
        FROM execution_commands c
        JOIN strategy_5scr_risk_reservations r ON r.reservation_id=c.risk_reservation_id
        JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id=r.reservation_id
        JOIN strategy_5scr_tradeplan_candidates p ON p.tradeplan_id=r.tradeplan_id
        JOIN strategy_5scr_evidence_snapshots e ON e.snapshot_id=p.evidence_snapshot_id
        WHERE c.command_id=$1::uuid""",
        str(manifest.command_id),
    )
    assert row is not None
    assert row["canonical_lifecycle_id"] == grant.pair_admission_id
    assert (row["state"], row["reservation_state"], row["outbox_status"]) == ("QUEUED", "CONSUMED", "PUBLISHED")
    assert row["reservation_policy"] == RULE_TUPLE["risk_policy"]
    wire = SignedExecutionEnvelopeV2.model_validate(
        {
            "wire_version": row["wire_format"],
            "payload_encoding": row["payload_encoding"],
            "payload_b64": row["signed_payload_b64"],
            "payload_sha256": row["signed_payload_sha256"],
            "algorithm": row["signature_algorithm"],
            "key_id": row["signature_key_id"],
            "executor_id": row["executor_id"],
            "signature": row["signature_value"],
        }
    )
    command = verify_signed_execution_envelope_with_root(wire, root_secret=COMMAND_SECRET)
    assert command.executor_binding.execution_mode.value == "SHADOW"
    assert isinstance(command.source, CommandSource)
    assert command.source.strategy_rule_version == RULE_TUPLE["strategy"]
    assert command.source.campaign_id == command.source.lifecycle_anchor == grant.pair_admission_id
    counts = await postgres.fetchrow("""SELECT
        (SELECT count(*) FROM execution_commands) AS commands,
        (SELECT count(*) FROM strategy_5scr_risk_reservations) AS reservations,
        (SELECT count(*) FROM strategy_5scr_final_signal_outbox) AS final_signals,
        (SELECT count(*) FROM execution_reports) AS execution_reports,
        (SELECT count(*) FROM broker_entities) AS broker_entities""")
    assert counts is not None and dict(counts) == {
        "commands": 1,
        "reservations": 1,
        "final_signals": 1,
        "execution_reports": 0,
        "broker_entities": 0,
    }
    saved_evidence = json.loads(row["evidence_payload"])
    assert len(saved_evidence["source_candles"]) > 0
    assert hashlib.sha256(_json(saved_evidence).encode()).hexdigest() == row["evidence_hash"]
    result = {
        "evidence_class": "SYNTHETIC_DISPOSABLE_ENGINEERING_REPLAY",
        "rule_tuple": RULE_TUPLE,
        "raw_events": [asdict(event) for event in _raw_events()],
        "grant": grant.model_dump(mode="json"),
        "evaluation": audit.evaluations[0],
        "radar_manifest": ready.manifest.model_dump(mode="json"),
        "envelope": envelope.model_dump(mode="json"),
        "evidence": saved_evidence,
        "candidate": candidate,
        "candidate_hash": row["candidate_hash"],
        "operator_manifest": manifest.model_dump(mode="json"),
        "command": command.model_dump(mode="json"),
        "counts": dict(counts),
        "broker_effects": "ZERO_LOCAL_ISOLATED_NO_BROKER_PROCESS",
        "natural_runtime": "NOT_PROVEN",
        "strategy_oos": "NOT_YET_VALIDATED",
        "demo_authority": "NOT_GRANTED",
        "v2_handoff": "NOT_IN_SELECTED_RELEASE_HISTORICAL_ADAPTER_REVIEW_PENDING",
    }
    receipt_path = os.getenv("WOLF15_P5_REPLAY_RECEIPT")
    assert receipt_path, "isolated runner must supply a persistent replay receipt path"
    with Path(receipt_path).open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2, default=str) + "\n")
