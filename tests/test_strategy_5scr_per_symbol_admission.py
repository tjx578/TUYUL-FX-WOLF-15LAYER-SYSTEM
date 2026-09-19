"""G1/G1b acceptance: per-symbol isolated PairAdmission (rule per-symbol-isolated.v3) with global safety kept global."""

from __future__ import annotations

import csv
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_per_symbol_admission import evaluate_per_symbol_admission, replay_pair_admission
from analysis.strategy_5scr_raw_admission_blocks import RawAdmissionPopulation
from contracts.strategy_5scr_pair_admission import PAIR_ADMISSION_RULE_VERSION
from contracts.strategy_5scr_per_symbol_admission import (
    LEGACY_GLOBAL_STREAM_RULE_VERSION,
    PER_SYMBOL_ADMISSION_RULE_VERSION,
    GlobalSafetyStateV1,
    PerSymbolAdmissionEvaluationV3,
    PerSymbolAdmissionPolicyV3,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
POLICY = PerSymbolAdmissionPolicyV3(policy_id="test-policy.v1", min_duration_seconds=300, max_gap_seconds=300)


def _universe() -> tuple[str, ...]:
    path = ROOT / "ea_interface" / "wolf15_executor" / "broker_maps" / "xmglobal-mt5-10.csv"
    with path.open(encoding="utf-8") as handle:
        return tuple(row["canonical_symbol"] for row in csv.DictReader(handle))


UNIVERSE = _universe()


def _safety(**overrides: bool) -> GlobalSafetyStateV1:
    values = {
        "kill_switch_active": False,
        "account_or_executor_identity_ok": True,
        "authentication_ok": True,
        "database_and_governance_ok": True,
        "market_data_authority_ok": True,
        **overrides,
    }
    return GlobalSafetyStateV1(observed_at_utc=START, **values)


def _raw(seconds: float, symbol: str = "EURUSD", direction: str = "BUY") -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="warning",
        message="raw",
        symbol=symbol,
        event_type="ALLOWED",
        verdict=f"EXECUTE_{direction}",
        direction=direction,
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="deployment-A",
        scanner_cycle_id=f"cycle-{symbol}-{seconds}",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
    )


def _evaluate(events, *, safety=None, as_of_seconds: float = 400) -> PerSymbolAdmissionEvaluationV3:
    return evaluate_per_symbol_admission(
        events,
        universe=UNIVERSE,
        policy=POLICY,
        global_safety=safety or _safety(),
        as_of=START + timedelta(seconds=as_of_seconds),
    )


def test_universe_is_the_30_pair_broker_map_not_a_hardcoded_slot_count():
    assert len(UNIVERSE) == 30 and len(set(UNIVERSE)) == 30
    assert {"EURUSD", "GBPUSD", "CADJPY", "CHFJPY"} <= set(UNIVERSE)
    result = _evaluate([])
    assert set(result.lineages) == set(UNIVERSE)
    assert all(items == () for items in result.lineages.values())


def test_a_interleaved_symbol_does_not_close_another_symbols_lineage():
    events = [_raw(0), _raw(150, "GBPUSD", "SELL"), _raw(300)]
    result = _evaluate(events)
    (eurusd,) = result.lineages["EURUSD"]
    (gbpusd,) = result.lineages["GBPUSD"]
    assert eurusd.state == "ACTIVE" and eurusd.event_count == 2 and eurusd.closed_at is None
    assert (eurusd.decision, eurusd.reason_code) == ("GRANTED", "PER_SYMBOL_THRESHOLD_REACHED")
    assert eurusd.granted_at == START + timedelta(seconds=300)
    assert gbpusd.direction == "SELL" and gbpusd.state == "ACTIVE"
    assert (gbpusd.decision, gbpusd.reason_code) == (None, "PENDING_THRESHOLD")  # reason, not an authority status


