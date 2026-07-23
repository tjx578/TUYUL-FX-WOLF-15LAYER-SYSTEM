"""Fail-closed Railway preflight for the pressure outbox worker."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from services.pressure_outbox.evidence_worker import EvidenceRuntimeConfig
from storage.postgres_client import pg_client
from storage.pressure_outbox import PressureOutboxRepository
from storage.pressure_radar_manifest import PressureRadarManifestRepository
from storage.strategy_5scr_candle_store import PostgresClosedCandleStore


def _enabled(value: str | None) -> bool:
    return str(value or "false").strip().lower() == "true"


@dataclass(frozen=True)
class PressureOutboxRolloutFlags:
    master: bool
    write: bool
    dispatch: bool
    consumer: bool


_EXPECTED_PHASES = {
    "dark": PressureOutboxRolloutFlags(False, False, False, False),
    "dispatcher": PressureOutboxRolloutFlags(True, False, True, False),
    "consumer": PressureOutboxRolloutFlags(True, False, True, True),
}


def rollout_flags(environ: Mapping[str, str] | None = None) -> PressureOutboxRolloutFlags:
    source = os.environ if environ is None else environ
    return PressureOutboxRolloutFlags(
        master=_enabled(source.get("SIGNAL_PRESSURE_OUTBOX_ENABLED")),
        write=_enabled(source.get("SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED")),
        dispatch=_enabled(source.get("SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED")),
        consumer=_enabled(source.get("STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED")),
    )


def validate_rollout_phase(flags: PressureOutboxRolloutFlags, expected_phase: str) -> None:
    expected = _EXPECTED_PHASES.get(expected_phase)
    if expected is None:
        raise RuntimeError(f"PRESSURE_OUTBOX_EXPECTED_PHASE_INVALID:{expected_phase}")
    if flags != expected:
        raise RuntimeError(
            "PRESSURE_OUTBOX_ROLLOUT_FLAG_MISMATCH:"
            f"expected={expected_phase}:actual={json.dumps(asdict(flags), sort_keys=True)}"
        )


async def run_preflight() -> dict[str, object]:
    expected_phase = os.getenv("PRESSURE_OUTBOX_EXPECTED_PHASE", "dark").strip().lower()
    flags = rollout_flags()
    validate_rollout_phase(flags, expected_phase)
    evidence_config = EvidenceRuntimeConfig.from_env()
    if evidence_config.enabled and not (flags.master and flags.consumer):
        raise RuntimeError("STRATEGY_5SCR_EVIDENCE_REQUIRES_PRESSURE_CONSUMER")
    await pg_client.initialize()
    if not pg_client.is_available:
        raise RuntimeError("PRESSURE_OUTBOX_DATABASE_UNAVAILABLE")
    try:
        schema = await PressureOutboxRepository(pg=pg_client).schema_status()
        if not schema.ready:
            raise RuntimeError(
                "PRESSURE_OUTBOX_SCHEMA_NOT_READY:"
                f"tables={','.join(schema.missing_tables) or 'none'}:"
                f"indexes={','.join(schema.missing_indexes) or 'none'}"
            )
        radar_schema = await PressureRadarManifestRepository(pg=pg_client).schema_status()
        if not radar_schema.ready:
            raise RuntimeError(
                "PRESSURE_RADAR_SCHEMA_NOT_READY:"
                f"tables={','.join(radar_schema.missing_tables) or 'none'}:"
                f"indexes={','.join(radar_schema.missing_indexes) or 'none'}"
            )
        candle_schema = await PostgresClosedCandleStore(pg=pg_client).schema_status()
        if evidence_config.enabled and not candle_schema.ready:
            raise RuntimeError(
                "STRATEGY_5SCR_CANDLE_SCHEMA_NOT_READY:"
                f"columns={','.join(candle_schema.missing_columns) or 'none'}:"
                f"closed_asof_index={candle_schema.closed_asof_index_present}"
            )
        return {
            "event": "pressure_outbox_preflight",
            "ready": True,
            "expected_phase": expected_phase,
            "flags": asdict(flags),
            "schema_tables": sorted(schema.present_tables),
            "schema_indexes": sorted(schema.present_indexes),
            "radar_schema_tables": sorted(radar_schema.present_tables),
            "radar_schema_indexes": sorted(radar_schema.present_indexes),
            "evidence": asdict(evidence_config),
            "candle_schema_ready": candle_schema.ready,
        }
    finally:
        await pg_client.close()


def main() -> int:
    print(json.dumps(asyncio.run(run_preflight()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PressureOutboxRolloutFlags",
    "rollout_flags",
    "run_preflight",
    "validate_rollout_phase",
]
