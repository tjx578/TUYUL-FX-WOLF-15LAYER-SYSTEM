from __future__ import annotations

from copy import deepcopy

import pytest

from analysis.strategy_5scr_analysis_admission import evaluate_strategy_analysis_admission
from contracts.strategy_5scr_analysis_admission import StrategyAnalysisAdmissionV1


def _usdchf_advisory(**overrides):
    payload = {
        "symbol": "USDCHF",
        "deployment_id": "deployment-target",
        "cluster_id": "USDCHF_PRESSURE_EPISODE",
        "pressure_source": "signal_throttle_check",
        "source_stream": "CANARY",
        "raw_direction_role": "SHORT_HORIZON_PRESSURE_RADAR_ONLY",
        "raw_direction": "SELL",
        "candidate_direction": "SELL",
        "watch_direction": "SELL",
        "block_direction": "SELL",
        "pressure_direction_consensus_status": "ALIGNED",
        "block_start_utc": "2026-08-17T06:01:09+00:00",
        "block_duration_seconds": 3040.073,
        "block_effective_ticks": 1499,
        "raw_direction_eligible_for_context_resolution": True,
        "pressure_direction_resolution": "UNRESOLVED",
        "raw_direction_expires_at_utc": "2026-08-17T14:51:45+00:00",
        "signal_valid_time_utc": "2026-08-17T06:51:45+00:00",
        "generated_at_utc": "2026-08-17T06:51:46+00:00",
        "quote_health_status": "LIVE",
        "material_context_hash": "sha256:" + "a" * 64,
        "htf_structure_context": {
            "daily_bias": "BULLISH",
            "h4_structure": "RANGE",
            "price_location": "PREMIUM",
            "allowed_playbook": "WAIT_FOR_BUY_LOCATION",
            "blocked_playbook": ["SELL_LIMIT", "SELL_BREAKOUT_CHASE"],
        },
        "pair_admission_status": "NOT_GRANTED",
    }
    payload.update(overrides)
    return payload


def _canonical_grant(**overrides):
    payload = {
        "event": "pair_admission_granted",
        "schema_version": "1.0",
        "rule_version": "5scr.pair-admission.raw-ledger.v2",
        "pair_admission_id": "5scr-admission:" + "b" * 32,
        "status": "GRANTED",
        "ledger_scope": "GLOBAL_SIGNAL_THROTTLE_RAW_LEDGER",
        "deployment_id": "deployment-target",
        "symbol": "USDCHF",
        "direction": "SELL",
        "episode_started_at_utc": "2026-08-17T06:45:00+00:00",
        "episode_observed_through_utc": "2026-08-17T06:50:00+00:00",
        "granted_at_utc": "2026-08-17T06:50:00+00:00",
        "expires_at_utc": "2026-08-17T07:05:00+00:00",
        "duration_seconds": 300.0,
        "effective_ticks": 3,
        "source_event_count": 2,
        "max_observed_gap_seconds": 300.0,
        "maximum_allowed_gap_seconds": 300.0,
        "source_ledger_event_ids": ["raw-event-1", "raw-event-2"],
        "source_scanner_cycle_ids": ["scanner-cycle-1"],
        "source_ledger_hash": "sha256:" + "c" * 64,
    }
    payload.update(overrides)
    return payload


def test_mature_aligned_sell_advisory_opens_shadow_analysis_without_risk_authority() -> None:
    admission = evaluate_strategy_analysis_admission(_usdchf_advisory())

    assert admission.admission_class == "MATURE_ADVISORY"
    assert admission.admission_status == "GRANTED"
    assert admission.pressure_direction == "SELL"
    assert admission.advisory_maturity == "EXTREME"
    assert admission.analysis_state == "ADVISORY_WAITING_H1"
    assert admission.strategy_next_required_stage == "STRICT_H1_M15_SELL_CONFIRMATION"
    assert admission.context_alignment == "CONTEXT_CONFLICT"
    assert admission.structural_evidence_prefetch_required is True
    assert admission.shadow_tradeplan_allowed is True
    assert admission.risk_authority is False
    assert admission.execution_authority is False
    assert admission.valid_for_execution is False
    assert admission.final_direction == "WAIT"


def test_frozen_quote_keeps_admission_and_waits_for_price_quality() -> None:
    admission = evaluate_strategy_analysis_admission(_usdchf_advisory(quote_health_status="PRICE_FROZEN"))

    assert admission.admission_status == "GRANTED"
    assert admission.analysis_state == "ADVISORY_WAITING_PRICE_QUALITY"
    assert admission.strategy_next_required_stage == "PRICE_QUALITY_THEN_H1_M15_SELL_CONFIRMATION"
    assert "LIVE_ENTRY_PRICE_QUALITY_BLOCKED" in admission.reason_codes
    assert admission.execution_authority is False