def test_b_direction_flip_supersedes_only_the_same_symbol():
    neighbours = [_raw(10, "GBPUSD", "SELL"), _raw(20, "NZDUSD")]
    baseline = _evaluate(neighbours)
    result = _evaluate([_raw(0), *neighbours, _raw(100), _raw(200, direction="SELL"), _raw(350, direction="SELL")])
    old, new = result.lineages["EURUSD"]
    assert (old.state, old.state_reason_code) == ("SUPERSEDED", "DIRECTION_CHANGE_SUPERSEDED")
    assert old.superseded_by == new.lineage_id and old.closed_at == START + timedelta(seconds=100)
    assert (old.decision, old.reason_code) == ("REJECTED", "LINEAGE_ENDED_BELOW_THRESHOLD")
    assert new.direction == "SELL" and new.state == "ACTIVE" and new.lineage_id != old.lineage_id
    assert new.opened_at == START + timedelta(seconds=200)
    assert result.lineages["GBPUSD"] == baseline.lineages["GBPUSD"]
    assert result.lineages["NZDUSD"] == baseline.lineages["NZDUSD"]


def test_c_thirty_pair_interleave_has_zero_cross_symbol_contamination():
    rng = random.Random(20260919)
    events = []
    for symbol in UNIVERSE:
        direction = rng.choice(["BUY", "SELL"])
        seconds = 0.0
        for _ in range(rng.randint(2, 8)):
            seconds += rng.uniform(5, 120)
            if rng.random() < 0.15:
                direction = "SELL" if direction == "BUY" else "BUY"
            events.append(_raw(round(seconds, 3), symbol, direction))
    rng.shuffle(events)
    as_of = max(e.timestamp for e in events) + timedelta(seconds=1)
    together = evaluate_per_symbol_admission(
        events, universe=UNIVERSE, policy=POLICY, global_safety=_safety(), as_of=as_of
    )
    contamination = 0
    for symbol in UNIVERSE:
        alone = evaluate_per_symbol_admission(
            [e for e in events if e.symbol == symbol],
            universe=UNIVERSE,
            policy=POLICY,
            global_safety=_safety(),
            as_of=as_of,
        )
        contamination += together.lineages[symbol] != alone.lineages[symbol]
    assert contamination == 0  # CROSS_SYMBOL_CONTAMINATION = 0
    assert all(item.state_reason_code != "CROSS_SYMBOL_EVENT" for items in together.lineages.values() for item in items)
    assert together.ranking is None


def test_d_pair_local_fault_stays_pair_local():
    malformed = replace(_raw(50, "CADJPY"), timestamp="not-a-timestamp")
    healthy = [_raw(0), _raw(300)]
    stale_other = [_raw(0, "CHFJPY")]
    result = _evaluate([*healthy, malformed, _raw(10, "CADJPY"), *stale_other], as_of_seconds=400)
    assert result.symbol_faults == {"CADJPY": "MALFORMED_RAW_EVENT"}
    assert all(item.decision == "SUSPENDED" for item in result.lineages["CADJPY"])
    (chfjpy,) = result.lineages["CHFJPY"]
    assert (chfjpy.state, chfjpy.decision) == ("SUSPENDED", "SUSPENDED")  # stale beyond max gap, local only
    assert result.lineages["EURUSD"] == _evaluate(healthy, as_of_seconds=400).lineages["EURUSD"]
    assert result.lineages["EURUSD"][0].decision == "GRANTED"
    assert result.global_vetoes == ()


