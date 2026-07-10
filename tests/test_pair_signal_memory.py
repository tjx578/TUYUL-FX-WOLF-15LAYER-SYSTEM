from __future__ import annotations

from analysis.pair_signal_memory import PairSignalMemoryStore, build_pair_memory_context


def _watch(**overrides):
    payload = {
        "symbol": "GBPCAD",
        "signal_id": "GBPCAD_BUY_WATCH_1",
        "cluster_id": "GBPCAD_BLOCK_1",
        "signal_family": "CLEAN_BLOCK_BUY_WATCH",
        "status": "CLEAN_BLOCK_BUY_WATCH",
        "watch_direction": "BUY",
        "candidate_direction": "BUY",
        "signal_valid_time_utc": "2026-05-08T04:29:00+00:00",
        "signal_valid_time_wita": "2026-05-08 12:29:00",
        "signal_valid_price": 1.85414,
        "entry_reference_price": 1.85414,
        "price_position": "MID_RANGE",
        "m15_phase": "BULLISH_UPPER_RANGE",
        "h1_phase": "BULLISH",
        "effective_density": 2.23,
        "source_clean_block_id": "GBPCAD_EARLY_BLOCK",
        "valid_for_execution": False,
    }
    payload.update(overrides)
    return payload


def test_pair_memory_marks_first_watch_as_fresh_observability_only():
    context = build_pair_memory_context(_watch())

    assert context["memory_available"] is False
    assert context["lifecycle_transition"] == "FIRST_VALID_PRESSURE"
    assert context["phase_structure_validation"] == "FRESH_SIGNAL_NO_MEMORY"
    assert context["recommended_interpretation"] == "TRACK_AS_FRESH_WATCH_CONTEXT"
    assert context["valid_for_execution"] is False
    assert context["execution_impact"] is False


def test_pair_memory_classifies_gbpcad_followthrough_as_late_after_pre_move():
    store = PairSignalMemoryStore()
    first = _watch()
    current = _watch(
        signal_id="GBPCAD_ACCELERATION_1645",
        cluster_id="GBPCAD_ACCELERATION_BLOCK",
        signal_family="MICROBOOST_ACCELERATION",
        status="MICROBOOST_WATCH",
        signal_valid_time_utc="2026-05-08T08:45:00+00:00",
        signal_valid_time_wita="2026-05-08 16:45:00",
        signal_valid_price=1.85890,
        entry_reference_price=1.85890,
        price_position="UPPER_RANGE",
        m15_phase="BULLISH_CONTINUATION",
        h1_phase="BULLISH",
        effective_density=11.44,
        source_clean_block_id="GBPCAD_ACCELERATION_BLOCK",
    )

    store.enrich_watch_payload(first, material_state="first")
    store.enrich_watch_payload(current, material_state="current")

    context = current["pair_memory_context"]
    assert context["memory_available"] is True
    assert context["previous_valid_signal_id"] == "GBPCAD_BUY_WATCH_1"
    assert context["minutes_since_previous_valid"] == 256.0
    assert context["price_delta_from_previous_valid_pips"] == 47.6
    assert context["lifecycle_transition"] == "LATE_PRESSURE_AFTER_PRE_MOVE"
    assert context["phase_structure_validation"] == "LATE_PRESSURE_AFTER_PRE_MOVE"
    assert context["recommended_interpretation"] == "HOLD_TRAIL_OR_RETEST_ONLY_NO_FRESH_CHASE"
    assert current["phase_structure_validation"] == "LATE_PRESSURE_AFTER_PRE_MOVE"


def test_pair_memory_classifies_chfjpy_failed_buy_as_absorption():
    store = PairSignalMemoryStore()
    first = _watch(
        symbol="CHFJPY",
        signal_id="CHFJPY_BUY_RESISTANCE_1",
        cluster_id="CHFJPY_BUY_BLOCK_1",
        signal_valid_time_utc="2026-07-09T13:00:00+00:00",
        signal_valid_price=201.1435,
        entry_reference_price=201.1435,
        price_position="MAIN_RESISTANCE",
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        source_clean_block_id="CHFJPY_BUY_BLOCK_1",
    )
    current = _watch(
        symbol="CHFJPY",
        signal_id="CHFJPY_BUY_RESISTANCE_2",
        cluster_id="CHFJPY_BUY_BLOCK_2",
        signal_family="MICROBOOST_WATCH",
        status="MICROBOOST_WATCH",
        signal_valid_time_utc="2026-07-09T14:00:00+00:00",
        signal_valid_price=201.0515,
        entry_reference_price=201.0515,
        price_position="MAIN_RESISTANCE",
        m15_phase="BEARISH_PULLBACK",
        h1_phase="BEARISH",
        effective_density=89.32,
        source_clean_block_id="CHFJPY_BUY_BLOCK_2",
    )

    store.enrich_watch_payload(first, material_state="first")
    store.enrich_watch_payload(current, material_state="current")

    context = current["pair_memory_context"]
    assert context["price_delta_from_previous_valid_pips"] == -9.2
    assert context["lifecycle_transition"] == "FAILED_BUY_PRESSURE_TO_ABSORPTION"
    assert context["phase_structure_validation"] == "ABSORPTION_CONFIRMED_BY_MEMORY"
    assert context["recommended_interpretation"] == "NO_CHASE_BUY_SELL_WATCH_PENDING_CONFIRMATION"
    assert context["valid_for_execution"] is False
