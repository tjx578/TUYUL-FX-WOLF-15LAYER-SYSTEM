"""Fail-closed Railway preflight for the pressure outbox worker."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from storage.postgres_client import pg_client
from storage.pressure_outbox import PressureOutboxRepository


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
        return {
            "event": "pressure_outbox_preflight",
            "ready": True,
            "expected_phase": expected_phase,
            "flags": asdict(flags),
            "schema_tables": sorted(schema.present_tables),
            "schema_indexes": sorted(schema.present_indexes),
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
