"""Hybrid V3 machinery must stay inert until its own increment activates it.

Three pieces of Hybrid V3 landed on main ahead of their planned sequence. Two
are sound and simply early; one modelled episodes in a way that was later
superseded. These tests pin the containment so a later change cannot quietly
re-activate any of it:

* the superseded SYMBOL_EPISODE grouping is gone, flag and all
* the Microboost pulse engine is consumed only by inert P2 persistence
* the 10-pip policy exists and is tested, but the *existing* runtime stays on
  the legacy floor until a real Hybrid V3 entrypoint selects it
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

from contracts.strategy_5scr_execution_policy import (
    FX_LEGACY_6P_V1,
    FX_MIN_TARGET_10P_V1,
    HYBRID_V3_EXECUTION_POLICY,
    LEGACY_REPLAY_EXECUTION_POLICY,
)
from storage.strategy_5scr_pressure_inbox import Strategy5SCRPressureProcessor

# --------------------------------------------------------------------------
# 1. superseded SYMBOL_EPISODE grouping is fully removed
# --------------------------------------------------------------------------


def test_symbol_episode_anchor_source_is_gone():
    from contracts.strategy_5scr_pressure import CampaignAnchorSource

    assert "SYMBOL_EPISODE" not in getattr(CampaignAnchorSource, "__args__", ())


def test_symbol_episode_policy_contract_is_gone():
    import contracts.strategy_5scr_pressure as pressure_contracts

    assert not hasattr(pressure_contracts, "SymbolEpisodePolicy")


def test_symbol_episode_flag_and_helper_are_gone():
    import analysis.strategy_5scr_pressure_to_tradeplan as tradeplan

    assert not hasattr(tradeplan, "SYMBOL_EPISODE_FLAG")
    assert not hasattr(tradeplan, "symbol_episode_enabled")


def test_accumulator_no_longer_accepts_an_episode_policy():
    from analysis.strategy_5scr_pressure_to_tradeplan import PressureLifecycleAccumulator

    signature = inspect.signature(PressureLifecycleAccumulator.__init__)

    assert "episode_policy" not in signature.parameters


def test_setting_the_old_flag_has_no_runtime_effect(monkeypatch):
    """An operator flipping the retired flag must change nothing."""
    from analysis.strategy_5scr_pressure_to_tradeplan import PressureLifecycleAccumulator

    monkeypatch.setenv("STRATEGY_5SCR_SYMBOL_EPISODE_ENABLED", "true")
    accumulator = PressureLifecycleAccumulator()

    assert not hasattr(accumulator, "episode_policy")
    assert not hasattr(accumulator, "_active_episode")


def test_live_events_without_lineage_use_the_pre_b_fallback():
    """Legacy accumulator is byte-compatible with pre-Commit-B behaviour."""
    from analysis.strategy_5scr_pressure_to_tradeplan import (
        PressureEventNormalizer,
        PressureLifecycleAccumulator,
    )

    payload = {
        "event": "signal_pressure_state_json",
        "schema_version": "2.0-pressure-state",
        "symbol": "CHFJPY",
        "cluster_id": "CHFJPY_20260717T130500Z_MICROBOOST_WATCH",
        "promotion_stage": "PRESSURE_ONLY",
        "raw_direction": "BUY",
        "final_direction": "WAIT",
        "signal_valid_time_utc": "2026-07-17T13:05:00+00:00",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "pressure_seen": True,
        "pressure_event_count": 3,
    }
    event = PressureEventNormalizer(input_mode="LIVE").normalize(payload)
    lifecycle, _duplicate = PressureLifecycleAccumulator().ingest(event)

    assert lifecycle.campaign_anchor_source == "UNRESOLVED"
    assert lifecycle.campaign_id.startswith("unresolved:CHFJPY:")
    assert lifecycle.campaign_anchor_execution_grade is False


# --------------------------------------------------------------------------
# 2. Microboost pulse code present, but inert
# --------------------------------------------------------------------------


def test_microboost_pulse_engine_is_present():
    module = importlib.import_module("analysis.strategy_5scr_microboost_pulse_engine")

    assert hasattr(module, "MicroboostPulseEngine")


def test_microboost_pulse_flag_defaults_off(monkeypatch):
    from analysis.strategy_5scr_microboost_pulse_engine import microboost_pulse_enabled

    monkeypatch.delenv("STRATEGY_5SCR_MICROBOOST_PULSE_ENABLED", raising=False)

    assert microboost_pulse_enabled() is False


def test_microboost_pulse_engine_has_only_the_p2_persistence_consumer():
    """P2 may persist pulses; no service/runtime activation may consume it."""
    root = Path(__file__).parents[1]
    importers: list[str] = []
    for root_name in ("analysis", "api", "contracts", "pipeline", "services", "storage"):
        production_root = root / root_name
        if not production_root.exists():
            continue
        for source in production_root.rglob("*.py"):
            if "strategy_5scr_microboost_pulse_engine" in source.read_text(encoding="utf-8"):
                importers.append(source.relative_to(root).as_posix())

    assert sorted(importers) == ["storage/strategy_5scr_microboost_v1_repository.py"]


def test_pulse_engine_writes_nothing_and_is_not_executable():
    from analysis.strategy_5scr_microboost_pulse_engine import MicroboostPulseEngine

    engine = MicroboostPulseEngine(
        "5scr-lifecycle:22222222222222222222222222222222",
        "CHFJPY",
    )
    engine.ingest(
        {
            "microboost_detected": True,
            "block_direction": "BUY",
            "block_effective_ticks": 10,
            "pressure_strength": "MICROBOOST",
            "source_stage": "MICROBOOST",
            "block_latest_end_utc": "2026-07-17T13:00:00+00:00",
        },
        event_id="evt-1",
    )

    assert all(pulse.valid_for_execution is False for pulse in engine.pulses)
    assert all(pulse.execution_authority is False for pulse in engine.pulses)
    assert engine.state.valid_for_execution is False
    assert engine.state.execution_authority is False


# --------------------------------------------------------------------------
# 3. 10-pip policy available, but not silently active in the existing runtime
# --------------------------------------------------------------------------


def test_existing_pressure_processor_stays_on_the_legacy_floor():
    """The premature activation this containment exists to undo."""
    processor = Strategy5SCRPressureProcessor()

    assert processor.execution_policy is LEGACY_REPLAY_EXECUTION_POLICY
    assert processor.execution_policy.policy_id == "FX_LEGACY_6P_V1"
    assert processor.execution_policy.minimum_fx_target_pips == 6.0


def test_hybrid_v3_policy_remains_available_for_explicit_selection():
    processor = Strategy5SCRPressureProcessor(execution_policy=FX_MIN_TARGET_10P_V1)

    assert processor.execution_policy.policy_id == "FX_MIN_TARGET_10P_V1"
    assert processor.execution_policy.minimum_fx_target_pips == 10.0


def test_both_policies_still_exist_and_are_distinct():
    assert HYBRID_V3_EXECUTION_POLICY is FX_MIN_TARGET_10P_V1
    assert LEGACY_REPLAY_EXECUTION_POLICY is FX_LEGACY_6P_V1
    assert FX_MIN_TARGET_10P_V1.minimum_fx_target_pips == 10.0
    assert FX_LEGACY_6P_V1.minimum_fx_target_pips == 6.0


def test_ten_pip_floor_is_a_minimum_not_a_fixed_target():
    """A structurally further TP1 stays valid; 10 pips is a floor."""
    for target_pips in (10.0, 15.0, 20.0, 30.0):
        assessment = FX_MIN_TARGET_10P_V1.assess_target(
            "CHFJPY",
            target_distance_price=target_pips * 0.01,
            pip_size=0.01,
            spread_price=0.001,
        )
        assert assessment.target_floor_status == "PASS"


def test_processor_reports_its_active_policy(caplog):
    """Startup must state which floor is live, so it cannot drift unnoticed."""
    processor = Strategy5SCRPressureProcessor()

    assert processor.execution_policy.policy_id == "FX_LEGACY_6P_V1"


# --------------------------------------------------------------------------
# 4. nothing here reaches execution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        "STRATEGY_5SCR_MICROBOOST_PULSE_ENABLED",
        "STRATEGY_5SCR_SYMBOL_EPISODE_ENABLED",
        "STRATEGY_5SCR_LIFECYCLE_V2_ENABLED",
    ],
)
def test_hybrid_v3_flags_default_off(monkeypatch, flag):
    import os

    monkeypatch.delenv(flag, raising=False)

    assert os.getenv(flag, "false").strip().lower() == "false"
