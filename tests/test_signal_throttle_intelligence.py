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
    )

    emit_signal_throttle_intel(intel)

    assert capsys.readouterr().out.splitlines() == [
        "[SignalThrottleIntel] symbol=NZDCHF raw_direction=SELL final_direction=WAIT "
        "direction_status=ALLOWED_CANDIDATE phase=TIMING_VALID action=WAIT_PRICE_CONFIRMATION "
        "verdict=EXECUTE_SELL count=2 remaining=1 streak=2 max=3 window=300s "
        "reason=allowed_is_candidate_until_price_theme_structure_validation"
    ]
