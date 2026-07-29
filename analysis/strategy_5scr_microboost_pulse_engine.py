"""Reduce sticky Microboost snapshots into an explicit pulse-transition stream.

``SignalPressureStateJSON`` reports ``microboost_detected`` as a latched state.
Once a Microboost forms it keeps riding subsequent emissions, including those
published by other stages, so a naive count of the flag measures *persistence*
and calls it *frequency*.

This engine consumes those snapshots in order and emits a pulse only when the
evidence changes materially:

    100 sticky snapshots -> 1 FORMED, perhaps a couple of REINFORCED
                         -> never 100 pulses

It is a pure reducer.  It performs no I/O, resolves no direction, and produces
nothing executable -- Microboost remains timing/pressure evidence.

Flag-guarded via ``STRATEGY_5SCR_MICROBOOST_PULSE_ENABLED`` (default off) so the
stream can be shadow-compared against legacy ``REPEATED_MICROBOOST`` counts
before anything downstream consumes it.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from contracts.strategy_5scr_microboost_pulse import (
    MicroboostPulseEvent,
    MicroboostPulseTransition,
    MicroboostState,
)

MICROBOOST_PULSE_FLAG = "STRATEGY_5SCR_MICROBOOST_PULSE_ENABLED"

#: Ordinal ranking of the categorical ``pressure_strength`` labels actually
#: observed in the pressure stream.  Unknown labels rank 0 and therefore never
#: fabricate a strengthening or weakening signal on their own.
STRENGTH_RANK: dict[str, int] = {
    "CANARY": 1,
    "MICROBOOST": 2,
    "SUSTAINED": 3,
    "STRONG": 4,
}

DEFAULT_TICK_BUCKET = 5
DEFAULT_TTL_SECONDS = 900.0
DEFAULT_MIN_PULSE_SEPARATION_SECONDS = 60.0


def microboost_pulse_enabled() -> bool:
    return os.getenv(MICROBOOST_PULSE_FLAG, "false").strip().lower() == "true"


class MicroboostPulsePolicy:
    """Tunables that decide when a change counts as *material*."""

    def __init__(
        self,
        *,
        tick_bucket: int = DEFAULT_TICK_BUCKET,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        min_pulse_separation_seconds: float = DEFAULT_MIN_PULSE_SEPARATION_SECONDS,
    ) -> None:
        if tick_bucket < 1:
            raise ValueError("tick_bucket must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if min_pulse_separation_seconds < 0:
            raise ValueError("min_pulse_separation_seconds cannot be negative")
        self.tick_bucket = tick_bucket
        self.ttl_seconds = ttl_seconds
        self.min_pulse_separation_seconds = min_pulse_separation_seconds

    def bucket(self, ticks: int) -> int:
        return int(ticks) // self.tick_bucket


def _text(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def _direction(value: Any) -> str | None:
    resolved = (_text(value) or "").upper()
    return resolved if resolved in {"BUY", "SELL"} else None


def _non_negative_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if not math.isfinite(timestamp):
            return None
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


class _Observation:
    """The subset of a pressure payload the pulse reducer actually reads."""

    __slots__ = (
        "detected",
        "direction",
        "occurred_at",
        "effective_ticks",
        "strength",
        "source_stage",
        "source_family",
        "block_id",
    )

    def __init__(self, payload: Mapping[str, Any], *, fallback_time: datetime | None) -> None:
        self.detected = bool(payload.get("microboost_detected"))
        self.direction = _direction(
            payload.get("block_direction") or payload.get("raw_direction") or payload.get("candidate_direction")
        )
        occurred = (
            _parse_datetime(payload.get("block_latest_end_utc"))
            or _parse_datetime(payload.get("generated_at_utc"))
            or _parse_datetime(payload.get("event_time_utc"))
            or fallback_time
        )
        if occurred is None:
            raise ValueError("MICROBOOST_PULSE_EVENT_TIME_REQUIRED")
        self.occurred_at = occurred
        self.effective_ticks = _non_negative_int(
            payload.get("block_effective_ticks")
            if payload.get("block_effective_ticks") is not None
            else payload.get("max_effective_ticks")
        )
        self.strength = _text(payload.get("pressure_strength"))
        self.source_stage = _text(payload.get("source_stage"))
        self.source_family = _text(payload.get("source_family"))
        self.block_id = _text(payload.get("source_clean_block_id"))

    @property
    def strength_rank(self) -> int:
        return STRENGTH_RANK.get((self.strength or "").upper(), 0)


class MicroboostPulseEngine:
    """Fold ordered pressure snapshots for one lifecycle into pulses + state.

    One engine instance tracks one ``strategy_lifecycle_id``.  Feed it snapshots
    in non-decreasing time order; out-of-order snapshots are ignored rather than
    allowed to rewrite an already-observed past.
    """

    def __init__(
        self,
        strategy_lifecycle_id: str,
        symbol: str,
        *,
        policy: MicroboostPulsePolicy | None = None,
    ) -> None:
        self.policy = policy or MicroboostPulsePolicy()
        self._state = MicroboostState(
            strategy_lifecycle_id=strategy_lifecycle_id,
            symbol=symbol.upper(),
        )
        self._pulses: list[MicroboostPulseEvent] = []
        #: Signatures already pulsed within the *current* pulse generation.
        #: Cleared on a terminal transition so a genuinely new pulse may reuse
        #: an earlier signature.
        self._generation_signatures: set[str] = set()
        self._seen_event_ids: set[str] = set()

    @property
    def state(self) -> MicroboostState:
        return self._state

    @property
    def pulses(self) -> tuple[MicroboostPulseEvent, ...]:
        return tuple(self._pulses)

    def ingest(
        self,
        payload: Mapping[str, Any],
        *,
        event_id: str,
        event_time_utc: datetime | None = None,
    ) -> tuple[MicroboostPulseEvent, ...]:
        """Fold one snapshot in and return any pulses it produced.

        Returns an empty tuple for the common case: a sticky snapshot that
        carries the state forward without changing it.
        """
        if event_id in self._seen_event_ids:
            # A redelivered emission is not new evidence.
            return ()
        self._seen_event_ids.add(event_id)

        observation = _Observation(payload, fallback_time=event_time_utc)
        if self._state.last_pulse_at_utc is not None and observation.occurred_at < self._state.last_pulse_at_utc:
            return ()

        emitted: list[MicroboostPulseEvent] = []
        expiry = self._expire_if_due(observation.occurred_at, event_id, observation)
        if expiry is not None:
            emitted.append(expiry)

        if not observation.detected:
            withdrawal = self._withdraw_if_active(observation, event_id)
            if withdrawal is not None:
                emitted.append(withdrawal)
            self._note_snapshot(observation, carried=False)
            return tuple(emitted)

        emitted.extend(self._ingest_detected(observation, event_id))
        return tuple(emitted)

    def expire_due(self, as_of_utc: datetime, *, event_id: str = "ttl-sweep") -> MicroboostPulseEvent | None:
        """Expire an active pulse whose TTL lapsed with no new confirmation."""
        return self._expire_if_due(as_of_utc, event_id, None)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _ingest_detected(self, observation: _Observation, event_id: str) -> list[MicroboostPulseEvent]:
        state = self._state
        if not state.is_active:
            self._generation_signatures.clear()
            return [self._emit("FORMED", observation, event_id)]

        if (
            observation.direction is not None
            and state.direction is not None
            and observation.direction != state.direction
        ):
            # An opposite pulse does not mutate the existing one; the old pulse
            # is invalidated and a new one forms in the new direction.
            invalidated = self._emit("INVALIDATED", observation, event_id, direction=state.direction)
            self._generation_signatures.clear()
            formed = self._emit("FORMED", observation, event_id)
            return [invalidated, formed]

        transition = self._classify(observation)
        if transition is None:
            self._note_snapshot(observation, carried=True)
            return []
        return [self._emit(transition, observation, event_id)]

    def _classify(self, observation: _Observation) -> MicroboostPulseTransition | None:
        """Decide whether an ACTIVE pulse materially changed.

        Returns ``None`` for a carried snapshot -- the case that dominates the
        stream and that must never be mistaken for a new pulse.
        """
        state = self._state
        signature = self._signature(observation)
        if signature in self._generation_signatures:
            return None

        if state.last_pulse_at_utc is not None:
            elapsed = (observation.occurred_at - state.last_pulse_at_utc).total_seconds()
            if elapsed < self.policy.min_pulse_separation_seconds:
                return None

        current_bucket = self.policy.bucket(state.current_effective_ticks)
        observed_bucket = self.policy.bucket(observation.effective_ticks)
        strength_delta = observation.strength_rank - STRENGTH_RANK.get((state.current_strength or "").upper(), 0)
        new_block = observation.block_id is not None and observation.block_id != state.active_block_id

        if observed_bucket > current_bucket or strength_delta > 0 or new_block:
            return "REINFORCED"
        if observed_bucket < current_bucket or strength_delta < 0:
            return "WEAKENED"
        return None

    def _signature(self, observation: _Observation) -> str:
        return "|".join(
            (
                observation.direction or "NONE",
                observation.source_stage or "NONE",
                observation.block_id or "NONE",
                str(self.policy.bucket(observation.effective_ticks)),
                (observation.strength or "NONE").upper(),
            )
        )

    def _expire_if_due(
        self,
        as_of_utc: datetime,
        event_id: str,
        observation: _Observation | None,
    ) -> MicroboostPulseEvent | None:
        state = self._state
        if not state.is_active or state.expires_at_utc is None:
            return None
        if as_of_utc < state.expires_at_utc:
            return None
        return self._emit(
            "EXPIRED",
            observation,
            event_id,
            direction=state.direction,
            occurred_at=state.expires_at_utc,
        )

    def _withdraw_if_active(self, observation: _Observation, event_id: str) -> MicroboostPulseEvent | None:
        if not self._state.is_active:
            return None
        # The evidence stopped being reported; the pulse no longer stands.
        return self._emit("INVALIDATED", observation, event_id, direction=self._state.direction)

    def _emit(
        self,
        transition: MicroboostPulseTransition,
        observation: _Observation | None,
        event_id: str,
        *,
        direction: str | None = None,
        occurred_at: datetime | None = None,
    ) -> MicroboostPulseEvent:
        state = self._state
        resolved_direction = direction or (observation.direction if observation else None)
        moment = occurred_at or (observation.occurred_at if observation else datetime.now(UTC))
        signature = self._signature(observation) if observation else f"{transition}|TTL"
        dedupe_key = f"{state.strategy_lifecycle_id}|{transition}|{signature}|{state.state_version}"
        pulse = MicroboostPulseEvent(
            pulse_event_id="5scr-pulse:"
            + hashlib.sha256(f"{dedupe_key}|{moment.isoformat()}".encode()).hexdigest()[:32],
            strategy_lifecycle_id=state.strategy_lifecycle_id,
            symbol=state.symbol,
            transition=transition,
            direction=resolved_direction if resolved_direction in {"BUY", "SELL"} else None,
            occurred_at_utc=moment,
            source_event_ids=(event_id,),
            source_stage=observation.source_stage if observation else None,
            source_family=observation.source_family if observation else None,
            active_block_id=observation.block_id if observation else state.active_block_id,
            effective_ticks_before=None if transition == "FORMED" else state.current_effective_ticks,
            effective_ticks_after=observation.effective_ticks if observation else None,
            strength_before=None if transition == "FORMED" else state.current_strength,
            strength_after=observation.strength if observation else None,
            dedupe_key=dedupe_key,
        )
        self._pulses.append(pulse)
        self._apply(pulse, observation)
        return pulse

    def _apply(self, pulse: MicroboostPulseEvent, observation: _Observation | None) -> None:
        state = self._state
        transition = pulse.transition
        updates: dict[str, Any] = {
            "state_version": state.state_version + 1,
            "last_pulse_at_utc": pulse.occurred_at_utc,
        }

        if transition in {"INVALIDATED", "EXPIRED"}:
            updates["state"] = transition
            updates["expires_at_utc"] = None
            self._generation_signatures.clear()
            self._state = state.model_copy(update=updates)
            return

        if observation is not None:
            self._generation_signatures.add(self._signature(observation))

        ticks = observation.effective_ticks if observation else state.current_effective_ticks
        strength = (observation.strength if observation else state.current_strength) or state.current_strength
        updates.update(
            {
                "state": "WEAKENING" if transition == "WEAKENED" else "ACTIVE",
                "direction": pulse.direction or state.direction,
                "last_confirmed_at_utc": pulse.occurred_at_utc,
                "expires_at_utc": pulse.occurred_at_utc + timedelta(seconds=self.policy.ttl_seconds),
                "current_effective_ticks": ticks,
                "peak_effective_ticks": max(state.peak_effective_ticks, ticks),
                "current_strength": strength,
                "active_block_id": (observation.block_id if observation else None) or state.active_block_id,
                "last_source_stage": observation.source_stage if observation else state.last_source_stage,
                "observed_snapshot_count": state.observed_snapshot_count + 1,
            }
        )
        if STRENGTH_RANK.get((strength or "").upper(), 0) >= STRENGTH_RANK.get((state.peak_strength or "").upper(), 0):
            updates["peak_strength"] = strength

        if transition == "FORMED":
            updates["independent_pulse_count"] = state.independent_pulse_count + 1
            updates["first_formed_at_utc"] = state.first_formed_at_utc or pulse.occurred_at_utc
        elif transition == "REINFORCED":
            updates["reinforcement_count"] = state.reinforcement_count + 1

        self._state = state.model_copy(update=updates)

    def _note_snapshot(self, observation: _Observation, *, carried: bool) -> None:
        state = self._state
        updates: dict[str, Any] = {"observed_snapshot_count": state.observed_snapshot_count + 1}
        if carried:
            updates["carried_snapshot_count"] = state.carried_snapshot_count + 1
            updates["last_confirmed_at_utc"] = observation.occurred_at
            # A carried snapshot is *not* new evidence: it must never extend the
            # TTL, or a stale pulse would live forever on telemetry refresh.
        self._state = state.model_copy(update=updates)


__all__ = [
    "DEFAULT_MIN_PULSE_SEPARATION_SECONDS",
    "DEFAULT_TICK_BUCKET",
    "DEFAULT_TTL_SECONDS",
    "MICROBOOST_PULSE_FLAG",
    "STRENGTH_RANK",
    "MicroboostPulseEngine",
    "MicroboostPulsePolicy",
    "microboost_pulse_enabled",
]
