"""Authority decision 2026-09-19: native V31 UUIDv5 identity and canonical admission receipt hash."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

import pytest

from contracts.strategy_5scr_admission_identity_v31 import (
    IDENTITY_ENCODING_VERSION,
    WOLF15_V31_ADMISSION_NAMESPACE,
    WOLF15_V31_LIFECYCLE_NAMESPACE,
    AdmissionReceiptV31,
    admission_id_v31,
    admission_receipt_hash_v31,
    build_admission_receipt_v31,
    lifecycle_id_v31,
    verify_handoff_admission_receipt_v31,
)
from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31
from contracts.strategy_5scr_per_symbol_admission import PER_SYMBOL_ADMISSION_RULE_VERSION
from tests.test_strategy_5scr_per_symbol_admission import POLICY, _evaluate, _raw, _safety

ROOT = Path(__file__).resolve().parents[1]
RULE = PER_SYMBOL_ADMISSION_RULE_VERSION


def _granted():
    result = _evaluate([_raw(0), _raw(300)])
    (lineage,) = result.lineages["EURUSD"]
    assert lineage.decision == "GRANTED"
    return lineage


def test_identity_contract_is_pinned():
    assert IDENTITY_ENCODING_VERSION == "v31.native-identity.v1"
    assert UUID("221b74fd-95a4-4133-9db1-482fda36c331") == WOLF15_V31_ADMISSION_NAMESPACE
    assert UUID("7f5e5517-372c-43ef-b243-00e1e665fe84") == WOLF15_V31_LIFECYCLE_NAMESPACE
    assert WOLF15_V31_ADMISSION_NAMESPACE != WOLF15_V31_LIFECYCLE_NAMESPACE
    selected = CandidateHandoffV31.model_fields["selected_ssot_hash"].annotation
    assert AdmissionReceiptV31.model_fields["selected_ssot_hash"].annotation == selected


def test_same_canonical_input_gives_same_uuid_and_replay_is_stable():
    first = admission_id_v31(pair_admission_rule_version=RULE, canonical_symbol="EURUSD", opening_source_event_id="e1")
    again = admission_id_v31(pair_admission_rule_version=RULE, canonical_symbol="EURUSD", opening_source_event_id="e1")
    assert first == again and first.version == 5
    lineage = _granted()
    replayed = _granted()
    assert build_admission_receipt_v31(lineage, policy=POLICY) == build_admission_receipt_v31(replayed, policy=POLICY)


def test_different_anchor_symbol_or_rule_gives_different_uuid():
    base = {"pair_admission_rule_version": RULE, "canonical_symbol": "EURUSD", "opening_source_event_id": "e1"}
    ids = {
        admission_id_v31(**base),
        admission_id_v31(**{**base, "opening_source_event_id": "e2"}),
        admission_id_v31(**{**base, "canonical_symbol": "GBPUSD"}),
        admission_id_v31(**{**base, "pair_admission_rule_version": "5scr.pair-admission.raw-ledger.v2"}),
    }
    assert len(ids) == 4
    admission = admission_id_v31(**base)
    lifecycles = {
        lifecycle_id_v31(strategy_analysis_admission_id=admission, lifecycle_anchor="a1"),
        lifecycle_id_v31(strategy_analysis_admission_id=admission, lifecycle_anchor="a2"),
        lifecycle_id_v31(
            strategy_analysis_admission_id=admission_id_v31(**{**base, "opening_source_event_id": "e2"}),
            lifecycle_anchor="a1",
        ),
    }
    assert len(lifecycles) == 3 and all(item.version == 5 for item in lifecycles)


def test_field_boundaries_cannot_collide():
    a = admission_id_v31(pair_admission_rule_version=RULE, canonical_symbol="EURUSD", opening_source_event_id="Xe1")
    b = admission_id_v31(pair_admission_rule_version=RULE, canonical_symbol="EURUSDX", opening_source_event_id="e1")
    assert a != b


def test_identity_never_depends_on_legacy_hex32_identity():
    source = (ROOT / "contracts" / "strategy_5scr_admission_identity_v31.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("#", '"""')))
    assert not re.search(r"5scr-(analysis-admission|lifecycle|admission):", code)
    assert "hex32" not in code.replace("<hex32>", "")


def test_direction_flip_successor_has_distinct_identity_and_exact_supersession():
    result = _evaluate([_raw(0), _raw(100), _raw(200, direction="SELL"), _raw(350, direction="SELL")])
    old, new = result.lineages["EURUSD"]
    old_receipt = build_admission_receipt_v31(old, policy=POLICY)
    new_receipt = build_admission_receipt_v31(new, policy=POLICY)
    assert old.superseded_by == new.lineage_id
    assert old_receipt.strategy_analysis_admission_id != new_receipt.strategy_analysis_admission_id
    old_lifecycle = lifecycle_id_v31(
        strategy_analysis_admission_id=old_receipt.strategy_analysis_admission_id, lifecycle_anchor=old.lineage_id
    )
    new_lifecycle = lifecycle_id_v31(
        strategy_analysis_admission_id=new_receipt.strategy_analysis_admission_id, lifecycle_anchor=new.lineage_id
    )
    assert old_lifecycle != new_lifecycle


