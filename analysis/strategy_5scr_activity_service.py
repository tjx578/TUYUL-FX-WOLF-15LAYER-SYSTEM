"""Opt-in service binding; absent/invalid bindings remain explicit and inert."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from contracts.strategy_5scr_activity_runtime import ActivityCoverageCheckpointV1, ActivityRuntimeBindingV1
from storage.strategy_5scr_activity_runtime import PostgresActivityRuntime, unavailable_activity


class UnboundActivityRuntime:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def record(self, event: Any) -> None:
        pass

    def snapshot(self) -> dict[str, Any]:
        return unavailable_activity(self.reason)


def activity_runtime_from_environment(
    environ: Mapping[str, str] | None = None,
) -> PostgresActivityRuntime | UnboundActivityRuntime:
    env = os.environ if environ is None else environ
    binding_path = env.get("WOLF15_PAIR_ACTIVITY_BINDING_PATH")
    if not binding_path:
        return UnboundActivityRuntime("ACTIVITY_RUNTIME_BINDING_UNBOUND")
    dsn = env.get("WOLF15_PAIR_ACTIVITY_DATABASE_URL")
    if not dsn:
        return UnboundActivityRuntime("ACTIVITY_RUNTIME_DATABASE_UNBOUND")
    try:
        binding = ActivityRuntimeBindingV1.model_validate_json(Path(binding_path).read_text(encoding="utf-8"))
        deployment = env.get("RAILWAY_DEPLOYMENT_ID") or env.get("DEPLOYMENT_ID")
        if deployment != binding.deployment_id:
            return UnboundActivityRuntime("ACTIVITY_RUNTIME_DEPLOYMENT_MISMATCH")
    except (OSError, ValueError, TypeError):
        return UnboundActivityRuntime("ACTIVITY_RUNTIME_BINDING_INVALID")

    def checkpoint() -> ActivityCoverageCheckpointV1 | None:
        checkpoint_path = env.get("WOLF15_PAIR_ACTIVITY_CHECKPOINT_PATH")
        if not checkpoint_path:
            return None
        return ActivityCoverageCheckpointV1.model_validate_json(Path(checkpoint_path).read_text(encoding="utf-8"))

    return PostgresActivityRuntime(dsn=dsn, binding=binding, checkpoint_provider=checkpoint)
