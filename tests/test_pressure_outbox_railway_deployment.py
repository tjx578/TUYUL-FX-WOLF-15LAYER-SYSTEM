from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from services.pressure_outbox.preflight import (
    PressureOutboxRolloutFlags,
    rollout_flags,
    validate_rollout_phase,
)
from storage.pressure_outbox import PressureOutboxRepository

ROOT = Path(__file__).resolve().parents[1]


def test_railway_pressure_outbox_manifest_is_dark_by_default() -> None:
    manifest = tomllib.loads((ROOT / "railway-pressure-outbox.toml").read_text(encoding="utf-8"))

    assert manifest["build"] == {"builder": "DOCKERFILE", "dockerfilePath": "Dockerfile"}
    assert manifest["deploy"]["startCommand"] == "bash deploy/railway/start_pressure_outbox.sh"
    assert manifest["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert manifest["deploy"]["restartPolicyMaxRetries"] == 5
    assert set(manifest) == {"build", "deploy"}


def test_rollout_phase_contract_is_fail_closed() -> None:
    dark = rollout_flags({})
    assert dark == PressureOutboxRolloutFlags(False, False, False, False)
    validate_rollout_phase(dark, "dark")
    validate_rollout_phase(PressureOutboxRolloutFlags(True, False, True, False), "dispatcher")
    validate_rollout_phase(PressureOutboxRolloutFlags(True, False, True, True), "consumer")

    with pytest.raises(RuntimeError, match="PRESSURE_OUTBOX_ROLLOUT_FLAG_MISMATCH"):
        validate_rollout_phase(PressureOutboxRolloutFlags(True, True, True, False), "dispatcher")
    with pytest.raises(RuntimeError, match="PRESSURE_OUTBOX_EXPECTED_PHASE_INVALID"):
        validate_rollout_phase(dark, "writer")


class _SchemaPostgres:
    is_available = True

    def __init__(self, *, complete: bool) -> None:
        self.complete = complete

    async def fetch(self, query: str, *_: Any) -> list[dict[str, str]]:
        if "pg_catalog.pg_tables" in query:
            tables = [
                "pressure_lifecycle_sequences",
                "pressure_outbox",
                "strategy_5scr_inbox",
                "pressure_radar_manifests",
                "pressure_radar_events",
            ]
            return [{"tablename": item} for item in tables if self.complete or item == "pressure_outbox"]
        indexes = [
            "ix_pressure_outbox_pending",
            "ix_pressure_outbox_lease_expiry",
            "ix_pressure_outbox_published",
            "ix_pressure_outbox_lifecycle",
            "ix_pressure_outbox_signal_valid_at",
            "ix_strategy_5scr_inbox_status_received",
            "ix_pressure_radar_manifest_active",
            "ix_pressure_radar_manifest_expiry",
            "ix_pressure_radar_event_manifest",
        ]
        return [{"indexname": item} for item in indexes if self.complete]


@pytest.mark.asyncio
async def test_schema_preflight_reports_missing_and_complete_contracts() -> None:
    missing = await PressureOutboxRepository(pg=cast(Any, _SchemaPostgres(complete=False))).schema_status()
    ready = await PressureOutboxRepository(pg=cast(Any, _SchemaPostgres(complete=True))).schema_status()

    assert missing.ready is False
    assert "strategy_5scr_inbox" in missing.missing_tables
    assert "ix_pressure_outbox_pending" in missing.missing_indexes
    assert ready.ready is True
    assert ready.missing_tables == ()
    assert ready.missing_indexes == ()
