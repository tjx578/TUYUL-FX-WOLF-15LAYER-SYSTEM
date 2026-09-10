from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import storage.strategy_5scr_analysis_admission_v1_repository as admission_repository
from analysis.signal_pressure_state_emitter import build_signal_pressure_state_payload
from analysis.strategy_5scr_analysis_admission import evaluate_strategy_analysis_admission
from analysis.strategy_5scr_v3.episode_grouping import EpisodeEvent
from analysis.strategy_5scr_v3.episode_reducer import MarketEpisodeReducer
from contracts.strategy_5scr import H1Confirmation, M1ExecutionBox, M15Confirmation
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence
from execution.execution_plane_flags import EXECUTION_PLANE_FLAGS, TRUE_VALUES
from services.pressure_outbox.analysis_admission_v1_worker import (
    StrategyAnalysisAdmissionRuntimeConfig,
    StrategyAnalysisAdmissionV1Worker,
    build_analysis_evidence_snapshot_v1,
)
from storage.strategy_5scr_analysis_admission_v1_repository import (
    AnalysisAdmissionRadarEvent,
    AnalysisEvidenceWorkItemV1,
    StrategyAnalysisAdmissionV1Repository,
)

START = datetime(2026, 8, 17, 6, 1, 9, tzinfo=UTC)


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "USDCHF",
        "deployment_id": "deployment-target",
        "cluster_id": "USDCHF_PRESSURE_EPISODE",
        "pressure_source": "signal_throttle_check",
        "source_stream": "CANARY",
        "raw_direction_role": "SHORT_HORIZON_PRESSURE_RADAR_ONLY",
        "raw_direction": "SELL",
        "candidate_direction": "SELL",
        "watch_direction": "SELL",
        "block_direction": "SELL",
        "pressure_direction_consensus_status": "ALIGNED",
        "block_start_utc": START.isoformat(),
        "block_duration_seconds": 3040.073,
        "block_effective_ticks": 1499,
        "pressure_seen": True,
        "pressure_event_count": 1499,
        "raw_direction_eligible_for_context_resolution": True,
        "pressure_direction_resolution": "UNRESOLVED",
        "raw_direction_expires_at_utc": (START + timedelta(hours=8)).isoformat(),
        "signal_valid_time_utc": (START + timedelta(seconds=3040)).isoformat(),
        "quote_health_status": "LIVE",
        "material_context_hash": "sha256:" + "a" * 64,
        "htf_structure_context": {
            "daily_bias": "BULLISH",
            "h4_structure": "RANGE",
            "price_location": "PREMIUM",
            "allowed_playbook": "WAIT_FOR_BUY_LOCATION",
            "blocked_playbook": ["SELL_LIMIT"],
        },
        "pair_admission_status": "NOT_GRANTED",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
    }
    payload.update(overrides)
    return payload


class _Repository:
    def __init__(self, events=(), evidence_items=(), lifecycle=None):
        self.events = tuple(events)
        self.evidence_items = tuple(evidence_items)
        self.lifecycle = lifecycle
        self.persisted: list[tuple[Any, Any, Any, Any]] = []
        self.snapshots = []
        self.failures = []

    async def fetch_pending_radar_events(self, *, limit):
        return self.events[:limit]

    async def active_recovery_state(self, _symbol):
        return None

    async def lifecycle_for_analysis_admission(self, _analysis_admission_id):
        return self.lifecycle

    async def persist_evaluation(self, event, admission, *, lifecycle=None, event_link=None):
        self.persisted.append((event, admission, lifecycle, event_link))
        return True

    async def load_pending_evidence(self, *, limit):
        return self.evidence_items[:limit]

    async def freeze_decision_time(self, _job_id, decision_time):
        return decision_time

    async def persist_snapshot(self, snapshot):
        self.snapshots.append(snapshot)
        return True

    async def record_evidence_failure(self, job_id, *, error, max_attempts):
        self.failures.append((job_id, error, max_attempts))
        return True


class _Provider:
    def __init__(self, evidence=None):
        self.evidence = evidence
        self.calls = []

    async def provide(self, **kwargs):
        self.calls.append(kwargs)
        return self.evidence


def _config(**overrides: Any) -> StrategyAnalysisAdmissionRuntimeConfig:
    values = {"enabled": True, "activation_requested": True, "shadow_only": True}
    values.update(overrides)
    return StrategyAnalysisAdmissionRuntimeConfig(**values)


