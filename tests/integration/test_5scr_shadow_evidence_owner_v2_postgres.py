"""Real-PostgreSQL gate for Lifecycle V2 shadow evidence ownership."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from analysis.strategy_5scr_closed_candle_provider import FutureCandleLeakageError
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink, StrategyLifecycleV2
from contracts.strategy_5scr_shadow_evidence_v2 import StrategyLifecycleAdmissionLinkV2
from services.pressure_outbox.shadow_evidence_v2_worker import (
    ShadowEvidenceV2RuntimeConfig,
    StrategyShadowEvidenceV2Worker,
)
from storage.strategy_5scr_shadow_evidence_v2_repository import (
    StrategyShadowEvidenceV2Repository,
    shadow_evidence_job_id,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

LIFECYCLE_ID = "5scr-lifecycle:" + "8" * 32
ADMISSION_ID = "5scr-admission:" + "9" * 32
EVENT_ID = "shadow-evidence-owner-event-v2"
SYMBOL = "V2AUDIT"
OPENED_AT = datetime(2026, 8, 4, 1, 0, tzinfo=UTC)


def _bundle() -> tuple[StrategyLifecycleV2, StrategyLifecycleEventLink, StrategyLifecycleAdmissionLinkV2]:
    lifecycle = StrategyLifecycleV2(
        strategy_lifecycle_id=LIFECYCLE_ID,
        symbol=SYMBOL,
        opened_at_utc=OPENED_AT,
        last_event_at_utc=OPENED_AT,
        last_continuity_event_at_utc=OPENED_AT,
        last_material_event_at_utc=OPENED_AT,
        material_state_hash="a" * 64,
        event_count=1,
    )
    event_link = StrategyLifecycleEventLink(
        strategy_lifecycle_id=LIFECYCLE_ID,
        pressure_event_id=EVENT_ID,
        transport_lifecycle_id=ADMISSION_ID,
        linked_at_utc=OPENED_AT,
        link_reason="EPISODE_OPENED",
    )
    admission_link = StrategyLifecycleAdmissionLinkV2(
        admission_event_id=ADMISSION_ID,
        strategy_lifecycle_id=LIFECYCLE_ID,
        pressure_event_id=EVENT_ID,
        raw_lineage_hash="sha256:" + "b" * 64,
        admission_rule_version="5scr.pair-admission.raw-ledger.v2",
        admitted_at_utc=OPENED_AT,
        linked_at_utc=OPENED_AT,
    )
    return lifecycle, event_link, admission_link


async def _cleanup(pg: Any) -> None:
    await pg.execute(
        "DELETE FROM strategy_5scr_evidence_comparisons_v2 WHERE strategy_lifecycle_id = $1",
        LIFECYCLE_ID,
    )
    await pg.execute(
        "DELETE FROM strategy_5scr_evidence_snapshots_v2 WHERE strategy_lifecycle_id = $1",
        LIFECYCLE_ID,
    )
    await pg.execute(
        "DELETE FROM strategy_5scr_evidence_jobs_v2 WHERE strategy_lifecycle_id = $1",
        LIFECYCLE_ID,
    )
    await pg.execute(
        "DELETE FROM strategy_5scr_lifecycle_admission_links_v2 WHERE strategy_lifecycle_id = $1",
        LIFECYCLE_ID,
    )
    await pg.execute(
        "DELETE FROM strategy_5scr_lifecycle_event_links_v2 WHERE strategy_lifecycle_id = $1",
        LIFECYCLE_ID,
    )
    await pg.execute(
        "DELETE FROM strategy_5scr_analysis_lifecycles_v2 WHERE strategy_lifecycle_id = $1",
        LIFECYCLE_ID,
    )


async def _execution_counts(pg: Any) -> tuple[int, int, int, int]:
    row = await pg.fetchrow(
        """
        SELECT
            (SELECT count(*) FROM strategy_5scr_risk_reservations) AS reservations,
            (SELECT count(*) FROM strategy_5scr_final_signal_outbox) AS final_outbox,
            (SELECT count(*) FROM execution_commands) AS commands,
            (SELECT count(*) FROM broker_entities) AS broker_entities
        """
    )
    return (
        int(row["reservations"]),
        int(row["final_outbox"]),
        int(row["commands"]),
        int(row["broker_entities"]),
    )


class _NoCoverageProvider:
    async def provide(self, **_: Any) -> None:
        return None


class _FutureLeakProvider:
    async def provide(self, **_: Any) -> None:
        raise FutureCandleLeakageError("STRATEGY_5SCR_FUTURE_CANDLE_LEAKAGE")


async def test_owner_bundle_restart_freezes_decision_and_stays_non_executable(postgres: Any) -> None:
    await _cleanup(postgres)
    baseline = await _execution_counts(postgres)
    assert baseline == (0, 0, 0, 0)
    repository = StrategyShadowEvidenceV2Repository(pg=postgres)
    lifecycle, event_link, admission_link = _bundle()
    try:
        assert await repository.persist_owner_bundle(lifecycle, event_link, admission_link) is True
        assert await repository.persist_owner_bundle(lifecycle, event_link, admission_link) is False

        counts = await postgres.fetchrow(
            """
            SELECT
                (SELECT count(*) FROM strategy_5scr_analysis_lifecycles_v2
                  WHERE strategy_lifecycle_id = $1) AS lifecycles,
                (SELECT count(*) FROM strategy_5scr_lifecycle_admission_links_v2
                  WHERE strategy_lifecycle_id = $1) AS admissions,
                (SELECT count(*) FROM strategy_5scr_evidence_jobs_v2
                  WHERE strategy_lifecycle_id = $1) AS jobs
            """,
            LIFECYCLE_ID,
        )
        assert tuple(int(counts[key]) for key in ("lifecycles", "admissions", "jobs")) == (1, 1, 1)

        frozen_decision = OPENED_AT + timedelta(hours=2)
        job_id = shadow_evidence_job_id(LIFECYCLE_ID)
        assert await repository.freeze_decision_time(job_id, frozen_decision) == frozen_decision

        restarted = StrategyShadowEvidenceV2Worker(
            repository=StrategyShadowEvidenceV2Repository(pg=postgres),
            provider=_NoCoverageProvider(),
            config=ShadowEvidenceV2RuntimeConfig(enabled=True, activation_requested=True),
            clock=lambda: frozen_decision + timedelta(hours=3),
        )
        assert await restarted.process_once() == 1
        stored = await postgres.fetchrow(
            """
            SELECT s.decision_time, s.coverage_status, s.valid_for_execution,
                   s.execution_authority, s.evidence_hash, j.status,
                   c.reason_codes
            FROM strategy_5scr_evidence_snapshots_v2 s
            JOIN strategy_5scr_evidence_jobs_v2 j
              ON j.evidence_job_id = s.evidence_job_id
            JOIN strategy_5scr_evidence_comparisons_v2 c
              ON c.strategy_lifecycle_id = s.strategy_lifecycle_id
            WHERE s.strategy_lifecycle_id = $1
            """,
            LIFECYCLE_ID,
        )
        assert stored["decision_time"] == frozen_decision
        assert stored["coverage_status"] == "INCOMPLETE"
        assert stored["valid_for_execution"] is False
        assert stored["execution_authority"] is False
        assert stored["status"] == "COMPLETED"
        assert "LEGACY_EVIDENCE_NOT_AVAILABLE" in stored["reason_codes"]
        assert str(stored["evidence_hash"]).startswith("sha256:")
        metrics = await repository.metrics_snapshot()
        assert metrics["evidence_snapshot_count"] == 1
        assert metrics["wait_result_count"] == 1
        assert metrics["restart_parity_failure_count"] == 0
        assert await _execution_counts(postgres) == baseline
    finally:
        await _cleanup(postgres)


async def test_future_candle_failure_persists_no_snapshot_or_comparison(postgres: Any) -> None:
    await _cleanup(postgres)
    repository = StrategyShadowEvidenceV2Repository(pg=postgres)
    lifecycle, event_link, admission_link = _bundle()
    try:
        assert await repository.persist_owner_bundle(lifecycle, event_link, admission_link) is True
        worker = StrategyShadowEvidenceV2Worker(
            repository=repository,
            provider=_FutureLeakProvider(),
            config=ShadowEvidenceV2RuntimeConfig(
                enabled=True,
                activation_requested=True,
                max_attempts=1,
            ),
            clock=lambda: OPENED_AT + timedelta(hours=1),
        )
        assert await worker.process_once() == 0
        row = await postgres.fetchrow(
            """
            SELECT j.status, j.last_error,
                   (SELECT count(*) FROM strategy_5scr_evidence_snapshots_v2
                     WHERE strategy_lifecycle_id = $1) AS snapshots,
                   (SELECT count(*) FROM strategy_5scr_evidence_comparisons_v2
                     WHERE strategy_lifecycle_id = $1) AS comparisons
            FROM strategy_5scr_evidence_jobs_v2 j
            WHERE j.strategy_lifecycle_id = $1
            """,
            LIFECYCLE_ID,
        )
        assert row["status"] == "FAILED"
        assert "FUTURE_CANDLE_LEAKAGE" in str(row["last_error"])
        assert int(row["snapshots"]) == 0
        assert int(row["comparisons"]) == 0
        assert await _execution_counts(postgres) == (0, 0, 0, 0)
    finally:
        await _cleanup(postgres)


async def test_same_named_weakened_shadow_constraint_fails_readiness(postgres: Any) -> None:
    repository = StrategyShadowEvidenceV2Repository(pg=postgres)
    assert not any((await repository.schema_status()).values())
    try:
        await postgres.execute(
            "ALTER TABLE strategy_5scr_evidence_snapshots_v2 DROP CONSTRAINT ck_5scr_evidence_snapshot_shadow_only_v2"
        )
        await postgres.execute(
            "ALTER TABLE strategy_5scr_evidence_snapshots_v2 "
            "ADD CONSTRAINT ck_5scr_evidence_snapshot_shadow_only_v2 "
            "CHECK ((valid_for_execution = false AND execution_authority = false) OR true)"
        )
        degraded = await repository.schema_status()
        assert degraded["missing_constraints"] == ("ck_5scr_evidence_snapshot_shadow_only_v2",)
    finally:
        await postgres.execute(
            "ALTER TABLE strategy_5scr_evidence_snapshots_v2 "
            "DROP CONSTRAINT IF EXISTS ck_5scr_evidence_snapshot_shadow_only_v2"
        )
        await postgres.execute(
            "ALTER TABLE strategy_5scr_evidence_snapshots_v2 "
            "ADD CONSTRAINT ck_5scr_evidence_snapshot_shadow_only_v2 "
            "CHECK (valid_for_execution = false AND execution_authority = false)"
        )
    assert not any((await repository.schema_status()).values())
