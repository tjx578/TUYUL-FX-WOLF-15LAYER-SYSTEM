from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_context_route_v31 import (
    ContextRouteReceiptV31,
    MaterialContextV31,
    context_route_receipt_hash_v31,
    material_context_hash_v31,
)
from tests.test_strategy_5scr_capacity_v31 import NOW, H


def receipt(direction="BUY"):
    material = MaterialContextV31(
        d1_source_ids=("sha256:" + "1" * 64,),
        h4_source_ids=("sha256:" + "2" * 64,),
        d1_structure="FIXTURE_STRUCTURE",
        h4_structure="FIXTURE_STRUCTURE",
        price_location="FIXTURE_RANGE",
        liquidity_state="TESTING",
        primary_direction_domain=direction + "_ONLY",
        allowed_directions=(direction,),
        counter_pressure_policy_hash=H,
        counter_pressure_observation_allowed=True,
        counter_pressure_thesis_status="PROHIBITED",
        allowed_routes=("FIXTURE_CONTINUATION",),
        blocked_routes=(),
        target_map_version="fixture-map-v1",
        structural_invalidation_version="fixture-invalidation-v1",
        pressure_contract_status="OPEN",
    )
    return ContextRouteReceiptV31(
        profile="TEST_ONLY",
        context_epoch_id=UUID(int=6),
        strategy_lifecycle_id=UUID(int=3),
        symbol="EURUSD",
        state="ACTIVE",
        material=material,
        material_context_hash=material_context_hash_v31("EURUSD", material),
        registry_version="fixture-registry-v1",
        location_route_policy_hash=H,
        location_alignment="FAVORABLE",
        selected_route="FIXTURE_CONTINUATION",
        direction=direction,
        resolution_evidence_hash=H,
        source_closed_through=NOW - timedelta(hours=1),
        evaluated_at=NOW,
        valid_until=NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("counter_pressure_policy_hash", "sha256:" + "8" * 64),
        ("pressure_contract_status", "TRANSITION_PENDING"),
        ("d1_structure", "NEW_STRUCTURE"),
        ("target_map_version", "fixture-map-v2"),
    ],
)
def test_mandatory_material_change_changes_identity(field, value):
    old = receipt()
    changed = old.material.model_copy(update={field: value})
    assert material_context_hash_v31(old.symbol, changed) != old.material_context_hash
    with pytest.raises(ValidationError, match="MATERIAL_HASH_MISMATCH"):
        ContextRouteReceiptV31.model_validate({**old.model_dump(), "material": changed})


@pytest.mark.parametrize("field", ["box_version", "cluster_id", "deployment_id", "telemetry_count"])
def test_telemetry_cannot_enter_material_contract(field):
    with pytest.raises(ValidationError, match="Extra inputs"):
        MaterialContextV31.model_validate({**receipt().material.model_dump(), field: 1})


def test_receipt_refresh_changes_receipt_hash_without_reminting_material():
    old = receipt()
    changed = ContextRouteReceiptV31.model_validate({**old.model_dump(), "evaluated_at": NOW + timedelta(seconds=1)})
    assert changed.material_context_hash == old.material_context_hash
    assert context_route_receipt_hash_v31(old) != context_route_receipt_hash_v31(changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_directions", ("SELL",)),
        ("blocked_routes", ("FIXTURE_CONTINUATION",)),
        ("d1_source_ids", ()),
        ("h4_source_ids", ("sha256:" + "1" * 64,)),
    ],
)
def test_incoherent_domain_route_or_sources_rejected(field, value):
    with pytest.raises(ValidationError):
        MaterialContextV31.model_validate({**receipt().material.model_dump(), field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_closed_through", NOW + timedelta(seconds=1)),
        ("valid_until", NOW),
        ("evaluated_at", NOW.replace(tzinfo=None)),
    ],
)
def test_context_clock_failures_rejected(field, value):
    with pytest.raises(ValidationError):
        ContextRouteReceiptV31.model_validate({**receipt().model_dump(), field: value})
