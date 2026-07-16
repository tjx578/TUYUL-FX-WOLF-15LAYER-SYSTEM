"""SignalPressureStateJSON emitter.

Pressure-state events are observability-only.  They are not fed through the
SignalJSON builder and never authorize execution.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

DEFAULT_SIGNAL_PRESSURE_STATE_PREFIX = "[SignalPressureStateJSON]"
DEFAULT_SIGNAL_PRESSURE_STATE_SUMMARY_PREFIX = "[SignalPressureStateSummary]"


def signal_pressure_runtime_identity(*, generated_at: datetime | None = None) -> dict[str, str]:
    timestamp = generated_at or datetime.now(UTC)
    return {
        "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID") or os.getenv("DEPLOYMENT_ID") or "unknown",
        "commit_sha": (
            os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA") or os.getenv("COMMIT_SHA") or "unknown"
        ),
        "replica_id": os.getenv("RAILWAY_REPLICA_ID") or os.getenv("REPLICA_ID") or "unknown",
        "generated_at_utc": timestamp.astimezone(UTC).isoformat(),
    }


def emit_signal_pressure_state(
    payload: Mapping[str, Any],
    *,
    enabled: bool = True,
    prefix: str = DEFAULT_SIGNAL_PRESSURE_STATE_PREFIX,
) -> bool:
    if not enabled:
        return False
    data = dict(payload)
    for key, value in signal_pressure_runtime_identity().items():
        data.setdefault(key, value)
    data["event"] = "signal_pressure_state_json"
    data["schema_version"] = "2.0-pressure-state"
    data["valid_for_execution"] = False
    data["execution_valid_now"] = False
    data["is_final_signal"] = False
    data["final_direction"] = "WAIT"
    data["eligible_for_signal_decision"] = False
    logging.getLogger("signal_json").warning(
        "%s %s",
        prefix,
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def emit_signal_pressure_state_summary(
    payload: Mapping[str, Any],
    *,
    enabled: bool = True,
    prefix: str = DEFAULT_SIGNAL_PRESSURE_STATE_SUMMARY_PREFIX,
) -> bool:
    if not enabled:
        return False
    data = dict(payload)
    for key, value in signal_pressure_runtime_identity().items():
        data.setdefault(key, value)
    data["event"] = "signal_pressure_state_summary"
    data["schema_version"] = "1.0-pressure-state-summary"
    data["valid_for_execution"] = False
    data["execution_valid_now"] = False
    data["is_final_signal"] = False
    data["final_direction"] = "WAIT"
    data["eligible_for_signal_decision"] = False
    logging.getLogger("signal_json").warning(
        "%s %s",
        prefix,
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


__all__ = [
    "DEFAULT_SIGNAL_PRESSURE_STATE_PREFIX",
    "DEFAULT_SIGNAL_PRESSURE_STATE_SUMMARY_PREFIX",
    "emit_signal_pressure_state",
    "emit_signal_pressure_state_summary",
    "signal_pressure_runtime_identity",
]