@pytest.mark.parametrize(
    "override",
    [
        {"kill_switch_active": True},
        {"account_or_executor_identity_ok": False},
        {"authentication_ok": False},
        {"database_and_governance_ok": False},
        {"market_data_authority_ok": False},
    ],
)
def test_e_global_veto_is_an_overlay_that_blocks_progression_without_rewriting_lineages(override):
    events = [_raw(0), _raw(300), _raw(0, "GBPUSD", "SELL"), _raw(100, "GBPUSD", "SELL"), _raw(0, "CHFJPY")]
    healthy = _evaluate(events)
    vetoed = _evaluate(events, safety=_safety(**override))
    assert vetoed.global_vetoes and healthy.global_vetoes == ()
    assert (vetoed.effective_state, vetoed.progression_allowed, vetoed.effective_grants) == (
        "GLOBAL_SAFETY_VETO",
        False,
        (),
    )
    assert (healthy.effective_state, healthy.progression_allowed) == ("PROGRESSION_ALLOWED", True)
    assert healthy.effective_grants == (healthy.lineages["EURUSD"][0].lineage_id,)
    assert vetoed.lineages == healthy.lineages  # underlying per-symbol lineage UNCHANGED
    assert vetoed.lineages["EURUSD"][0].decision == "GRANTED"
    assert (vetoed.lineages["GBPUSD"][0].decision, vetoed.lineages["GBPUSD"][0].reason_code) == (
        None,
        "PENDING_THRESHOLD",
    )
    assert vetoed.lineages["CHFJPY"][0].decision == "SUSPENDED"


def test_f_legacy_rule_version_replays_global_stream_semantics_unchanged():
    assert LEGACY_GLOBAL_STREAM_RULE_VERSION == PAIR_ADMISSION_RULE_VERSION == "5scr.pair-admission.raw-ledger.v2"
    assert PER_SYMBOL_ADMISSION_RULE_VERSION != LEGACY_GLOBAL_STREAM_RULE_VERSION
    events = [_raw(0), _raw(150, "GBPUSD", "SELL"), _raw(300)]
    legacy = replay_pair_admission(LEGACY_GLOBAL_STREAM_RULE_VERSION, events, max_gap_seconds=300.0)
    assert isinstance(legacy, RawAdmissionPopulation)
    first = legacy.blocks[0]
    assert (first.symbol, first.finalization_reason, first.cross_symbol_interruption_count) == (
        "EURUSD",
        "CROSS_SYMBOL_EVENT",
        1,
    )
    assert [block.symbol for block in legacy.blocks] == ["EURUSD", "GBPUSD", "EURUSD"]
    isolated = replay_pair_admission(
        PER_SYMBOL_ADMISSION_RULE_VERSION,
        events,
        universe=UNIVERSE,
        policy=POLICY,
        global_safety=_safety(),
        as_of=START + timedelta(seconds=400),
    )
    assert isinstance(isolated, PerSymbolAdmissionEvaluationV3)
    assert len(isolated.lineages["EURUSD"]) == 1
    with pytest.raises(ValueError, match="unknown pair admission rule version"):
        replay_pair_admission("5scr.pair-admission.unknown", events)


def test_gap_suspends_only_that_symbol_and_does_not_supersede():
    result = _evaluate([_raw(0), _raw(500), _raw(10, "GBPUSD", "SELL"), _raw(480, "GBPUSD", "SELL")], as_of_seconds=520)
    first, second = result.lineages["EURUSD"]
    assert (first.state, first.state_reason_code, first.superseded_by) == ("SUSPENDED", "SUSPENDED_SOURCE_GAP", None)
    assert second.state == "ACTIVE"
    assert [item.state for item in result.lineages["GBPUSD"]] == ["SUSPENDED", "ACTIVE"]


def test_out_of_universe_and_non_authority_events_never_contaminate():
    canary = replace(
        _raw(20), pressure_source="signal_throttle_check", source_stream="CANARY", event_type="PRESSURE_CANARY"
    )
    result = _evaluate([_raw(0), _raw(300), _raw(10, "USDSEK"), canary])
    assert result.ignored_out_of_universe_events == 1 and result.ignored_non_authority_events == 1
    assert result.lineages["EURUSD"] == _evaluate([_raw(0), _raw(300)]).lineages["EURUSD"]


def test_policy_has_no_defaults():
    with pytest.raises(ValueError):
        PerSymbolAdmissionPolicyV3()  # type: ignore[call-arg]
