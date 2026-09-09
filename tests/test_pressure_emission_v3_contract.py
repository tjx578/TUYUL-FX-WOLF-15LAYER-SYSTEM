from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_v3.pressure.legacy_580_adapter import Legacy580PressureAdapter
from analysis.strategy_5scr_v3.pressure.normalization_errors import (
    PressureEmissionNormalizationError,
)
from tests.pressure_emission_v3_helpers import load_fixture, railway_record


def _legacy(**updates: object):
    payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    payload.update(updates)
    return Legacy580PressureAdapter().normalize(railway_record(payload))


def test_contract_is_immutable_partial_and_non_executable() -> None:
    emission = _legacy()

    assert emission.normalization.status == "PARTIAL"
    assert emission.execution_authority is False
    assert emission.source_safety.final_direction == "WAIT"
    assert emission.source_safety.valid_for_execution is False
    assert emission.source_safety.tradeplan_valid is False
    assert emission.source_safety.execution_valid_now is False
    assert "source_lineage.admission_event_id" in emission.normalization.missing_fields
    with pytest.raises(ValidationError):
        emission.symbol = "EURUSD"


def test_invalid_symbol_is_rejected() -> None:
    with pytest.raises(PressureEmissionNormalizationError):
        _legacy(symbol="bad symbol")


def test_invalid_source_time_uses_wrapper_only_in_quarantine() -> None:
    emission = _legacy(signal_valid_time_utc="not-a-time")

    assert emission.normalization.status == "QUARANTINED"
    assert "SOURCE_EVENT_TIME_INVALID_FALLBACK_RAILWAY_WRAPPER" in emission.normalization.reason_codes


def test_unknown_critical_direction_is_quarantined_not_invented() -> None:
    emission = _legacy(raw_direction="SIDEWAYS")

    assert emission.normalization.status == "QUARANTINED"
    assert emission.pressure.raw_direction is None
    assert "UNKNOWN_RAW_DIRECTION:SIDEWAYS" in emission.normalization.reason_codes


def test_executable_source_is_quarantined_while_output_stays_safe() -> None:
    emission = _legacy(final_direction="SELL", valid_for_execution=True)

    assert emission.normalization.status == "QUARANTINED"
    assert emission.source_safety.final_direction == "WAIT"
    assert emission.source_safety.valid_for_execution is False
    assert emission.execution_authority is False
    assert "PRESSURE_SOURCE_ATTEMPTED_EXECUTION_AUTHORITY" in emission.normalization.reason_codes


@pytest.mark.parametrize("unsafe", (True, 1, "true", "TRUE"))
def test_executable_looking_safety_values_are_not_silently_coerced(unsafe: object) -> None:
    emission = _legacy(valid_for_execution=unsafe)

    assert emission.normalization.status == "QUARANTINED"
    assert "PRESSURE_SOURCE_ATTEMPTED_EXECUTION_AUTHORITY" in emission.normalization.reason_codes
    assert emission.source_safety.valid_for_execution is False


def test_input_mapping_is_not_mutated() -> None:
    payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    before = deepcopy(payload)

    Legacy580PressureAdapter().normalize(payload)

    assert payload == before


def test_nested_contracts_and_sequences_are_immutable() -> None:
    emission = _legacy()

    with pytest.raises(ValidationError):
        emission.pressure.raw_direction = "BUY"
    with pytest.raises(TypeError):
        emission.normalization.missing_fields[0] = "changed"  # type: ignore[index]


def test_wrong_event_family_and_unknown_pressure_stage_are_distinct_quarantines() -> None:
    wrong_family = _legacy(event="signal_json")
    unknown_stage = _legacy(source_stage="SOME_NEW_PRESSURE_STAGE")

    assert wrong_family.normalization.status == "QUARANTINED"
    assert "WRONG_EVENT_FAMILY" in wrong_family.normalization.reason_codes
    assert unknown_stage.normalization.status == "QUARANTINED"
    assert "UNKNOWN_PRESSURE_STAGE:SOME_NEW_PRESSURE_STAGE" in unknown_stage.normalization.reason_codes


def test_legacy_authority_claims_are_not_promoted() -> None:
    emission = _legacy(
        pair_admission_id="5scr-admission:0123456789abcdef0123456789abcdef",
        pair_admission_status="GRANTED",
        pair_admission_rule_version="5scr.pair-admission.raw-ledger.v2",
        active_block_id="5scr-raw-block:0123456789abcdef0123456789abcdef",
        pair_eligible_for_analysis=True,
    )

    assert emission.pressure.pair_eligible_for_analysis is True
    assert emission.source_lineage.admission_event_id is None
    assert emission.source_lineage.active_block_id is None
    assert emission.execution_authority is False
    assert "LEGACY_AUTHORITY_REFERENCE_IGNORED" in emission.normalization.reason_codes
