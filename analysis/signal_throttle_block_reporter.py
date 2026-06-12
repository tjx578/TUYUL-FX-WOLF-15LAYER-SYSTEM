"""Pure-stage SignalThrottle block reporter.

Translates the proven ``PressureBlock`` sequence engine into discrete
pure-stage lifecycle events.  This layer is deliberately thin: it owns no
sequence logic of its own and reuses ``build_pressure_blocks`` /
``PressureBlock`` from :mod:`analysis.signal_throttle_log_analyzer`.

Stage-purity contract (ST-001..ST-010):
  * direction is ALWAYS ``"UNRESOLVED"`` -- SignalThrottle never promotes raw
    pressure into a trade direction;
  * the raw pressure colour from the logs is preserved separately as
    ``raw_pressure_direction`` so downstream stages keep their raw_direction
    signal without this stage deciding entry;
  * blocks are gap-agnostic: a time gap NEVER ends a block, only a different
    pair does (gap is recorded as a quality field, ``max_gap_seconds``);
  * no price / structure / M15 / RR / execution field is read or emitted;
  * a block becomes timing-valid only after >= 5 uninterrupted minutes, and a
    price/structure check is requested only once the block is finalized.

The reporter answers exactly six questions and nothing more: which pair, how
long, how strong, timing-valid or not, why the block ended, and whether a
price check is now due.
"""

from __future__ import annotations

from typing import Any

from analysis.signal_throttle_log_analyzer import (
    PressureBlock,
    SignalThrottleLogEvent,
    build_pressure_blocks,
)

__all__ = [
    "DOMINANT_SECONDS",
    "MAJOR_SECONDS",
    "SUSTAINED_SECONDS",
    "TIMING_VALID_SECONDS",
    "build_block_event",
    "build_finalized_block_events",
    "classify_duration",
    "is_price_check_required",
    "is_timing_valid",
]

# Duration tier gates (seconds).  These describe pressure *persistence* only;
# they are not entry permissions.
TIMING_VALID_SECONDS = 300.0  # >= 5m  -> timing valid
SUSTAINED_SECONDS = 600.0  # >= 10m -> sustained clean block
DOMINANT_SECONDS = 1200.0  # >= 20m -> dominant clean block
MAJOR_SECONDS = 1800.0  # >= 30m -> major pressure block


def classify_duration(duration_seconds: float) -> str:
    """Map an uninterrupted same-pair block duration to its pure-stage tier."""
    if duration_seconds < TIMING_VALID_SECONDS:
        return "PRE_VALID"
    if duration_seconds < SUSTAINED_SECONDS:
        return "TIMING_VALID"
    if duration_seconds < DOMINANT_SECONDS:
        return "SUSTAINED"
    if duration_seconds < MAJOR_SECONDS:
        return "DOMINANT"
    return "MAJOR"


def is_timing_valid(duration_seconds: float) -> bool:
    """A block clears the timing gate once it runs >= 5 uninterrupted minutes."""
    return duration_seconds >= TIMING_VALID_SECONDS


def is_price_check_required(duration_seconds: float, finalized: bool) -> bool:
    """Price/structure analysis is requested only for a finalized timing-valid block.

    A block that is still forming (``finalized=False``) never requests a price
    check, and a finalized block below the 5-minute gate is left as pure radar.
    """
    return finalized and is_timing_valid(duration_seconds)


def _block_id(block: PressureBlock) -> str:
    return f"{block.symbol.upper()}_{block.start.strftime('%Y%m%dT%H%M%S')}Z"


def build_block_event(
    block: PressureBlock,
    *,
    finalized: bool,
    interrupted_by_pair: str | None = None,
) -> dict[str, Any]:
    """Render one ``PressureBlock`` as a pure-stage lifecycle event.

    ``finalized`` selects between ``signal_throttle_block_update`` (block still
    forming) and ``signal_throttle_block_finalized`` (block closed because a
    different pair appeared or the stream ended).
    """
    duration_seconds = float(block.duration_seconds)
    price_check = is_price_check_required(duration_seconds, finalized)
    raw_direction = block.direction or "NONE"
    return {
        "event": ("signal_throttle_block_finalized" if finalized else "signal_throttle_block_update"),
        "schema_version": "1.0",
        "symbol": block.symbol,
        "block_id": _block_id(block),
        "block_status": classify_duration(duration_seconds),
        "timing_valid": is_timing_valid(duration_seconds),
        # Stage-purity: never a trade direction here.
        "direction": "UNRESOLVED",
        "raw_pressure_direction": raw_direction,
        "start_time_utc": block.start.isoformat(),
        "end_time_utc": block.end.isoformat(),
        "duration_seconds": round(duration_seconds, 3),
        "duration_minutes": round(duration_seconds / 60.0, 2),
        "event_count": block.events,
        "density_per_minute": block.density_per_minute,
        "effective_ticks": block.effective_ticks,
        "effective_density_per_minute": block.effective_density_per_minute,
        "suppressed_ticks": block.suppressed_ticks,
        # Quality only -- a large gap is recorded, never used to split a block.
        "max_gap_seconds": block.max_gap_seconds,
        "interrupted_by_pair": interrupted_by_pair,
        "price_check_required": price_check,
        "next_stage": ("PRICE_STRUCTURE_ANALYSIS" if price_check else "WAIT_MORE_PRESSURE"),
        "reason": _reason(duration_seconds, finalized),
    }


def build_finalized_block_events(
    events: list[SignalThrottleLogEvent],
) -> list[dict[str, Any]]:
    """Build finalized pure-stage block events from a batch of throttle events.

    Blocks are formed gap-agnostically (``max_gap_seconds=None``) so only a
    different pair ends a block.  Every returned block is treated as finalized
    (batch/offline semantics); ``interrupted_by_pair`` is the next different
    pair to appear after the block ends, or ``None`` when the block runs to the
    end of the stream.
    """
    ordered = sorted(events, key=lambda item: item.timestamp)
    blocks = build_pressure_blocks(ordered, max_gap_seconds=None)
    return [
        build_block_event(
            block,
            finalized=True,
            interrupted_by_pair=_interrupted_by(block, ordered),
        )
        for block in blocks
    ]


def _interrupted_by(block: PressureBlock, ordered: list[SignalThrottleLogEvent]) -> str | None:
    """Return the first different-pair symbol to appear after ``block`` ends.

    Because blocks are gap-agnostic and same-pair runs never split, the first
    event after ``block.end`` carrying a different symbol is precisely the pair
    that interrupted this block.  ``None`` means the block reached the tail of
    the stream.
    """
    symbol = block.symbol.upper()
    for event in ordered:
        if event.timestamp > block.end and event.symbol.upper() != symbol:
            return event.symbol.upper()
    return None


def _reason(duration_seconds: float, finalized: bool) -> str:
    if not finalized:
        return "SignalThrottle block forming; direction unresolved, awaiting block close."
    if duration_seconds < TIMING_VALID_SECONDS:
        return "SignalThrottle block finalized below the 5-minute timing gate; no price check."
    return "Clean same-pair SignalThrottle block finalized; timing valid; price/structure check required."
