"""SignalPressureStateJSON emitter.

Pressure-state events are observability-only.  They are not fed through the
SignalJSON builder and never authorize execution.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

DEFAULT_SIGNAL_PRESSURE_STATE_PREFIX = "[SignalPressureStateJSON]"


def emit_signal_pressure_state(
    payload: Mapping[str, Any],
    *,
    enabled: bool = True,
    prefix: str = DEFAULT_SIGNAL_PRESSURE_STATE_PREFIX,
) -> bool:
    if not enabled:
        return False
    data = dict(payload)
    data["event"] = "signal_pressure_state_json"
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
    "emit_signal_pressure_state",
]
