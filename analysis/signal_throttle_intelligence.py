"""SignalThrottle intelligence projection.

This module turns a raw SignalThrottle allowed event into a small, parseable
analysis record.  It does not execute trades and does not override L12.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

from schemas.direction import normalize_direction


@dataclass(frozen=True)
class SignalThrottleIntel:
    symbol: str
    verdict: str
    raw_direction: str | None
    final_direction: str
    direction_status: str
    phase: str
    action: str
    count: int
    remaining: int
    allowed_streak: int
    max_signals: int
    window_seconds: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _phase_from_allowed_streak(allowed_streak: int, quorum_size: int = 3) -> str:
    if allowed_streak <= 1:
        return "IGNITION"
    if allowed_streak < quorum_size:
        return "TIMING_VALID"
    return "ALLOWED_CANARY_QUORUM"


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, Real) and not isinstance(value, bool):
        return max(0, int(float(value)))
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def classify_allowed_signal(
    *,
    symbol: str,
    verdict: str,
    l12_direction: Any | None,
    synthesis: dict[str, Any] | None,
    count: int,
    remaining: int,
    max_signals: int,
    window_seconds: float,
    allowed_streak: int | None = None,
) -> SignalThrottleIntel:
    """Classify one allowed SignalThrottle event.

    The output is intentionally conservative: allowed is treated as a candidate
    until a future price/theme/structure validator can promote it.
    """
    max_signals = max(1, _coerce_int(max_signals, 3))
    count = _coerce_int(count, 0)
    remaining = _coerce_int(remaining, max(max_signals - count, 0))
    allowed_streak = max(1, _coerce_int(allowed_streak, count if count > 0 else 1))
    window_seconds = _coerce_float(window_seconds, 0.0)

    raw_direction = normalize_direction(None, verdict)
    l12_norm = normalize_direction(str(l12_direction) if l12_direction else None)

    execution = {}
    if isinstance(synthesis, dict) and isinstance(synthesis.get("execution"), dict):
        execution = synthesis["execution"]
    exec_norm = normalize_direction(str(execution.get("direction")) if execution.get("direction") else None)

    phase = _phase_from_allowed_streak(allowed_streak)

    if raw_direction is None:
        return SignalThrottleIntel(
            symbol=symbol,
            verdict=verdict,
            raw_direction=None,
            final_direction="WAIT",
            direction_status="NO_EXECUTE_DIRECTION",
            phase=phase,
            action="WAIT",
            count=count,
            remaining=remaining,
            allowed_streak=allowed_streak,
            max_signals=max_signals,
            window_seconds=window_seconds,
            reason="verdict_has_no_buy_sell_direction",
        )

    if l12_norm and l12_norm != raw_direction:
        return SignalThrottleIntel(
            symbol=symbol,
            verdict=verdict,
            raw_direction=raw_direction,
            final_direction="BLOCK_DIRECTION",
            direction_status="DIRECTION_MISMATCH",
            phase=phase,
            action="BLOCK_ENTRY",
            count=count,
            remaining=remaining,
            allowed_streak=allowed_streak,
            max_signals=max_signals,
            window_seconds=window_seconds,
            reason=f"l12_direction={l12_norm}_differs_from_verdict={raw_direction}",
        )

    if exec_norm and exec_norm != raw_direction:
        return SignalThrottleIntel(
            symbol=symbol,
            verdict=verdict,
            raw_direction=raw_direction,
            final_direction="BLOCK_DIRECTION",
            direction_status="DIRECTION_MISMATCH",
            phase=phase,
            action="BLOCK_ENTRY",
            count=count,
            remaining=remaining,
            allowed_streak=allowed_streak,
            max_signals=max_signals,
            window_seconds=window_seconds,
            reason=f"execution_direction={exec_norm}_differs_from_verdict={raw_direction}",
        )

    status = "ALLOWED_CANDIDATE"
    action = "WAIT_PRICE_CONFIRMATION"
    if phase == "ALLOWED_CANARY_QUORUM":
        status = "CANARY_QUORUM_PENDING_VALIDATION"
        action = "WAIT_PRICE_THEME_STRUCTURE"

    return SignalThrottleIntel(
        symbol=symbol,
        verdict=verdict,
        raw_direction=raw_direction,
        final_direction="WAIT",
        direction_status=status,
        phase=phase,
        action=action,
        count=count,
        remaining=remaining,
        allowed_streak=allowed_streak,
        max_signals=max_signals,
        window_seconds=window_seconds,
        reason="allowed_is_candidate_until_price_theme_structure_validation",
    )


def emit_signal_throttle_intel(intel: SignalThrottleIntel) -> None:
    """Emit a parseable info-level line to stdout."""
    parts = [
        "[SignalThrottleIntel]",
        f"symbol={intel.symbol}",
        f"raw_direction={intel.raw_direction or 'NONE'}",
        f"final_direction={intel.final_direction}",
        f"direction_status={intel.direction_status}",
        f"phase={intel.phase}",
        f"action={intel.action}",
        f"verdict={intel.verdict}",
        f"count={intel.count}",
        f"remaining={intel.remaining}",
        f"streak={intel.allowed_streak}",
        f"max={intel.max_signals}",
        f"window={int(intel.window_seconds)}s",
        f"reason={intel.reason}",
    ]
    sys.stdout.write(" ".join(parts) + "\n")
    sys.stdout.flush()
