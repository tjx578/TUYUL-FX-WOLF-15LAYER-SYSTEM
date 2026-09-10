"""Real-PostgreSQL gates for the canonical raw analysis-admission producer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from storage.observer_export_outbox import ObserverExportOutboxRepository
from storage.pressure_radar_manifest import PressureRadarManifestRepository
from tests.test_pressure_radar_manifest_repository import _lineage_payload, _qualifying_payload

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)


class _FailAfterObserverAppend(ObserverExportOutboxRepository):
    async def append_in_transaction(self, connection: Any, draft: Any, **kwargs: Any) -> Any:
        await super().append_in_transaction(connection, draft, **kwargs)
        raise RuntimeError("injected failure after observer append")


async def test_analysis_ready_and_observer_admission_share_one_transaction(
    postgres: PoolBackedPostgres,
) -> None:
    deployment_id = f"observer-analysis-{uuid4().hex}"
    qualifying = _qualifying_payload(
        deployment_id=deployment_id,
        replica_id=f"replica-{uuid4().hex}",
    )
    lineage = _lineage_payload(qualifying)
    failing = PressureRadarManifestRepository(
        pg=cast(Any, postgres),
        observer_export_repository=_FailAfterObserverAppend(pg=cast(Any, postgres)),
    )
    waiting = await failing.ingest(qualifying)
    assert waiting.manifest is not None

    with pytest.raises(RuntimeError, match="after observer append"):
        await failing.ingest(lineage)

    rolled_back = await postgres.fetchrow(
        """
        SELECT status, outbox_event_id
        FROM pressure_radar_manifests
        WHERE manifest_id=$1
        """,
        waiting.manifest.manifest_id,
    )
    assert rolled_back is not None
    assert dict(rolled_back) == {
        "status": "WAITING_CANONICAL_LINEAGE",
        "outbox_event_id": None,
    }
    assert (
        await postgres.fetchrow(
            "SELECT event_id FROM observer_export.outbox WHERE source_deployment_id=$1",
            deployment_id,
        )
        is None
    )

    export = ObserverExportOutboxRepository(pg=cast(Any, postgres))
    repository = PressureRadarManifestRepository(
        pg=cast(Any, postgres),
        observer_export_repository=export,
    )
    ready = await repository.ingest(lineage)
    replay = await repository.ingest(lineage)
    assert ready.manifest is not None
    assert ready.manifest.pair_admission_id is not None
    rows = await export.read_stream(f"strategy-analysis-admission:{ready.manifest.pair_admission_id}")
    matching_rows = tuple(row for row in rows if row.envelope.source.deployment_id == deployment_id)

    assert ready.transition == "ANALYSIS_READY"
    assert replay.duplicate is True
    assert len(matching_rows) == 1
    envelope = matching_rows[0].envelope
    body = envelope.payload.body
    assert envelope.authority.authority_class == "STRATEGY_ANALYSIS_ADMISSION"
    assert body["admission_class"] == "CANONICAL_RAW"
    assert body["decision"] == "ADMITTED"
    assert body["authority_scope_id"] == ready.manifest.pair_admission_id
    assert body["next_required_stage"] == ready.manifest.next_required_stage
    assert body["execution_authority"] is False
    assert envelope.safety.observer_can_mutate_source is False