def test_sticky_telemetry_does_not_remint_the_logical_analysis_admission() -> None:
    first_payload = _usdchf_advisory()
    repeated_payload = deepcopy(first_payload)
    repeated_payload["generated_at_utc"] = "2026-08-17T06:55:00+00:00"
    repeated_payload["pressure_state_emitted"] = 10_000

    first = evaluate_strategy_analysis_admission(first_payload)
    repeated = evaluate_strategy_analysis_admission(repeated_payload)

    assert repeated.analysis_admission_id == first.analysis_admission_id
    assert repeated.admitted_at_utc == first.admitted_at_utc
    assert repeated.analysis_material_hash == first.analysis_material_hash
    assert repeated.evidence_hash == first.evidence_hash


def test_quote_recovery_keeps_lifecycle_identity_but_requests_new_material_evidence() -> None:
    frozen = evaluate_strategy_analysis_admission(_usdchf_advisory(quote_health_status="PRICE_FROZEN"))
    recovered = evaluate_strategy_analysis_admission(_usdchf_advisory(quote_health_status="LIVE"))

    assert recovered.analysis_admission_id == frozen.analysis_admission_id
    assert recovered.analysis_material_hash != frozen.analysis_material_hash
    assert frozen.analysis_state == "ADVISORY_WAITING_PRICE_QUALITY"
    assert recovered.analysis_state == "ADVISORY_WAITING_H1"


def test_direction_lineage_conflict_suspends_without_buy_or_sell_hypothesis() -> None:
    admission = evaluate_strategy_analysis_admission(
        _usdchf_advisory(
            block_direction="BUY",
            pressure_direction_consensus_status="CONFLICT",
        )
    )

    assert admission.admission_status == "SUSPENDED"
    assert admission.pressure_direction == "CONFLICT"
    assert admission.analysis_state == "ADVISORY_WAITING_PRESSURE_RESOLUTION"
    assert admission.context_resolution_allowed is False
    assert admission.structural_evidence_prefetch_required is False
    assert admission.shadow_tradeplan_allowed is False


def test_immature_advisory_is_observed_but_not_admitted() -> None:
    admission = evaluate_strategy_analysis_admission(
        _usdchf_advisory(block_duration_seconds=12.0, block_effective_ticks=3)
    )

    assert admission.admission_status == "REJECTED"
    assert admission.advisory_maturity == "IMMATURE"
    assert admission.analysis_state == "ADVISORY_OBSERVED_IMMATURE"
    assert admission.strategy_next_required_stage == "PRESSURE_MATURITY"


def test_canonical_pair_admission_maps_to_the_higher_analysis_contract() -> None:
    admission = evaluate_strategy_analysis_admission(
        _usdchf_advisory(
            pair_admission_status="GRANTED",
            pair_admission_id="5scr-admission:" + "b" * 32,
            pair_admission_granted_at_utc="2026-08-17T06:50:00+00:00",
            pair_admission_expires_at_utc="2026-08-17T07:05:00+00:00",
            pair_admission_rule_version="5scr.pair-admission.raw-ledger.v2",
            pair_admission_source_ledger_hash="sha256:" + "c" * 64,
            pair_admission_grant=_canonical_grant(),
        )
    )

    assert admission.admission_class == "CANONICAL_RAW"
    assert admission.admission_status == "GRANTED"
    assert admission.analysis_authority == "FULL_CANONICAL_ANALYSIS"
    assert admission.source_authority == "RAW_SIGNAL_THROTTLE_LEDGER"
    assert admission.pair_admission_id == "5scr-admission:" + "b" * 32
    assert admission.risk_authority is False
    assert admission.execution_authority is False


@pytest.mark.parametrize(
    "overrides",
    (
        {"pair_admission_grant": None},
        {"pair_admission_rule_version": "legacy"},
        {"pair_admission_source_ledger_hash": "sha256:" + "d" * 64},
        {"pair_admission_grant": _canonical_grant(ledger_scope="DERIVED_PRESSURE_ADVISORY")},
    ),
)
def test_unproven_pair_admission_cannot_claim_canonical_raw_authority(overrides) -> None:
    canonical_fields = {
        "pair_admission_status": "GRANTED",
        "pair_admission_id": "5scr-admission:" + "b" * 32,
        "pair_admission_rule_version": "5scr.pair-admission.raw-ledger.v2",
        "pair_admission_source_ledger_hash": "sha256:" + "c" * 64,
        "pair_admission_grant": _canonical_grant(),
    }
    canonical_fields.update(overrides)
    payload = _usdchf_advisory(**canonical_fields)

    admission = evaluate_strategy_analysis_admission(payload)

    assert admission.admission_class == "MATURE_ADVISORY"
    assert admission.source_authority == "DERIVED_PRESSURE_ADVISORY"
    assert admission.risk_authority is False
    assert admission.execution_authority is False


def test_contract_cannot_be_mutated_into_execution_authority() -> None:
    payload = evaluate_strategy_analysis_admission(_usdchf_advisory()).model_dump(mode="python")
    payload["execution_authority"] = True

    with pytest.raises(ValueError):
        StrategyAnalysisAdmissionV1.model_validate(payload)