@pytest.mark.asyncio
async def test_mature_advisory_worker_opens_durable_shadow_lifecycle() -> None:
    event = AnalysisAdmissionRadarEvent(
        deployment_id="deployment-target",
        pressure_event_id="sha256:" + "b" * 64,
        symbol="USDCHF",
        observed_at_utc=START + timedelta(seconds=3040),
        payload=_payload(),
    )
    repository = _Repository(events=(event,))
    worker = StrategyAnalysisAdmissionV1Worker(
        repository=repository,  # type: ignore[arg-type]
        provider=_Provider(),
        config=_config(),
    )

    assert await worker.process_admissions_once() == 1

    _event, admission, lifecycle, link = repository.persisted[0]
    assert admission.admission_status == "GRANTED"
    assert admission.pressure_direction == "SELL"
    assert lifecycle is not None and lifecycle.direction_state == "SELL"
    assert lifecycle.execution_authority is False
    assert link.strategy_lifecycle_id == lifecycle.strategy_lifecycle_id
    assert admission.risk_authority is False
    assert admission.execution_authority is False


@pytest.mark.asyncio
async def test_direction_conflict_opens_waiting_resolution_lifecycle_without_evidence_authority() -> None:
    event = AnalysisAdmissionRadarEvent(
        deployment_id="deployment-target",
        pressure_event_id="sha256:" + "c" * 64,
        symbol="USDCHF",
        observed_at_utc=START + timedelta(seconds=3040),
        payload=_payload(
            block_direction="BUY",
            pressure_direction_consensus_status="CONFLICT",
        ),
    )
    repository = _Repository(events=(event,))
    worker = StrategyAnalysisAdmissionV1Worker(
        repository=repository,  # type: ignore[arg-type]
        provider=_Provider(),
        config=_config(),
    )

    await worker.process_admissions_once()

    _event, admission, lifecycle, _link = repository.persisted[0]
    assert admission.admission_status == "SUSPENDED"
    assert admission.structural_evidence_prefetch_required is False
    assert lifecycle.state == "TRANSITION_PENDING"
    assert lifecycle.direction_state == "CONFLICT"


@pytest.mark.asyncio
async def test_expired_advisory_terminalizes_its_existing_lifecycle() -> None:
    reducer = MarketEpisodeReducer()
    active = reducer.ingest(
        EpisodeEvent(
            pressure_event_id="sha256:" + "3" * 64,
            symbol="USDCHF",
            event_time_utc=START + timedelta(seconds=300),
            transport_lifecycle_id="advisory-transport",
            raw_direction="SELL",
            pressure_seen=True,
            pressure_event_count=149,
        )
    )
    expired_at = START + timedelta(hours=8)
    event = AnalysisAdmissionRadarEvent(
        deployment_id="deployment-target",
        pressure_event_id="sha256:" + "4" * 64,
        symbol="USDCHF",
        observed_at_utc=expired_at,
        payload=_payload(
            signal_valid_time_utc=expired_at.isoformat(),
            raw_direction_expires_at_utc=(expired_at - timedelta(seconds=1)).isoformat(),
            pressure_direction_resolution="EXPIRED",
        ),
    )
    repository = _Repository(events=(event,), lifecycle=active)
    worker = StrategyAnalysisAdmissionV1Worker(
        repository=repository,  # type: ignore[arg-type]
        provider=_Provider(),
        config=_config(),
    )

    await worker.process_admissions_once()

    _event, admission, lifecycle, link = repository.persisted[0]
    assert admission.analysis_state == "ADVISORY_EXPIRED"
    assert lifecycle.state == "TERMINAL_NO_TRADE"
    assert lifecycle.execution_authority is False
    assert link.strategy_lifecycle_id == active.strategy_lifecycle_id


def _evidence_item(admission_payload: dict[str, Any]) -> AnalysisEvidenceWorkItemV1:
    return AnalysisEvidenceWorkItemV1(
        evidence_job_id="5scr-analysis-evidence-job:" + "d" * 32,
        analysis_admission_id=admission_payload["analysis_admission_id"],
        strategy_lifecycle_id="5scr-lifecycle:" + "e" * 32,
        symbol="USDCHF",
        opened_at_utc=START,
        decision_time_utc=None,
        attempt_count=0,
        admission_payload=admission_payload,
    )


