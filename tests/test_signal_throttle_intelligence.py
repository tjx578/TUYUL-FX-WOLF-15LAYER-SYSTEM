from __future__ import annotations

from analysis.signal_throttle_intelligence import (
    classify_allowed_signal,
    emit_signal_throttle_intel,
)


def test_allowed_quorum_is_phase_not_final_direction():
    intel = classify_allowed_signal(
        symbol="AUDCAD",
        verdict="EXECUTE_REDUCED_RISK_BUY",
        l12_direction="BUY",
        synthesis={"execution": {"direction": "BUY"}},
        count=3,
        remaining=0,
        max_signals=3,
        window_seconds=300.0,
    )

    assert intel.raw_direction == "BUY"
    assert intel.final_direction == "WAIT"
    assert intel.direction_status == "CANARY_QUORUM_PENDING_VALIDATION"
    assert intel.phase == "ALLOWED_CANARY_QUORUM"
    assert intel.action == "WAIT_PRICE_THEME_STRUCTURE"
    assert intel.base_ccy == "AUD"
    assert intel.quote_ccy == "CAD"
    assert intel.symbol_orientation == "FX_BASE_QUOTE"
    assert intel.window_count_after == 3
    assert intel.window_remaining_after == 0
    assert intel.allowed_streak_before == 2
    assert intel.allowed_streak_after == 3
    assert intel.verdict_features_hash is not None
    assert len(intel.verdict_features_hash) == 16


def test_window_count_does_not_create_quorum_without_allowed_streak():
    intel = classify_allowed_signal(
        symbol="AUDCAD",
        verdict="EXECUTE_BUY",
        l12_direction="BUY",
        synthesis={"execution": {"direction": "BUY"}},
        count=3,
        remaining=0,
        max_signals=3,
        window_seconds=300.0,
        allowed_streak=1,
    )

    assert intel.phase == "IGNITION"
    assert intel.direction_status == "ALLOWED_CANDIDATE"


def test_allowed_direction_mismatch_blocks_entry_candidate():
    intel = classify_allowed_signal(
        symbol="GBPCAD",
        verdict="EXECUTE_BUY",
        l12_direction="SELL",
        synthesis={"execution": {"direction": "SELL"}},
        count=1,
        remaining=2,
        max_signals=3,
        window_seconds=300.0,
    )

    assert intel.raw_direction == "BUY"
    assert intel.final_direction == "BLOCK_DIRECTION"
    assert intel.direction_status == "DIRECTION_MISMATCH"
    assert intel.action == "BLOCK_ENTRY"
    assert intel.reason == "l12_direction=SELL_differs_from_verdict=BUY"


def test_signal_throttle_intel_log_is_parseable_info(capsys):
    intel = classify_allowed_signal(
        symbol="NZDCHF",
        verdict="EXECUTE_SELL",
        l12_direction="SELL",
        synthesis={},
        count=2,
        remaining=1,
        max_signals=3,
        window_seconds=300.0,
        count_before=1,
        remaining_before=2,
        verdict_source="POST_L12_PRE_V11",
    )

    emit_signal_throttle_intel(intel)

    line = capsys.readouterr().out.strip()
    assert line.startswith(
        "[SignalThrottleIntel] symbol=NZDCHF base_ccy=NZD quote_ccy=CHF "
        "symbol_orientation=FX_BASE_QUOTE raw_direction=SELL final_direction=WAIT "
        "direction_status=ALLOWED_CANDIDATE phase=TIMING_VALID action=WAIT_PRICE_CONFIRMATION "
        "verdict=EXECUTE_SELL verdict_source=POST_L12_PRE_V11 verdict_features_hash="
    )
    assert " count_before=1 count_after=2 count=2 " in line
    assert " remaining_before=2 remaining_after=1 remaining=1 " in line
    assert " streak_before=1 streak_after=2 streak=2 " in line
    assert line.endswith("max=3 window=300s reason=allowed_is_candidate_until_price_theme_structure_validation")