def test_other_symbols_never_change_this_symbols_identity():
    alone = _granted()
    crowded = _evaluate([_raw(0), _raw(1, "GBPUSD", "SELL"), _raw(300), _raw(2, "NZDUSD")]).lineages["EURUSD"][0]
    assert build_admission_receipt_v31(alone, policy=POLICY) == build_admission_receipt_v31(crowded, policy=POLICY)


def test_receipt_hash_is_deterministic_and_key_order_independent():
    receipt = build_admission_receipt_v31(_granted(), policy=POLICY)
    digest = admission_receipt_hash_v31(receipt)
    assert digest == admission_receipt_hash_v31(AdmissionReceiptV31.model_validate(receipt.model_dump()))
    shuffled = dict(reversed(list(json.loads(receipt.model_dump_json()).items())))
    assert admission_receipt_hash_v31(AdmissionReceiptV31.model_validate(shuffled)) == digest
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)


def test_canonical_field_change_changes_hash():
    receipt = build_admission_receipt_v31(_granted(), policy=POLICY)
    digest = admission_receipt_hash_v31(receipt)
    changed = receipt.model_copy(update={"reason_code": "PER_SYMBOL_THRESHOLD_REACHED_X"})
    assert admission_receipt_hash_v31(changed) != digest
    other_policy = POLICY.model_copy(update={"min_duration_seconds": 301})
    assert admission_receipt_hash_v31(build_admission_receipt_v31(_granted(), policy=other_policy)) != digest


@pytest.mark.parametrize("override", [{"kill_switch_active": True}, {"market_data_authority_ok": False}])
def test_global_safety_veto_never_changes_the_admission_receipt_hash(override):
    events = [_raw(0), _raw(300)]
    healthy = _evaluate(events).lineages["EURUSD"][0]
    vetoed_eval = _evaluate(events, safety=_safety(**override))
    vetoed = vetoed_eval.lineages["EURUSD"][0]
    assert vetoed_eval.progression_allowed is False
    assert admission_receipt_hash_v31(build_admission_receipt_v31(vetoed, policy=POLICY)) == admission_receipt_hash_v31(
        build_admission_receipt_v31(healthy, policy=POLICY)
    )


def test_receipt_excludes_runtime_broker_database_and_overlay_fields():
    fields = set(AdmissionReceiptV31.model_fields)
    forbidden = {
        "global_vetoes",
        "effective_state",
        "progression_allowed",
        "spread",
        "algo_trading",
        "deployment_id",
        "inserted_at",
        "row_version",
        "id",
        "latest_snapshot_id",
        "secret",
        "source_legacy_identity",
    }
    assert not fields & forbidden
    with pytest.raises(ValueError):
        AdmissionReceiptV31.model_validate(
            {**build_admission_receipt_v31(_granted(), policy=POLICY).model_dump(), "deployment_id": "d"}
        )


def test_forged_admission_id_is_rejected():
    receipt = build_admission_receipt_v31(_granted(), policy=POLICY)
    forged = {**receipt.model_dump(), "strategy_analysis_admission_id": UUID(int=1)}
    with pytest.raises(ValueError, match="ADMISSION_ID_NOT_DERIVED_FROM_OPENING_EVENT"):
        AdmissionReceiptV31.model_validate(forged)


def test_handoff_may_reference_only_a_matching_granted_receipt():
    granted = build_admission_receipt_v31(_granted(), policy=POLICY)
    digest = admission_receipt_hash_v31(granted)
    verify_handoff_admission_receipt_v31(
        granted,
        admission_receipt_hash=digest,
        strategy_analysis_admission_id=granted.strategy_analysis_admission_id,
        canonical_symbol="EURUSD",
    )
    pending = _evaluate([_raw(0), _raw(100, "GBPUSD", "SELL")]).lineages["GBPUSD"][0]
    assert (pending.decision, pending.reason_code) == (None, "PENDING_THRESHOLD")
    stale = _evaluate([_raw(0, "CHFJPY")]).lineages["CHFJPY"][0]
    for lineage in (pending, stale):
        receipt = build_admission_receipt_v31(lineage, policy=POLICY)
        with pytest.raises(ValueError, match="HANDOFF_REQUIRES_GRANTED_ADMISSION_RECEIPT"):
            verify_handoff_admission_receipt_v31(
                receipt,
                admission_receipt_hash=admission_receipt_hash_v31(receipt),
                strategy_analysis_admission_id=receipt.strategy_analysis_admission_id,
                canonical_symbol=receipt.canonical_symbol,
            )
    with pytest.raises(ValueError, match="HANDOFF_ADMISSION_RECEIPT_HASH_MISMATCH"):
        verify_handoff_admission_receipt_v31(
            granted,
            admission_receipt_hash="sha256:" + "0" * 64,
            strategy_analysis_admission_id=granted.strategy_analysis_admission_id,
            canonical_symbol="EURUSD",
        )
    with pytest.raises(ValueError, match="HANDOFF_ADMISSION_SCOPE_MISMATCH"):
        verify_handoff_admission_receipt_v31(
            granted,
            admission_receipt_hash=digest,
            strategy_analysis_admission_id=granted.strategy_analysis_admission_id,
            canonical_symbol="GBPUSD",
        )