def _complete_evidence() -> Strategy5SCRMarketEvidence:
    return Strategy5SCRMarketEvidence(
        decision_at_utc=START + timedelta(hours=1),
        lifecycle_anchor_utc=START,
        h1=H1Confirmation(
            direction="SELL",
            structure_state="BEARISH_TRANSITION",
            structure_confirmed=True,
            candle_closed=True,
            confirmed_at_utc=START + timedelta(minutes=15),
        ),
        m15=M15Confirmation(
            direction="SELL",
            structural_break=True,
            candle_closed=True,
            acceptance_confirmed=True,
            failed_reclaim_or_retest_confirmed=False,
            rejection_candle_only=False,
            confirmed_at_utc=START + timedelta(minutes=30),
        ),
        m1=M1ExecutionBox(
            box_id="USDCHF-M1-BOX",
            box_low=0.8090,
            box_high=0.8100,
            fill_price=0.8095,
            return_to_box_invalidated=False,
            formed_at_utc=START + timedelta(minutes=45),
        ),
        structural_sl=0.8110,
        pip_size=0.0001,
        spread_price=0.0001,
    )


def test_valid_geometry_creates_only_a_shadow_candidate() -> None:
    admission = evaluate_strategy_analysis_admission(_payload()).model_dump(mode="json")
    snapshot = build_analysis_evidence_snapshot_v1(
        _evidence_item(admission),
        _complete_evidence(),
        decision_time=START + timedelta(hours=1),
    )

    assert snapshot.result_state == "SHADOW_CANDIDATE"
    assert snapshot.shadow_tradeplan_candidate is True
    assert snapshot.final_direction == "WAIT"
    assert snapshot.valid_for_execution is False
    assert snapshot.risk_authority is False
    assert snapshot.execution_authority is False


def test_frozen_quote_prefetches_history_but_stays_waiting_price_quality() -> None:
    admission = evaluate_strategy_analysis_admission(_payload(quote_health_status="PRICE_FROZEN")).model_dump(
        mode="json"
    )
    snapshot = build_analysis_evidence_snapshot_v1(
        _evidence_item(admission),
        _complete_evidence(),
        decision_time=START + timedelta(hours=1),
    )

    assert snapshot.coverage_status == "COMPLETE"
    assert snapshot.result_state == "WAIT"
    assert snapshot.terminal_reason == "PRICE_QUALITY_PENDING_HISTORICAL_EVIDENCE_PREFETCHED"
    assert snapshot.shadow_tradeplan_candidate is False


def test_pressure_payload_exposes_the_higher_analysis_contract() -> None:
    payload = build_signal_pressure_state_payload(_payload())

    assert payload["strategy_analysis_admission_class"] == "MATURE_ADVISORY"
    assert payload["strategy_analysis_admission_status"] == "GRANTED"
    assert payload["strategy_analysis_direction"] == "SELL"
    assert payload["strategy_analysis_risk_authority"] is False
    assert payload["strategy_analysis_execution_authority"] is False


def test_later_canonical_raw_event_upgrades_the_same_market_episode() -> None:
    reducer = MarketEpisodeReducer()
    advisory = EpisodeEvent(
        pressure_event_id="sha256:" + "1" * 64,
        symbol="USDCHF",
        event_time_utc=START + timedelta(seconds=300),
        transport_lifecycle_id="advisory-transport",
        raw_direction="SELL",
        pressure_seen=True,
        pressure_event_count=149,
    )
    canonical = EpisodeEvent(
        pressure_event_id="sha256:" + "2" * 64,
        symbol="USDCHF",
        event_time_utc=START + timedelta(seconds=360),
        transport_lifecycle_id="5scr-admission:" + "f" * 32,
        raw_direction="SELL",
        source_clean_block_id="USDCHF_RAW_BLOCK",
        pressure_seen=True,
        pair_eligible_for_analysis=True,
        pressure_event_count=180,
    )

    advisory_lifecycle = reducer.ingest(advisory)
    canonical_lifecycle = reducer.ingest(canonical)

    assert canonical_lifecycle.strategy_lifecycle_id == advisory_lifecycle.strategy_lifecycle_id
    assert len(reducer.result.lifecycles) == 1
    assert canonical_lifecycle.event_count == 2
    assert canonical_lifecycle.execution_authority is False


def test_runtime_defaults_off_and_refuses_execution_plane() -> None:
    assert StrategyAnalysisAdmissionRuntimeConfig.from_env({}).enabled is False

    with pytest.raises(RuntimeError, match="REQUIRES_EXECUTION_OFF"):
        StrategyAnalysisAdmissionRuntimeConfig.from_env(
            {
                "STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_ENABLED": "true",
                "RISK_RESERVATION_ENABLED": "true",
            }
        )


