"""Fail-closed preflight for the trade service execution plane.

Runs before any worker exists. Its job is to make an unsafe configuration
impossible to deploy rather than merely unlikely: a typo'd flag, two execution
planes enabled at once, a legacy push worker with no configured bridge, or an
observation phase running with a broker-capable switch left on.

``TRADE_EXPECTED_PHASE`` states what the deploy believes it is. ``observe`` --
the default -- requires every execution switch to be off, so an operator who
means to observe cannot accidentally execute.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping

from execution.execution_plane_flags import (
    ExecutionPlaneConfigError,
    ExecutionPlaneFlags,
    assert_execution_isolated,
    validate_execution_plane,
)

#: Phases the trade service may be deployed in.
OBSERVE_PHASE = "observe"
LEGACY_PUSH_PHASE = "legacy-push"
SIGNED_COMMAND_PHASE = "signed-command"

KNOWN_PHASES = frozenset({OBSERVE_PHASE, LEGACY_PUSH_PHASE, SIGNED_COMMAND_PHASE})


def resolve_expected_phase(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    phase = str(source.get("TRADE_EXPECTED_PHASE") or OBSERVE_PHASE).strip().lower()
    if phase not in KNOWN_PHASES:
        raise ExecutionPlaneConfigError(f"TRADE_EXPECTED_PHASE_INVALID:{phase}")
    return phase


def validate_trade_phase(flags: ExecutionPlaneFlags, phase: str) -> None:
    """Check the resolved plane against what the deploy claims to be."""
    validate_execution_plane(flags)

    if phase == OBSERVE_PHASE:
        assert_execution_isolated(flags, phase=phase)
        return

    if phase == LEGACY_PUSH_PHASE:
        if not flags.legacy_push_execution_enabled:
            raise ExecutionPlaneConfigError("TRADE_PHASE_MISMATCH:legacy-push_requires_legacy_push_enabled")
        if flags.signed_command_bridge_enabled:
            raise ExecutionPlaneConfigError("TRADE_PHASE_MISMATCH:legacy-push_with_signed_bridge")
        return

    if phase == SIGNED_COMMAND_PHASE:
        if not flags.signed_command_bridge_enabled:
            raise ExecutionPlaneConfigError("TRADE_PHASE_MISMATCH:signed-command_requires_bridge_enabled")
        if flags.legacy_push_execution_enabled:
            raise ExecutionPlaneConfigError("TRADE_PHASE_MISMATCH:signed-command_with_legacy_push")


async def run_preflight(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    phase = resolve_expected_phase(environ)
    # strict: a typo in an execution flag stops the deploy instead of being
    # quietly read as "off" and hiding the operator's real intent.
    flags = ExecutionPlaneFlags.from_env(environ, strict=True)
    validate_trade_phase(flags, phase)
    return {
        "event": "trade_preflight",
        "ready": True,
        "expected_phase": phase,
        "execution_plane": flags.as_dict(),
        "execution_isolated": not flags.any_execution_reachable,
        "legacy_push_worker_will_start": flags.legacy_push_execution_enabled,
    }


def main() -> int:
    print(json.dumps(asyncio.run(run_preflight()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "KNOWN_PHASES",
    "LEGACY_PUSH_PHASE",
    "OBSERVE_PHASE",
    "SIGNED_COMMAND_PHASE",
    "main",
    "resolve_expected_phase",
    "run_preflight",
    "validate_trade_phase",
]
