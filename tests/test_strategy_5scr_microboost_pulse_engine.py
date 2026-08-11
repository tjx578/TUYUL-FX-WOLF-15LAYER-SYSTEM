"""Pulse-vs-state semantics for Microboost pressure.

The property that matters most: a latched ``microboost_detected=true`` riding
many emissions is *one* pulse, not many.  Everything else here defends that
distinction from the directions it could erode -- duplicates, telemetry
refreshes, direction flips, and TTL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analysis.strategy_5scr_microboost_pulse_engine import (
    MicroboostPulseEngine,
    MicroboostPulsePolicy,
    microboost_pulse_enabled,
)

START = datetime(2026, 7, 17, 13, 0, 0, tzinfo=UTC)
LIFECYCLE = "5scr-lifecycle:0123456789abcdef0123456789abcdef"


def _payload(
    *,
    detected=True,
    direction="BUY",
    ticks=10,
    strength="MICROBOOST",
    stage="MICROBOOST",
    block="CHFJPY_20260717T130000Z_20260717T130500Z",
    at=START,
):
    return {
        "microboost_detected": detected,
        "block_direction": direction,
        "block_effective_ticks": ticks,
        "pressure_strength": strength,
        "source_stage": stage,
        "source_clean_block_id": block,
        "block_latest_end_utc": at.isoformat(),
    }


def _engine(**policy_kwargs) -> MicroboostPulseEngine:
    return MicroboostPulseEngine(
        LIFECYCLE,
        "CHFJPY",
        policy=MicroboostPulsePolicy(**policy_kwargs) if policy_kwargs else None,
    )


# --------------------------------------------------------------------------
# the core distinction
# --------------------------------------------------------------------------


def test_sticky_state_across_many_snapshots_is_one_pulse():
    """100 latched snapshots must not become 100 pulses."""
    engine = _engine()
    for index in range(100):
        engine.ingest(
            _payload(stage="SIGNAL_THROTTLE_INTEL", at=START + timedelta(seconds=index * 5)),
            event_id=f"evt-{index}",
        )

    assert engine.state.independent_pulse_count == 1
    assert len(engine.pulses) == 1
    assert engine.pulses[0].transition == "FORMED"
    assert engine.state.state == "ACTIVE"


def test_sticky_ratio_exposes_carried_share():
    engine = _engine()
    for index in range(10):
        engine.ingest(_payload(at=START + timedelta(seconds=index * 5)), event_id=f"evt-{index}")

    state = engine.state
    assert state.observed_snapshot_count == 10
    assert state.carried_snapshot_count == 9
    assert state.sticky_ratio == pytest.approx(0.9)


def test_duplicate_emission_does_not_add_a_pulse():
    engine = _engine()
    engine.ingest(_payload(), event_id="evt-1")
    engine.ingest(_payload(), event_id="evt-1")
    engine.ingest(_payload(), event_id="evt-1")

    assert len(engine.pulses) == 1
    assert engine.state.independent_pulse_count == 1
    assert engine.state.observed_snapshot_count == 1


# --------------------------------------------------------------------------
# transitions
# --------------------------------------------------------------------------


def test_false_to_true_forms_a_pulse():
    engine = _engine()
    assert engine.ingest(_payload(detected=False), event_id="evt-0") == ()
    assert engine.state.state == "NONE"

    pulses = engine.ingest(_payload(at=START + timedelta(seconds=5)), event_id="evt-1")

    assert [p.transition for p in pulses] == ["FORMED"]
    assert engine.state.direction == "BUY"
    assert engine.state.first_formed_at_utc is not None


def test_material_tick_growth_reinforces():
    engine = _engine()
    engine.ingest(_payload(ticks=10), event_id="evt-1")
    pulses = engine.ingest(
        _payload(ticks=40, at=START + timedelta(seconds=120)),
        event_id="evt-2",
    )

    assert [p.transition for p in pulses] == ["REINFORCED"]
    assert engine.state.reinforcement_count == 1
    assert engine.state.independent_pulse_count == 1
    assert engine.state.peak_effective_ticks == 40


def test_material_tick_decay_weakens():
    engine = _engine()
    engine.ingest(_payload(ticks=40), event_id="evt-1")
    pulses = engine.ingest(
        _payload(ticks=5, at=START + timedelta(seconds=120)),
        event_id="evt-2",
    )

    assert [p.transition for p in pulses] == ["WEAKENED"]
    assert engine.state.state == "WEAKENING"
    assert engine.state.peak_effective_ticks == 40


def test_direction_flip_invalidates_then_forms_new_pulse():
    """An opposite pulse never mutates the existing one."""
    engine = _engine()
    engine.ingest(_payload(direction="BUY"), event_id="evt-1")
    pulses = engine.ingest(
        _payload(direction="SELL", at=START + timedelta(seconds=120)),
        event_id="evt-2",
    )

    assert [p.transition for p in pulses] == ["INVALIDATED", "FORMED"]
    assert engine.state.direction == "SELL"
    assert engine.state.independent_pulse_count == 2


def test_withdrawn_flag_invalidates_active_pulse():
    engine = _engine()
    engine.ingest(_payload(), event_id="evt-1")
    pulses = engine.ingest(
        _payload(detected=False, at=START + timedelta(seconds=60)),
        event_id="evt-2",
    )

    assert [p.transition for p in pulses] == ["INVALIDATED"]
    assert engine.state.state == "INVALIDATED"
    assert engine.state.is_active is False


def test_ttl_lapse_expires_the_pulse():
    engine = _engine(ttl_seconds=300.0)
    engine.ingest(_payload(), event_id="evt-1")

    expired = engine.expire_due(START + timedelta(seconds=400))

    assert expired is not None and expired.transition == "EXPIRED"
    assert engine.state.state == "EXPIRED"


def test_carried_snapshot_does_not_extend_ttl():
    """Telemetry refresh must not keep a stale pulse alive forever."""
    engine = _engine(ttl_seconds=300.0)
    engine.ingest(_payload(), event_id="evt-1")
    original_expiry = engine.state.expires_at_utc

    for index in range(5):
        engine.ingest(
            _payload(at=START + timedelta(seconds=30 * (index + 1))),
            event_id=f"refresh-{index}",
        )

    assert engine.state.expires_at_utc == original_expiry


def test_new_block_reinforces_even_at_equal_ticks():
    engine = _engine()
    engine.ingest(_payload(block="block-a"), event_id="evt-1")
    pulses = engine.ingest(
        _payload(block="block-b", at=START + timedelta(seconds=120)),
        event_id="evt-2",
    )

    assert [p.transition for p in pulses] == ["REINFORCED"]
    assert engine.state.active_block_id == "block-b"


def test_min_separation_suppresses_rapid_restatement():
    engine = _engine(min_pulse_separation_seconds=300.0)
    engine.ingest(_payload(ticks=10), event_id="evt-1")
    pulses = engine.ingest(
        _payload(ticks=90, at=START + timedelta(seconds=30)),
        event_id="evt-2",
    )

    assert pulses == ()
    assert engine.state.reinforcement_count == 0


def test_out_of_order_snapshot_is_ignored():
    engine = _engine()
    engine.ingest(_payload(at=START + timedelta(seconds=600)), event_id="evt-late")
    pulses = engine.ingest(_payload(ticks=90, at=START), event_id="evt-early")

    assert pulses == ()


# --------------------------------------------------------------------------
# contract invariants
# --------------------------------------------------------------------------


def test_pulses_are_never_executable():
    engine = _engine()
    engine.ingest(_payload(), event_id="evt-1")

    assert all(pulse.valid_for_execution is False for pulse in engine.pulses)
    assert engine.state.valid_for_execution is False


def test_formed_pulse_carries_no_prior_reading():
    engine = _engine()
    engine.ingest(_payload(), event_id="evt-1")
    formed = engine.pulses[0]

    assert formed.effective_ticks_before is None
    assert formed.strength_before is None


def test_pulse_ids_are_deterministic_across_replays():
    first = _engine()
    second = _engine()
    for engine in (first, second):
        engine.ingest(_payload(), event_id="evt-1")
        engine.ingest(_payload(ticks=50, at=START + timedelta(seconds=120)), event_id="evt-2")

    assert [p.pulse_event_id for p in first.pulses] == [p.pulse_event_id for p in second.pulses]


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("STRATEGY_5SCR_MICROBOOST_PULSE_ENABLED", raising=False)
    assert microboost_pulse_enabled() is False

    monkeypatch.setenv("STRATEGY_5SCR_MICROBOOST_PULSE_ENABLED", "true")
    assert microboost_pulse_enabled() is True
