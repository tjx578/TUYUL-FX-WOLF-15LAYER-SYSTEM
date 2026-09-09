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

_STRATEGY_STAGE_RANK = {
    "PRESSURE_OBSERVED": 10,
    "PRESSURE_QUALIFIED": 20,
    "PAIR_ADMISSION_GRANTED": 30,
}


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


def build_signal_pressure_state_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the single canonical payload shared by the outbox and log."""

    data = dict(payload)
    for key, value in signal_pressure_runtime_identity().items():
        data.setdefault(key, value)
    data["event"] = "signal_pressure_state_json"
    data["schema_version"] = "2.0-pressure-state"
    data["promotion_stage"] = "PRESSURE_ONLY"
    data["valid_for_execution"] = False
    data["execution_valid_now"] = False
    data["is_final_signal"] = False
    data["final_direction"] = "WAIT"
    data["eligible_for_signal_decision"] = False
    data.setdefault("source_stage_role", "PRODUCER_METADATA_NON_MONOTONIC")
    strategy_stage = str(data.get("strategy_stage") or "").upper()
    if strategy_stage not in _STRATEGY_STAGE_RANK:
        if str(data.get("pair_admission_status") or "").upper() == "GRANTED":
            strategy_stage = "PAIR_ADMISSION_GRANTED"
        else:
            try:
                effective_ticks = int(data.get("current_block_effective_ticks") or 0)
            except (TypeError, ValueError):
                effective_ticks = 0
            strategy_stage = "PRESSURE_QUALIFIED" if effective_ticks >= 3 else "PRESSURE_OBSERVED"
    data["strategy_stage"] = strategy_stage
    data["strategy_stage_rank"] = _STRATEGY_STAGE_RANK[strategy_stage]
    data["strategy_stage_role"] = "MONOTONIC_STRATEGY_LIFECYCLE_STAGE"
    data.setdefault("event_severity", _pressure_event_severity(data))
    return data


def _pressure_event_severity(payload: Mapping[str, Any]) -> str:
    quote_health = str(payload.get("quote_health_status") or "").upper()
    htf_raw = payload.get("htf_structure_context")
    htf = htf_raw if isinstance(htf_raw, Mapping) else {}
    daily_stale = (
        str(htf.get("daily_bias_freshness_status") or "").upper() == "STALE"
        and htf.get("daily_bias_execution_impact") is not False
    )
    if (
        quote_health
        in {
            "PRICE_FROZEN",
            "PRICE_QUALITY_WARMING_UP",
            "INSUFFICIENT_HISTORY",
            "OUT_OF_ORDER",
        }
        or daily_stale
        or payload.get("schema_contract_complete") is False
    ):
        return "WARNING"
    return "INFO"


def emit_signal_pressure_state(
    payload: Mapping[str, Any],
    *,
    enabled: bool = True,
    prefix: str = DEFAULT_SIGNAL_PRESSURE_STATE_PREFIX,
) -> bool:
    if not enabled:
        return False
    data = build_signal_pressure_state_payload(payload)
    level = logging.WARNING if data["event_severity"] == "WARNING" else logging.INFO
    logging.getLogger("signal_json").log(
        level,
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
    data.setdefault("event_severity", "INFO")
    level = logging.WARNING if data["event_severity"] == "WARNING" else logging.INFO
    logging.getLogger("signal_json").log(
        level,
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
