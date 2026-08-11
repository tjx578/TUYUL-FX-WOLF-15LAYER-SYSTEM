from __future__ import annotations

from decimal import Decimal

from analysis.strategy_5scr_v3.pressure.legacy_580_adapter import Legacy580PressureAdapter
from analysis.strategy_5scr_v3.pressure.live_outbox_adapter import LivePressureOutboxAdapter
from analysis.strategy_5scr_v3.pressure.semantic_projection import semantic_projection
from tests.pressure_emission_v3_helpers import live_envelope, load_fixture, railway_record


def test_legacy_and_live_equivalents_have_semantic_not_payload_parity() -> None:
    legacy_payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    live_payload = load_fixture("live_equivalents", "equivalent_chfjpy.json")
    legacy = Legacy580PressureAdapter().normalize(railway_record(legacy_payload))
    live = LivePressureOutboxAdapter().normalize(live_envelope(live_payload))

    assert semantic_projection(legacy) == semantic_projection(live)
    assert legacy.identity.semantic_projection_hash == live.identity.semantic_projection_hash
    assert legacy.identity.source_payload_hash != live.identity.source_payload_hash
    assert legacy.identity.transport_event_id != live.identity.transport_event_id
    assert legacy.deployment.deployment_id is None
    assert live.deployment.deployment_id == "railway-deployment-live"
    assert legacy.price.observed_price is None
    assert live.price.observed_price == 190.51
    assert legacy.source_lineage.admission_event_id is None
    assert live.source_lineage.admission_event_id is not None


def test_transport_provenance_churn_does_not_change_semantic_hash() -> None:
    first_payload = load_fixture("live_equivalents", "equivalent_chfjpy.json")
    second_payload = dict(first_payload)
    second_payload.update(
        deployment_id="other-deployment",
        commit_sha="other-commit",
        replica_id="other-replica",
        cluster_id="other-transport-cluster",
    )
    adapter = LivePressureOutboxAdapter()

    first = adapter.normalize(live_envelope(first_payload))
    second = adapter.normalize(live_envelope(second_payload))

    assert first.identity.source_payload_hash != second.identity.source_payload_hash
    assert first.identity.semantic_projection_hash == second.identity.semantic_projection_hash


def test_mapping_order_and_wrapper_provenance_do_not_change_semantic_hash() -> None:
    payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    reordered = dict(reversed(tuple(payload.items())))
    context = dict(reordered["htf_structure_context"])  # type: ignore[arg-type]
    reordered["htf_structure_context"] = dict(reversed(tuple(context.items())))
    adapter = Legacy580PressureAdapter()

    first = adapter.normalize(railway_record(payload))
    second_record = railway_record(reordered)
    second_record["timestamp"] = "2026-07-17T13:05:01.900Z"
    second = adapter.normalize(second_record)

    assert first.identity.source_payload_hash == second.identity.source_payload_hash
    assert first.identity.semantic_projection_hash == second.identity.semantic_projection_hash
    assert first.time.received_at_utc != second.time.received_at_utc


def test_material_semantics_change_the_semantic_hash() -> None:
    payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    adapter = Legacy580PressureAdapter()
    baseline = adapter.normalize(payload).identity.semantic_projection_hash

    direction = dict(payload)
    direction["raw_direction"] = "BUY"
    context = dict(payload)
    context["htf_structure_context"] = {
        **dict(payload["htf_structure_context"]),  # type: ignore[arg-type]
        "daily_bias": "BULLISH",
    }
    microboost = dict(payload)
    microboost["microboost_detected"] = False

    assert adapter.normalize(direction).identity.semantic_projection_hash != baseline
    assert adapter.normalize(context).identity.semantic_projection_hash != baseline
    assert adapter.normalize(microboost).identity.semantic_projection_hash != baseline


def test_numeric_spelling_and_missing_vs_null_have_explicit_semantics() -> None:
    payload = load_fixture("legacy_580", "equivalent_chfjpy.json")
    decimal_payload = dict(payload)
    decimal_payload["reference_price"] = Decimal("190.5000")
    absent = dict(payload)
    absent.pop("candidate_direction")
    explicit_null = dict(payload)
    explicit_null["candidate_direction"] = None
    adapter = Legacy580PressureAdapter()

    baseline = adapter.normalize(payload)
    numeric = adapter.normalize(decimal_payload)
    missing = adapter.normalize(absent)
    null = adapter.normalize(explicit_null)

    assert numeric.identity.source_payload_hash != baseline.identity.source_payload_hash
    assert numeric.identity.semantic_projection_hash == baseline.identity.semantic_projection_hash
    assert missing.identity.source_payload_hash != null.identity.source_payload_hash
    assert missing.identity.semantic_projection_hash == null.identity.semantic_projection_hash
