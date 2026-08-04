"""Fail-closed Railway preflight for the pressure outbox worker."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from services.pressure_outbox.evidence_worker import EvidenceRuntimeConfig
from services.pressure_outbox.lifecycle_shadow_worker import LifecycleV2RuntimeConfig
from services.pressure_outbox.outcome_worker import (
    OutcomeRuntimeConfig,
    PostgresOutcomeRepository,
)
from services.pressure_outbox.shadow_evidence_v2_worker import ShadowEvidenceV2RuntimeConfig
from storage.postgres_client import pg_client
from storage.pressure_outbox import PressureOutboxRepository
from storage.pressure_radar_manifest import PressureRadarManifestRepository
from storage.strategy_5scr_candle_store import PostgresClosedCandleStore
from storage.strategy_5scr_lifecycle_v2_repository import StrategyLifecycleV2Repository
from storage.strategy_5scr_shadow_evidence_v2_repository import StrategyShadowEvidenceV2Repository


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
    # Writer authority belongs to the engine.  The worker dispatches and
    # consumes but must never carry SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED.
    "production-observe": PressureOutboxRolloutFlags(True, False, True, True),
}


def lifecycle_v2_schema_ready(status: Mapping[str, tuple[str, ...]]) -> bool:
    """Ready only when nothing is missing on any dimension.

    Tables and indexes are not enough: a database that kept the tables but lost
    the shadow-only CHECK would run the worker while the invariant it depends
    on no longer exists.
    """
    return not any(status.values())


def lifecycle_v2_schema_error(status: Mapping[str, tuple[str, ...]]) -> str:
    return (
        "STRATEGY_5SCR_LIFECYCLE_V2_SCHEMA_NOT_READY:"
        f"tables={','.join(status.get('missing_tables', ())) or 'none'}:"
        f"indexes={','.join(status.get('missing_indexes', ())) or 'none'}:"
        f"columns={','.join(status.get('missing_columns', ())) or 'none'}:"
        f"constraints={','.join(status.get('missing_constraints', ())) or 'none'}"
    )


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


def validate_analysis_worker_phase(
    *,
    expected_phase: str,
    evidence_enabled: bool,
    outcome_enabled: bool,
) -> None:
    """Keep live evidence/outcomes confined to production-observe."""

    if expected_phase == "production-observe" and not evidence_enabled:
        raise RuntimeError("PRODUCTION_OBSERVE_REQUIRES_EVIDENCE_WORKER")
    if expected_phase != "production-observe" and evidence_enabled:
        raise RuntimeError("EVIDENCE_WORKER_REQUIRES_PRODUCTION_OBSERVE_PHASE")
    if outcome_enabled and not evidence_enabled:
        raise RuntimeError("STRATEGY_5SCR_OUTCOME_REQUIRES_EVIDENCE_WORKER")


def validate_lifecycle_evidence_owner_phase(
    *,
    lifecycle_config: LifecycleV2RuntimeConfig,
    evidence_config: ShadowEvidenceV2RuntimeConfig,
) -> None:
    if lifecycle_config.evidence_owner_writer_enabled and not (
        lifecycle_config.enabled and lifecycle_config.shadow_only and lifecycle_config.dual_write_enabled
    ):
        raise RuntimeError("STRATEGY_5SCR_EVIDENCE_OWNER_WRITER_REQUIRES_LIFECYCLE_DUAL_WRITE")
    if lifecycle_config.evidence_owner_writer_enabled and evidence_config.execution_plane_active:
        raise RuntimeError("STRATEGY_5SCR_EVIDENCE_OWNER_WRITER_REQUIRES_EXECUTION_OFF")
    if evidence_config.enabled and not lifecycle_config.evidence_owner_writer_enabled:
        raise RuntimeError("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_REQUIRES_OWNER_WRITER")


async def run_preflight() -> dict[str, object]:
    expected_phase = os.getenv("PRESSURE_OUTBOX_EXPECTED_PHASE", "dark").strip().lower()
    flags = rollout_flags()
    validate_rollout_phase(flags, expected_phase)
    evidence_config = EvidenceRuntimeConfig.from_env()
    outcome_config = OutcomeRuntimeConfig.from_env()
    validate_analysis_worker_phase(
        expected_phase=expected_phase,
        evidence_enabled=evidence_config.enabled,
        outcome_enabled=outcome_config.enabled,
    )
    if evidence_config.enabled and not (flags.master and flags.consumer):
        raise RuntimeError("STRATEGY_5SCR_EVIDENCE_REQUIRES_PRESSURE_CONSUMER")
    lifecycle_v2_config = LifecycleV2RuntimeConfig.from_env()
    shadow_evidence_v2_config = ShadowEvidenceV2RuntimeConfig.from_env()
    validate_lifecycle_evidence_owner_phase(
        lifecycle_config=lifecycle_v2_config,
        evidence_config=shadow_evidence_v2_config,
    )
    # Phase one has no non-shadow mode.  Refuse at startup rather than trust
    # every call site to re-check.
    if lifecycle_v2_config.enabled and not lifecycle_v2_config.shadow_only:
        raise RuntimeError("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY_REQUIRED")
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
        outcome_schema = await PostgresOutcomeRepository(pg=pg_client).schema_status()
        if (evidence_config.enabled or outcome_config.enabled) and not outcome_schema.ready:
            raise RuntimeError(
                "STRATEGY_5SCR_OUTCOME_SCHEMA_NOT_READY:"
                f"tables={','.join(outcome_schema.missing_tables) or 'none'}:"
                f"indexes={','.join(outcome_schema.missing_indexes) or 'none'}"
            )
        lifecycle_v2_schema = await StrategyLifecycleV2Repository(pg=pg_client).schema_status()
        lifecycle_v2_ready = lifecycle_v2_schema_ready(lifecycle_v2_schema)
        # Enabling the worker before migration 20260729_01 has run would fail on
        # every poll; fail closed at startup instead.
        if lifecycle_v2_config.enabled and not lifecycle_v2_ready:
            raise RuntimeError(lifecycle_v2_schema_error(lifecycle_v2_schema))
        owner_schema = await StrategyShadowEvidenceV2Repository(pg=pg_client).schema_status()
        owner_schema_ready = not any(owner_schema.values())
        if (
            lifecycle_v2_config.evidence_owner_writer_enabled or shadow_evidence_v2_config.enabled
        ) and not owner_schema_ready:
            raise RuntimeError(
                "STRATEGY_5SCR_SHADOW_EVIDENCE_V2_SCHEMA_NOT_READY:"
                f"tables={','.join(owner_schema['missing_tables']) or 'none'}:"
                f"indexes={','.join(owner_schema['missing_indexes']) or 'none'}:"
                f"columns={','.join(owner_schema['missing_columns']) or 'none'}:"
                f"constraints={','.join(owner_schema['missing_constraints']) or 'none'}"
            )
        if shadow_evidence_v2_config.enabled and not candle_schema.ready:
            raise RuntimeError("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_CANDLE_SCHEMA_NOT_READY")
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
            "outcome": asdict(outcome_config),
            "execution_isolated": not any(
                (
                    evidence_config.execution_enabled,
                    evidence_config.risk_reservation_enabled,
                    evidence_config.trade_outbox_write_enabled,
                    evidence_config.ea_command_delivery_enabled,
                    evidence_config.mt5_order_send_enabled,
                )
            ),
            "candle_schema_ready": candle_schema.ready,
            "outcome_schema_ready": outcome_schema.ready,
            "lifecycle_v2": asdict(lifecycle_v2_config),
            "lifecycle_v2_schema_ready": lifecycle_v2_ready,
            "shadow_evidence_v2": asdict(shadow_evidence_v2_config),
            "shadow_evidence_v2_schema_ready": owner_schema_ready,
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
    "validate_analysis_worker_phase",
    "validate_lifecycle_evidence_owner_phase",
    "validate_rollout_phase",
]
