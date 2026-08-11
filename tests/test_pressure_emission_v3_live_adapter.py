from __future__ import annotations

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_v3.pressure.live_outbox_adapter import LivePressureOutboxAdapter
from analysis.strategy_5scr_v3.pressure.normalization_errors import (
    PressureEmissionNormalizationError,
)
from storage.pressure_outbox import pressure_payload_hash
from tests.pressure_emission_v3_helpers import live_envelope, load_fixture


def test_live_adapter_preserves_only_available_canonical_references() -> None:
    envelope = live_envelope(load_fixture("live_equivalents", "equivalent_chfjpy.json"))
    emission = LivePressureOutboxAdapter().normalize(envelope)

    assert emission.identity.normalization_profile == "LIVE_PRESSURE_OUTBOX"
    assert emission.source_lineage.admission_event_id == envelope.lifecycle_id
    assert emission.source_lineage.source_clean_block_id == envelope.source_clean_block_id
    assert emission.source_lineage.active_block_id is None
    assert emission.context_seed.context_epoch_reference == "5scr-context:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert emission.execution_authority is False


def test_live_adapter_rejects_outbox_payload_hash_mismatch() -> None:
    envelope = live_envelope(load_fixture("live_equivalents", "equivalent_chfjpy.json"))
    forged = envelope.model_copy(update={"payload_hash": "f" * 64})

    with pytest.raises(PressureEmissionNormalizationError, match="PAYLOAD_HASH_MISMATCH"):
        LivePressureOutboxAdapter().normalize(forged)


def test_live_adapter_requires_full_durable_outbox_contract() -> None:
    with pytest.raises(ValidationError):
        LivePressureOutboxAdapter().normalize({"payload": {}})


def test_live_adapter_does_not_accept_legacy_pair_eligibility_as_admission() -> None:
    envelope = live_envelope(load_fixture("live_equivalents", "equivalent_chfjpy.json"))
    unsafe = envelope.model_dump(mode="python")
    payload = dict(unsafe["payload"])
    payload.update(pair_admission_status="NOT_GRANTED", pair_eligible_for_analysis=True)
    unsafe["payload"] = payload
    unsafe["payload_hash"] = pressure_payload_hash(payload)

    with pytest.raises(ValidationError, match="canonical pair admission"):
        LivePressureOutboxAdapter().normalize(unsafe)