@pytest.mark.parametrize("execution_flag", (*EXECUTION_PLANE_FLAGS, "STRATEGY_5SCR_EXECUTION_ENABLED"))
@pytest.mark.parametrize("enabled_value", sorted(TRUE_VALUES))
def test_runtime_refuses_every_central_execution_plane_flag(
    execution_flag: str,
    enabled_value: str,
) -> None:
    with pytest.raises(RuntimeError, match="REQUIRES_EXECUTION_OFF"):
        StrategyAnalysisAdmissionRuntimeConfig.from_env(
            {
                "STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_ENABLED": "true",
                execution_flag: enabled_value,
            }
        )


def _good_schema_constraints() -> list[dict[str, Any]]:
    authority_definitions = {
        "ck_5scr_analysis_admission_shadow_only_v1": (
            "CHECK ((risk_authority = false) AND (execution_authority = false))"
        ),
        "ck_5scr_analysis_admission_evaluation_shadow_only_v1": (
            "CHECK ((risk_authority = false) AND (execution_authority = false))"
        ),
        "ck_5scr_analysis_evidence_snapshot_shadow_only_v1": (
            "CHECK ((valid_for_execution = false) AND (risk_authority = false) "
            "AND (execution_authority = false))"
        ),
    }
    return [
        {
            "conname": name,
            "table_name": table,
            "contype": contype,
            "convalidated": True,
            "definition": authority_definitions.get(name, "STRUCTURAL CONSTRAINT"),
        }
        for name, (table, contype) in admission_repository._REQUIRED_CONSTRAINTS.items()
    ]


def _good_schema_triggers() -> list[dict[str, Any]]:
    return [
        {
            "tgname": name,
            "table_name": table,
            "function_name": function,
            "enabled": "O",
            "row_level": True,
            "before_event": True,
            "on_insert": False,
            "on_delete": True,
            "on_update": True,
            "on_truncate": False,
        }
        for name, (table, function) in admission_repository._REQUIRED_TRIGGERS.items()
    ]


class _AnalysisAdmissionSchemaProbe:
    is_available = True

    def __init__(self, *, constraints=None, triggers=None) -> None:
        self.constraints = _good_schema_constraints() if constraints is None else constraints
        self.triggers = _good_schema_triggers() if triggers is None else triggers

    async def fetch(self, query: str, *_args: Any) -> list[dict[str, Any]]:
        normalized = " ".join(query.split())
        if "FROM pg_catalog.pg_tables" in normalized:
            return [{"tablename": name} for name in admission_repository._REQUIRED_TABLES]
        if "FROM pg_catalog.pg_indexes" in normalized:
            return [{"indexname": name} for name in admission_repository._REQUIRED_INDEXES]
        if "FROM pg_catalog.pg_constraint" in normalized:
            return self.constraints
        if "FROM pg_catalog.pg_trigger" in normalized:
            return self.triggers
        raise AssertionError(f"unexpected schema query: {normalized}")


@pytest.mark.asyncio
async def test_schema_status_requires_complete_fail_closed_catalog() -> None:
    status = await StrategyAnalysisAdmissionV1Repository(pg=_AnalysisAdmissionSchemaProbe()).schema_status()

    assert not any(status.values())


@pytest.mark.asyncio
async def test_schema_status_rejects_weakened_authority_check() -> None:
    constraints = _good_schema_constraints()
    target = next(
        row for row in constraints if row["conname"] == "ck_5scr_analysis_admission_shadow_only_v1"
    )
    target["definition"] = "CHECK (((risk_authority = false) AND (execution_authority = false)) OR true)"

    status = await StrategyAnalysisAdmissionV1Repository(
        pg=_AnalysisAdmissionSchemaProbe(constraints=constraints)
    ).schema_status()

    assert "ck_5scr_analysis_admission_shadow_only_v1" in status["invalid_constraints"]


@pytest.mark.asyncio
async def test_schema_status_rejects_disabled_immutability_trigger() -> None:
    triggers = _good_schema_triggers()
    triggers[0]["enabled"] = "D"

    status = await StrategyAnalysisAdmissionV1Repository(
        pg=_AnalysisAdmissionSchemaProbe(triggers=triggers)
    ).schema_status()

    assert triggers[0]["tgname"] in status["invalid_triggers"]


def test_migration_is_additive_and_database_shadow_only() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "migrations"
        / "versions"
        / "20260826_01_strategy_analysis_admission_v1.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "20260826_01"' in migration
    assert 'down_revision = "20260822_01"' in migration
    assert "ck_5scr_analysis_admission_shadow_only_v1" in migration
    assert "ck_5scr_analysis_evidence_snapshot_shadow_only_v1" in migration
    assert "risk_authority=false AND execution_authority=false" in migration
    assert "execution_commands" not in migration
    assert "risk_reservations" not in migration
