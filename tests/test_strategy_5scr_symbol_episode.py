"""Durable market-episode grouping for LIVE pressure without canonical lineage.

``cluster_id`` is a per-emission transport identifier -- unique in every record
of the repo's own archive cohort -- so keying a LIVE lifecycle on it splits one
market story into as many pseudo-lifecycles as there were emissions.

Episode grouping repairs the *analysis* view only.  The safety gate is
unchanged and asserted here: an episode-anchored lifecycle is never
execution-grade and still defers the tradeplan.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_pressure_to_tradeplan import (
    PressureEventNormalizer,
    PressureLifecycleAccumulator,
    PressureToTradePlanBuilder,
    symbol_episode_enabled,
)
from contracts.strategy_5scr_execution_policy import FX_LEGACY_6P_V1
from contracts.strategy_5scr_pressure import PressureLifecycle, SymbolEpisodePolicy


def _payload(*, symbol="CHFJPY", at="2026-07-17T13:05:00+00:00", direction="BUY", cluster=None):
    return {
        "event": "signal_pressure_state_json",
        "schema_version": "2.0-pressure-state",
        "symbol": symbol,
        # Mirrors production: a microsecond-stamped, per-emission identifier.
        "cluster_id": cluster or f"{symbol}_{at}_MICROBOOST_WATCH",
        "promotion_stage": "PRESSURE_ONLY",
        "raw_direction": direction,
        "final_direction": "WAIT",
        "signal_valid_time_utc": at,
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "pressure_seen": True,
        "pressure_event_count": 3,
        "pressure_level": "MICROBOOST_WATCH",
        "pressure_strength": "MICROBOOST",
    }


def _record(payload):
    return {
        "message": "[SignalPressureStateJSON] " + json.dumps(payload, separators=(",", ":")),
        "timestamp": payload["signal_valid_time_utc"],
    }


def _live_lifecycles(payloads, *, episode_policy):
    normalizer = PressureEventNormalizer(input_mode="LIVE")
    accumulator = PressureLifecycleAccumulator(episode_policy=episode_policy)
    for payload in payloads:
        accumulator.ingest(normalizer.normalize(_record(payload)))
    return accumulator.snapshots()


def _three_emissions():
    return [
        _payload(at="2026-07-17T13:05:00+00:00"),
        _payload(at="2026-07-17T13:07:00+00:00"),
        _payload(at="2026-07-17T13:09:00+00:00"),
    ]


# --------------------------------------------------------------------------
# the fragmentation this fixes
# --------------------------------------------------------------------------


def test_without_episode_grouping_each_emission_is_its_own_lifecycle():
    """Documents the current default: compression 1.0."""
    lifecycles = _live_lifecycles(_three_emissions(), episode_policy=None)

    assert len(lifecycles) == 3
    assert all(item.campaign_anchor_source == "UNRESOLVED" for item in lifecycles)


def test_episode_grouping_folds_one_symbol_story_into_one_lifecycle():
    lifecycles = _live_lifecycles(_three_emissions(), episode_policy=SymbolEpisodePolicy())

    assert len(lifecycles) == 1
    lifecycle = lifecycles[0]
    assert lifecycle.campaign_anchor_source == "SYMBOL_EPISODE"
    assert len(lifecycle.event_ids) == 3
    assert lifecycle.campaign_id.startswith("episode:CHFJPY:")


def test_episode_id_is_not_derived_from_cluster_id():
    lifecycles = _live_lifecycles(_three_emissions(), episode_policy=SymbolEpisodePolicy())
    campaign_id = lifecycles[0].campaign_id

    assert "MICROBOOST_WATCH" not in campaign_id


# --------------------------------------------------------------------------
# episode boundaries
# --------------------------------------------------------------------------


def test_gap_beyond_policy_starts_a_new_episode():
    payloads = [
        _payload(at="2026-07-17T13:05:00+00:00"),
        _payload(at="2026-07-17T13:40:00+00:00"),  # 35 min > 15 min policy
    ]
    lifecycles = _live_lifecycles(payloads, episode_policy=SymbolEpisodePolicy())

    assert len(lifecycles) == 2


def test_direction_flip_splits_the_episode():
    payloads = [
        _payload(at="2026-07-17T13:05:00+00:00", direction="BUY"),
        _payload(at="2026-07-17T13:07:00+00:00", direction="SELL"),
    ]
    lifecycles = _live_lifecycles(payloads, episode_policy=SymbolEpisodePolicy())

    assert len(lifecycles) == 2


def test_direction_flip_can_be_merged_when_policy_allows():
    payloads = [
        _payload(at="2026-07-17T13:05:00+00:00", direction="BUY"),
        _payload(at="2026-07-17T13:07:00+00:00", direction="SELL"),
    ]
    lifecycles = _live_lifecycles(
        payloads, episode_policy=SymbolEpisodePolicy(split_on_direction_flip=False)
    )

    assert len(lifecycles) == 1
    # Conflicting raw pressure resolves to no directional claim.
    assert lifecycles[0].raw_direction is None


def test_separate_symbols_never_share_an_episode():
    payloads = [
        _payload(symbol="CHFJPY", at="2026-07-17T13:05:00+00:00"),
        _payload(symbol="NZDCAD", at="2026-07-17T13:06:00+00:00"),
    ]
    lifecycles = _live_lifecycles(payloads, episode_policy=SymbolEpisodePolicy())

    assert len(lifecycles) == 2
    assert {item.symbol for item in lifecycles} == {"CHFJPY", "NZDCAD"}


def test_duplicate_emission_does_not_create_a_second_lifecycle():
    payload = _payload()
    lifecycles = _live_lifecycles([payload, payload, payload], episode_policy=SymbolEpisodePolicy())

    assert len(lifecycles) == 1
    assert len(lifecycles[0].event_ids) == 1


# --------------------------------------------------------------------------
# safety: analysis grouping is not execution authority
# --------------------------------------------------------------------------


def test_episode_lifecycle_is_never_execution_grade():
    lifecycles = _live_lifecycles(_three_emissions(), episode_policy=SymbolEpisodePolicy())

    assert lifecycles[0].campaign_anchor_execution_grade is False


def test_contract_rejects_an_execution_grade_episode_anchor():
    with pytest.raises(ValidationError, match="analysis-only"):
        PressureLifecycle(
            campaign_id="episode:CHFJPY:x",
            campaign_anchor_source="SYMBOL_EPISODE",
            campaign_anchor_execution_grade=True,
            input_mode="LIVE",
            symbol="CHFJPY",
            started_at_utc="2026-07-17T13:05:00+00:00",
            updated_at_utc="2026-07-17T13:05:00+00:00",
            event_ids=("sha256:" + "a" * 64,),
            latest_cluster_id="cluster",
            selected_by_pressure=True,
        )


def test_episode_lifecycle_still_defers_the_tradeplan():
    """Grouping improves analysis depth; it must not unlock execution."""
    from tests.test_strategy_5scr_pressure_to_tradeplan import _evidence

    lifecycles = _live_lifecycles(_three_emissions(), episode_policy=SymbolEpisodePolicy())
    result = PressureToTradePlanBuilder(execution_policy=FX_LEGACY_6P_V1).build(
        lifecycles[0], _evidence()
    )

    assert result.decision == "DEFER"
    assert "STRATEGY_5SCR_CANONICAL_LIFECYCLE_REQUIRED" in result.reasons
    assert result.tradeplan is None


def test_canonical_clean_block_anchor_still_wins_over_episode_grouping():
    payload = _payload()
    payload["source_clean_block_id"] = "CHFJPY_20260717T130000Z_20260717T130500Z"
    lifecycles = _live_lifecycles([payload], episode_policy=SymbolEpisodePolicy())

    assert lifecycles[0].campaign_anchor_source == "SOURCE_CLEAN_BLOCK_ID"
    assert lifecycles[0].campaign_anchor_execution_grade is True


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("STRATEGY_5SCR_SYMBOL_EPISODE_ENABLED", raising=False)
    assert symbol_episode_enabled() is False
    assert PressureLifecycleAccumulator().episode_policy is None

    monkeypatch.setenv("STRATEGY_5SCR_SYMBOL_EPISODE_ENABLED", "true")
    assert symbol_episode_enabled() is True
    assert PressureLifecycleAccumulator().episode_policy is not None


def test_explicit_none_beats_the_environment(monkeypatch):
    """Outbox replay must reproduce persisted lifecycle ids regardless of env."""
    monkeypatch.setenv("STRATEGY_5SCR_SYMBOL_EPISODE_ENABLED", "true")

    assert PressureLifecycleAccumulator(episode_policy=None).episode_policy is None
