"""SignalThrottle intelligence projection.

This module turns a raw SignalThrottle allowed event into a small, parseable
analysis record.  It does not execute trades and does not override L12.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

from schemas.direction import normalize_direction

_FX_CURRENCIES = frozenset({"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD"})
_METAL_BASES = frozenset({"XAG", "XAU"})


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
    base_ccy: str | None = None
    quote_ccy: str | None = None
    symbol_orientation: str = "UNKNOWN"
    verdict_source: str = "L12_EFFECTIVE_VERDICT"
    verdict_features_hash: str | None = None
    window_count_before: int | None = None
    window_count_after: int | None = None
    window_remaining_before: int | None = None
    window_remaining_after: int | None = None
    allowed_streak_before: int | None = None
    allowed_streak_after: int | None = None

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


def _symbol_orientation(symbol: str) -> tuple[str | None, str | None, str]:
    normalized = str(symbol or "").strip().upper()
    if len(normalized) < 6 or not normalized[:6].isalpha():
        return None, None, "UNKNOWN"
    base = normalized[:3]
    quote = normalized[3:6]
    if base in _METAL_BASES and quote in _FX_CURRENCIES:
        return base, quote, "METAL_BASE_QUOTE"
    if base in _FX_CURRENCIES and quote in _FX_CURRENCIES:
        return base, quote, "FX_BASE_QUOTE"
    return base or None, quote or None, "UNKNOWN"


def _technical_bias(synthesis: dict[str, Any] | None) -> str | None:
    if not isinstance(synthesis, dict):
        return None
    bias = synthesis.get("bias")
    if isinstance(bias, dict) and bias.get("technical") is not None:
        return str(bias.get("technical")).strip().upper() or None
    return None


def _verdict_features_hash(
    *,
    symbol: str,
    verdict: str,
    verdict_source: str,
    raw_direction: str | None,
    l12_direction: str | None,
    execution_direction: str | None,
    technical_bias: str | None,
) -> str:
    payload = {
        "symbol": str(symbol or "").strip().upper(),
        "verdict": str(verdict or "").strip().upper(),
        "verdict_source": str(verdict_source or "").strip().upper(),
        "raw_direction": raw_direction,
        "l12_direction": l12_direction,
        "execution_direction": execution_direction,
        "technical_bias": technical_bias,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


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
    count_before: int | None = None,
    remaining_before: int | None = None,
    allowed_streak_before: int | None = None,
    verdict_source: str = "L12_EFFECTIVE_VERDICT",
) -> SignalThrottleIntel:
    """Classify one allowed SignalThrottle event.

    The output is intentionally conservative: allowed is treated as a candidate
    until a future price/theme/structure validator can promote it.
    """
    max_signals = max(1, _coerce_int(max_signals, 3))
    count_before_value = None if count_before is None else _coerce_int(count_before, 0)
    remaining_before_value = None if remaining_before is None else _coerce_int(remaining_before, 0)
    count = _coerce_int(count, 0)
    remaining = _coerce_int(remaining, max(max_signals - count, 0))
    allowed_streak = max(1, _coerce_int(allowed_streak, count if count > 0 else 1))
    allowed_streak_before_value = (
        max(0, allowed_streak - 1)
        if allowed_streak_before is None
        else _coerce_int(allowed_streak_before, max(0, allowed_streak - 1))
    )
    window_seconds = _coerce_float(window_seconds, 0.0)
    base_ccy, quote_ccy, symbol_orientation = _symbol_orientation(symbol)

    raw_direction = normalize_direction(None, verdict)
    l12_norm = normalize_direction(str(l12_direction) if l12_direction else None)

    execution = {}
    if isinstance(synthesis, dict) and isinstance(synthesis.get("execution"), dict):
        execution = synthesis["execution"]
    exec_norm = normalize_direction(str(execution.get("direction")) if execution.get("direction") else None)
    verdict_source_text = str(verdict_source or "L12_EFFECTIVE_VERDICT").strip().upper()
    common_metadata = {
        "base_ccy": base_ccy,
        "quote_ccy": quote_ccy,
        "symbol_orientation": symbol_orientation,
        "verdict_source": verdict_source_text,
        "verdict_features_hash": _verdict_features_hash(
            symbol=symbol,
            verdict=verdict,
            verdict_source=verdict_source_text,
            raw_direction=raw_direction,
            l12_direction=l12_norm,
            execution_direction=exec_norm,
            technical_bias=_technical_bias(synthesis),
        ),
        "window_count_before": count_before_value,
        "window_count_after": count,
        "window_remaining_before": remaining_before_value,
        "window_remaining_after": remaining,
        "allowed_streak_before": allowed_streak_before_value,
        "allowed_streak_after": allowed_streak,
    }

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
            **common_metadata,
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
            **common_metadata,
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
            **common_metadata,
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
        **common_metadata,
    )


def emit_signal_throttle_intel(intel: SignalThrottleIntel) -> None:
    """Emit a parseable info-level line to stdout."""
    parts = [
        "[SignalThrottleIntel]",
        f"symbol={intel.symbol}",
        f"base_ccy={intel.base_ccy or 'NONE'}",
        f"quote_ccy={intel.quote_ccy or 'NONE'}",
        f"symbol_orientation={intel.symbol_orientation}",
        f"raw_direction={intel.raw_direction or 'NONE'}",
        f"final_direction={intel.final_direction}",
        f"direction_status={intel.direction_status}",
        f"phase={intel.phase}",
        f"action={intel.action}",
        f"verdict={intel.verdict}",
        f"verdict_source={intel.verdict_source}",
        f"verdict_features_hash={intel.verdict_features_hash or 'NONE'}",
        f"count_before={intel.window_count_before if intel.window_count_before is not None else 'NONE'}",
        f"count_after={intel.window_count_after if intel.window_count_after is not None else 'NONE'}",
        f"count={intel.count}",
        f"remaining_before={intel.window_remaining_before if intel.window_remaining_before is not None else 'NONE'}",
        f"remaining_after={intel.window_remaining_after if intel.window_remaining_after is not None else 'NONE'}",
        f"remaining={intel.remaining}",
        f"streak_before={intel.allowed_streak_before if intel.allowed_streak_before is not None else 'NONE'}",
        f"streak_after={intel.allowed_streak_after if intel.allowed_streak_after is not None else 'NONE'}",
        f"streak={intel.allowed_streak}",
        f"max={intel.max_signals}",
        f"window={int(intel.window_seconds)}s",
        f"reason={intel.reason}",
    ]
    sys.stdout.write(" ".join(parts) + "\n")
    sys.stdout.flush()
