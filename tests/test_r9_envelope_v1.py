"""R9EnvelopeV1: derived exact-S acceptance, fail-closed schema, doc/contract equality, reused names."""

from __future__ import annotations

import ast
import copy
import hashlib
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from contracts.direct_broker_reconciliation import DirectBrokerReconciliationReceipt
from contracts.mt5_execution_protocol import AccountSnapshotV1, SymbolCapability
from contracts.r9_envelope_v1 import (
    R9_FAILURE_REASONS_V1,
    R9EnvelopeV1,
    R9FailureReason,
    r9_envelope_failures_v1,
    r9_envelope_field_paths_v1,
    verify_r9_envelope_v1,
)
from execution.broker_reconciliation_evidence import ReconciliationAttestation
from ops.mt5_mcp.reconcile import MEASURED_STATES

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "governance" / "r9-envelope-v1.md"
ARTIFACT = b'{"run_id":"C2_RECONCILIATION_R9","status":"PASS_CLOSED"}\n'
S_ID = "snap-f1dd1f76"
S_SHA = "a" * 64
OTHER_SHA = "b" * 64
EVIDENCE_ID = "4a46f1fd-54e3-4241-9c03-8e0fa385a02d"
PAYLOAD_SHA = "e" * 64
RECEIPT_ID = "11111111-2222-4333-8444-555555555555"
RECEIPT_SHA = "sha256:" + "c" * 64
COMPONENT_IDENTITY_PATHS = {
    "collect": ("collect", "attested_snapshot_identity", "COLLECT_SNAPSHOT_IDENTITY_MISMATCH"),
    "import": ("import", "imported_snapshot_identity", "IMPORT_SNAPSHOT_IDENTITY_MISMATCH"),
    "active_readback": (
        "active_readback",
        "readback_snapshot_identity",
        "ACTIVE_READBACK_SNAPSHOT_IDENTITY_MISMATCH",
    ),
}
# Q1 (owner, 2026-09-28): these two views prove snapshot_id only.
COMPONENT_ID_ONLY_PATHS = {
    "capability": ("capability", "CAPABILITY_SNAPSHOT_ID_MISMATCH"),
    "direct_receipt": ("direct_receipt", "DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH"),
}


def _s() -> dict[str, str]:
    return {"snapshot_id": S_ID, "snapshot_sha256": S_SHA}


def _envelope(**receipt: Any) -> dict[str, Any]:
    return {
        "schema_id": "wolf15.r9-envelope",
        "schema_version": "v1",
        "source_artifact": "R9",
        "artifact_sha256": hashlib.sha256(ARTIFACT).hexdigest(),
        "snapshot_s": _s(),
        "collect": {
            "status": "MATCHED_FLAT_DEMO",
            "attested_snapshot_identity": _s(),
            "evidence_id": EVIDENCE_ID,
            "report_sha256": "d" * 64,
        },
        "import": {
            "status": "STORED",
            "imported_snapshot_identity": _s(),
            "evidence_id": EVIDENCE_ID,
            "payload_sha256": PAYLOAD_SHA,
        },
        "active_readback": {
            "status": "ACTIVE",
            "readback_snapshot_identity": _s(),
            "evidence_id": EVIDENCE_ID,
            "payload_sha256": PAYLOAD_SHA,
        },
        "capability": {
            "status": "MEASURED",
            "snapshot_id": S_ID,
            "canonical_symbol": "EURUSD",
            "broker_symbol": "EURUSD",
            "volume_min": 0.01,
            "volume_step": 0.01,
        },
        "direct_receipt": {
            "status": "ABSENT",
            "snapshot_id": S_ID,
            "reconciliation_id": None,
            "receipt_sha256": None,
            "broker_ledger_reconciled": None,
            **receipt,
        },
        "created_at": "2026-09-27T00:00:00Z",
    }


def _present() -> dict[str, Any]:
    return _envelope(
        status="PRESENT", reconciliation_id=RECEIPT_ID, receipt_sha256=RECEIPT_SHA, broker_ledger_reconciled=True
    )


def _reasons(raw: dict[str, Any], artifact: bytes | None = ARTIFACT) -> tuple[str, ...]:
    return verify_r9_envelope_v1(raw, artifact).failure_reasons


def _block(name: str) -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(rf"<!-- {name}:begin -->\n```text\n(.*?)\n```\n<!-- {name}:end -->", text, re.S)
    assert match, name
    return match.group(1).split("\n")


# --- positive -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("builder", [_envelope, _present], ids=["receipt_absent", "receipt_present_bound"])
def test_exact_s_accepted(builder):
    raw = builder()
    verdict = verify_r9_envelope_v1(raw, ARTIFACT)
    assert verdict.exact_s_accepted is True
    assert verdict.failure_reasons == ()
    assert verdict.artifact_bytes_verified is True
    model = R9EnvelopeV1.model_validate(raw)
    assert model.intrinsic_checks_passed is True
    assert not hasattr(model, "exact_s_accepted")  # Q4: the verdict is the only final authority
    assert verify_r9_envelope_v1(model, ARTIFACT) == verdict


def test_artifact_bytes_are_required():
    verdict = verify_r9_envelope_v1(_envelope(), None)
    assert (verdict.exact_s_accepted, verdict.failure_reasons, verdict.artifact_bytes_verified) == (
        False,
        ("ARTIFACT_BYTES_REQUIRED",),
        False,
    )
    assert R9EnvelopeV1.model_validate(_envelope()).intrinsic_checks_passed is True


def test_the_verdict_model_refuses_acceptance_without_bytes_or_with_a_failure():
    from contracts.r9_envelope_v1 import R9EnvelopeVerdictV1

    with pytest.raises(ValidationError, match="EXACT_S_ACCEPTED_WITHOUT_ARTIFACT_BYTES"):
        R9EnvelopeVerdictV1(exact_s_accepted=True, failure_reasons=(), artifact_bytes_verified=False)
    with pytest.raises(ValidationError, match="VERDICT_ACCEPTANCE_INCONSISTENT"):
        R9EnvelopeVerdictV1(
            exact_s_accepted=True, failure_reasons=("SOURCE_ARTIFACT_NOT_R9",), artifact_bytes_verified=True
        )
    with pytest.raises(ValidationError, match="VERDICT_ACCEPTANCE_INCONSISTENT"):
        R9EnvelopeVerdictV1(exact_s_accepted=False, failure_reasons=(), artifact_bytes_verified=True)


# --- identity mismatches (each individually, each half of the pair) ---------------------------------------


@pytest.mark.parametrize("component", sorted(COMPONENT_IDENTITY_PATHS))
@pytest.mark.parametrize("part", ["snapshot_id", "snapshot_sha256"])
def test_each_identity_mismatch_alone_rejects(component, part):
    for builder in (_envelope, _present):
        raw = builder()
        section, key, reason = COMPONENT_IDENTITY_PATHS[component]
        raw[section][key][part] = "snap-S1" if part == "snapshot_id" else OTHER_SHA
        verdict = verify_r9_envelope_v1(raw, ARTIFACT)
        assert verdict.exact_s_accepted is False
        assert verdict.failure_reasons == (reason,)


@pytest.mark.parametrize("component", sorted(COMPONENT_ID_ONLY_PATHS))
def test_each_id_only_component_mismatch_alone_rejects(component):
    for builder in (_envelope, _present):
        raw = builder()
        section, reason = COMPONENT_ID_ONLY_PATHS[component]
        raw[section]["snapshot_id"] = "snap-S1"
        assert _reasons(raw) == (reason,)


@pytest.mark.parametrize("component", sorted(COMPONENT_ID_ONLY_PATHS))
def test_id_only_components_carry_no_snapshot_sha256(component):
    """Q1: S's sha256 is never copied into these views as if it were extra evidence."""

    raw = _envelope()
    raw[component]["snapshot_sha256"] = S_SHA
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


def test_snapshot_s_id_differing_from_every_component_rejects_all():
    raw = _envelope()
    raw["snapshot_s"]["snapshot_id"] = "snap-S1"
    expected = {reason for _, _, reason in COMPONENT_IDENTITY_PATHS.values()}
    expected |= {reason for _, reason in COMPONENT_ID_ONLY_PATHS.values()}
    assert _reasons(raw) == tuple(r for r in R9_FAILURE_REASONS_V1 if r in expected)


def test_snapshot_s_sha_differing_rejects_only_the_full_pair_components():
    raw = _envelope()
    raw["snapshot_s"]["snapshot_sha256"] = OTHER_SHA
    expected = {reason for _, _, reason in COMPONENT_IDENTITY_PATHS.values()}
    assert _reasons(raw) == tuple(r for r in R9_FAILURE_REASONS_V1 if r in expected)


def test_latest_snapshot_never_substitutes_for_s():
    raw = _envelope()
    newer = {"snapshot_id": "snap-S2", "snapshot_sha256": OTHER_SHA}
    for section, key, _ in COMPONENT_IDENTITY_PATHS.values():
        raw[section][key] = dict(newer)
    for section in COMPONENT_ID_ONLY_PATHS:
        raw[section]["snapshot_id"] = "snap-S2"
    reasons = _reasons(raw)
    assert len(reasons) == 5 and all("SNAPSHOT_ID" in reason for reason in reasons)


@pytest.mark.parametrize(
    ("section", "field", "value", "reason"),
    [
        ("import", "evidence_id", RECEIPT_ID, ("IMPORT_EVIDENCE_ID_MISMATCH", "ACTIVE_READBACK_EVIDENCE_ID_MISMATCH")),
        ("active_readback", "evidence_id", RECEIPT_ID, ("ACTIVE_READBACK_EVIDENCE_ID_MISMATCH",)),
        ("active_readback", "payload_sha256", OTHER_SHA, ("ACTIVE_READBACK_PAYLOAD_SHA256_MISMATCH",)),
    ],
)
def test_evidence_chain_mismatch_rejects(section, field, value, reason):
    raw = _envelope()
    raw[section][field] = value
    assert _reasons(raw) == reason


def test_collect_evidence_id_change_breaks_import_link():
    raw = _envelope()
    raw["collect"]["evidence_id"] = RECEIPT_ID
    assert _reasons(raw) == ("IMPORT_EVIDENCE_ID_MISMATCH",)


def test_import_payload_change_breaks_readback_link():
    raw = _envelope()
    raw["import"]["payload_sha256"] = OTHER_SHA
    assert _reasons(raw) == ("ACTIVE_READBACK_PAYLOAD_SHA256_MISMATCH",)


# --- statuses ------------------------------------------------------------------------------------------------


def test_readback_revoked_rejects():
    raw = _envelope()
    raw["active_readback"]["status"] = "REVOKED"
    assert _reasons(raw) == ("ACTIVE_READBACK_STATUS_NOT_ACTIVE",)


@pytest.mark.parametrize("status", ["MEASURED_EMPTY", "NOT_MEASURED"])
def test_capability_not_measured_rejects(status):
    raw = _envelope()
    raw["capability"]["status"] = status
    assert _reasons(raw) == ("CAPABILITY_STATUS_NOT_MEASURED",)


@pytest.mark.parametrize("field", ["canonical_symbol", "broker_symbol", "volume_min", "volume_step"])
def test_capability_evidence_missing_rejects(field):
    raw = _envelope()
    raw["capability"][field] = None
    assert _reasons(raw) == ("CAPABILITY_EVIDENCE_MISSING",)


@pytest.mark.parametrize(
    ("field", "value"), [("volume_min", 0), ("volume_step", 0), ("volume_min", -0.01), ("canonical_symbol", "EU")]
)
def test_capability_evidence_reuses_symbol_capability_bounds(field, value):
    raw = _envelope()
    raw["capability"][field] = value
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("collect", "NOT_MATCHED"),
        ("collect", "matched_flat_demo"),
        ("import", "ACTIVE"),
        ("import", "FAILED"),
        ("active_readback", "STORED"),
        ("active_readback", "active"),
        ("capability", "MEASURABLE"),
        ("capability", "NOT_MEASURABLE_READ_ONLY"),
        ("direct_receipt", "UNKNOWN"),
        ("direct_receipt", "NOT_MEASURED"),
    ],
)
def test_status_outside_reused_vocabulary_is_schema_invalid(section, value):
    raw = _envelope()
    raw[section]["status"] = value
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


# --- source artifact and artifact hash ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["R8", "r9", "R9 ", "C2_RECONCILIATION_R9"])
def test_source_artifact_must_be_r9(value):
    raw = _envelope()
    raw["source_artifact"] = value
    assert _reasons(raw) == ("SOURCE_ARTIFACT_NOT_R9",)


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "a" * 65, "sha256:" + "a" * 64, "", "g" * 64])
def test_bad_artifact_sha256_format_is_schema_invalid(value):
    raw = _envelope()
    raw["artifact_sha256"] = value
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


@pytest.mark.parametrize("artifact", [ARTIFACT + b" ", b"", ARTIFACT.upper()])
def test_artifact_bytes_mismatch_rejects(artifact):
    verdict = verify_r9_envelope_v1(_envelope(), artifact)
    assert verdict.failure_reasons == ("ARTIFACT_SHA256_MISMATCH",)
    assert verdict.exact_s_accepted is False and verdict.artifact_bytes_verified is False


def test_artifact_bytes_must_be_bytes():
    verdict = verify_r9_envelope_v1(_envelope(), ARTIFACT.decode())  # type: ignore[arg-type]
    assert verdict.failure_reasons == ("ARTIFACT_SHA256_MISMATCH",)


def test_envelope_hash_is_not_the_artifact_hash():
    """No circular hashing: hashing the envelope itself never satisfies artifact_sha256."""
    raw = _envelope()
    envelope_bytes = R9EnvelopeV1.model_validate(raw).model_dump_json(by_alias=True).encode()
    assert verify_r9_envelope_v1(raw, envelope_bytes).failure_reasons == ("ARTIFACT_SHA256_MISMATCH",)


# --- direct receipt -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [{"reconciliation_id": None}, {"receipt_sha256": None}, {"reconciliation_id": None, "receipt_sha256": None}],
)
def test_present_without_receipt_identity_rejects(missing):
    raw = _present()
    raw["direct_receipt"].update(missing)
    assert _reasons(raw) == ("DIRECT_RECEIPT_PRESENT_WITHOUT_RECEIPT_IDENTITY",)


@pytest.mark.parametrize(
    "extra",
    [
        {"reconciliation_id": RECEIPT_ID},
        {"receipt_sha256": RECEIPT_SHA},
        {"reconciliation_id": RECEIPT_ID, "receipt_sha256": RECEIPT_SHA},
    ],
)
def test_absent_with_receipt_identity_rejects(extra):
    raw = _envelope(**extra)
    assert _reasons(raw) == ("DIRECT_RECEIPT_ABSENT_WITH_RECEIPT_IDENTITY",)


@pytest.mark.parametrize("value", [True, False])
def test_absent_carries_no_reconciliation_verdict(value):
    assert _reasons(_envelope(broker_ledger_reconciled=value)) == ("DIRECT_RECEIPT_ABSENT_WITH_RECEIPT_IDENTITY",)


@pytest.mark.parametrize("value", [False, None])
def test_present_must_be_a_reconciled_receipt(value):
    raw = _present()
    raw["direct_receipt"]["broker_ledger_reconciled"] = value
    verdict = verify_r9_envelope_v1(raw, ARTIFACT)
    assert (verdict.exact_s_accepted, verdict.failure_reasons) == (False, ("DIRECT_RECEIPT_NOT_RECONCILED",))


def test_absent_still_names_exact_s():
    raw = _envelope()
    raw["direct_receipt"]["snapshot_id"] = "snap-S2"
    assert _reasons(raw) == ("DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH",)


def test_stored_is_documented_as_external_qualified_and_never_main_canonical():
    text = DOC.read_text(encoding="utf-8")
    assert (
        "QUALIFIED_C2_WRAPPER_STATUS, normalized as the R9 import status; NOT a main-repository canonical status"
        in text
    )
    assert "persistence is proven by the main-side ACTIVE readback" in text


@pytest.mark.parametrize("value", ["c" * 64, "sha256:" + "C" * 64, "sha256:" + "c" * 63])
def test_receipt_sha256_must_use_existing_prefixed_format(value):
    raw = _present()
    raw["direct_receipt"]["receipt_sha256"] = value
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


# --- derived field and strict schema ---------------------------------------------------------------------------


@pytest.mark.parametrize("supplied", [True, False, None, "true"])
def test_supplied_exact_s_accepted_is_rejected_even_when_correct(supplied):
    raw = _envelope()
    raw["exact_s_accepted"] = supplied
    verdict = verify_r9_envelope_v1(raw, ARTIFACT)
    assert verdict.exact_s_accepted is False
    assert verdict.failure_reasons == ("EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT",)
    with pytest.raises(ValidationError):
        R9EnvelopeV1.model_validate(raw)


def test_exact_s_accepted_is_never_serialized():
    dumped = R9EnvelopeV1.model_validate(_envelope()).model_dump(mode="json", by_alias=True)
    assert "exact_s_accepted" not in dumped
    assert verify_r9_envelope_v1(dumped, ARTIFACT).exact_s_accepted is True


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("collect",),
        ("import",),
        ("active_readback",),
        ("capability",),
        ("direct_receipt",),
        ("snapshot_s",),
    ],
)
def test_extra_field_rejected(path):
    raw = _envelope()
    target = raw
    for key in path:
        target = target[key]
    target["latest_snapshot_id"] = "snap-S2"
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)
    with pytest.raises(ValidationError):
        R9EnvelopeV1.model_validate(raw)


def test_python_attribute_name_import_underscore_is_not_a_wire_key():
    raw = _envelope()
    raw["import_"] = raw.pop("import")
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


def _leaf_paths(raw: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, value in raw.items():
        if isinstance(value, dict):
            paths.extend(_leaf_paths(value, prefix + key + "."))
        else:
            paths.append(prefix + key)
    return paths


@pytest.mark.parametrize(
    "path",
    _leaf_paths(_envelope()) + ["collect", "import", "active_readback", "capability", "direct_receipt", "snapshot_s"],
)
def test_missing_field_or_component_fails_closed(path):
    raw = _envelope()
    *parents, leaf = path.split(".")
    target = raw
    for key in parents:
        target = target[key]
    del target[leaf]
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


@pytest.mark.parametrize("value", ["2026-09-27T00:00:00", "2026-09-27T08:00:00+08:00"])
def test_created_at_must_be_utc(value):
    raw = _envelope()
    raw["created_at"] = value
    assert _reasons(raw) == ("ENVELOPE_SCHEMA_INVALID",)


@pytest.mark.parametrize("envelope", [None, [], "{}", b"{}"])
def test_non_mapping_input_is_schema_invalid(envelope):
    assert verify_r9_envelope_v1(envelope, ARTIFACT).failure_reasons == ("ENVELOPE_SCHEMA_INVALID",)


def test_models_are_frozen():
    model = R9EnvelopeV1.model_validate(_envelope())
    with pytest.raises(ValidationError):
        model.source_artifact = "R8"


def test_failure_reasons_are_deterministic_and_canonically_ordered():
    raw = _present()
    raw["source_artifact"] = "R8"
    raw["direct_receipt"]["receipt_sha256"] = None
    raw["direct_receipt"]["snapshot_id"] = "snap-S1"
    raw["direct_receipt"]["broker_ledger_reconciled"] = False
    raw["capability"]["status"] = "NOT_MEASURED"
    raw["capability"]["volume_min"] = None
    raw["active_readback"]["status"] = "REVOKED"
    raw["import"]["imported_snapshot_identity"]["snapshot_sha256"] = OTHER_SHA
    expected = (
        "SOURCE_ARTIFACT_NOT_R9",
        "ARTIFACT_SHA256_MISMATCH",
        "IMPORT_SNAPSHOT_IDENTITY_MISMATCH",
        "ACTIVE_READBACK_STATUS_NOT_ACTIVE",
        "CAPABILITY_STATUS_NOT_MEASURED",
        "CAPABILITY_EVIDENCE_MISSING",
        "DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH",
        "DIRECT_RECEIPT_PRESENT_WITHOUT_RECEIPT_IDENTITY",
        "DIRECT_RECEIPT_NOT_RECONCILED",
    )
    for _ in range(3):
        assert _reasons(copy.deepcopy(raw), b"other") == expected
    model = R9EnvelopeV1.model_validate(raw)
    assert r9_envelope_failures_v1(model) == tuple(r for r in expected if r != "ARTIFACT_SHA256_MISMATCH")
    assert model.intrinsic_checks_passed is False
    assert _reasons(copy.deepcopy(raw), None)[:2] == ("SOURCE_ARTIFACT_NOT_R9", "ARTIFACT_BYTES_REQUIRED")


def test_every_intrinsic_reason_is_reachable_and_in_vocabulary():
    assert tuple(get_args(R9FailureReason)) == R9_FAILURE_REASONS_V1
    assert len(set(R9_FAILURE_REASONS_V1)) == len(R9_FAILURE_REASONS_V1)


# --- doc / contract consistency -------------------------------------------------------------------------------


def test_doc_field_list_equals_contract():
    assert _block("r9-envelope-fields") == list(r9_envelope_field_paths_v1())
    assert set(_leaf_paths(_envelope())) | {"exact_s_accepted"} == set(r9_envelope_field_paths_v1())


def test_doc_failure_vocabulary_equals_contract():
    assert _block("r9-envelope-failure-reasons") == list(R9_FAILURE_REASONS_V1)


FROZEN_SCHEMA_SHA256 = "10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2"
FROZEN_NORMATIVE_SPAN_SHA256 = "c9663fa7a752baa8f8723ef0241980d7fc9a55938ff480dc5703564e4e31b96f"


def test_doc_declares_frozen_and_inactive():
    text = DOC.read_text(encoding="utf-8")
    assert "- status: FROZEN\n" in text
    assert "- runtime_activation: false " in text
    assert "- envelope_status: FROZEN " in text
    assert "NOT_FROZEN" not in text


def test_frozen_sections_are_byte_identical_to_the_owner_frozen_bytes():
    """The freeze successor changes metadata only; sections 1-7 are pinned by the span of the frozen bytes."""

    raw = DOC.read_bytes()
    span = raw[raw.index(b"## 1. Purpose") : raw.index(b"\n## 8. Freeze record")]
    assert hashlib.sha256(span).hexdigest() == FROZEN_NORMATIVE_SPAN_SHA256
    text = raw.decode("utf-8")
    for line in (
        "frozen_schema_head             = 08c2de61d2ffe2da41ae4d04da8255319310c424",
        "frozen_schema_blob             = 9a895e34cd1547047e76d2646b3633cdac04cd13",
        f"frozen_schema_sha256           = {FROZEN_SCHEMA_SHA256}",
        "frozen_schema_bytes            = 13162",
        f"frozen_normative_span_sha256   = {FROZEN_NORMATIVE_SPAN_SHA256}",
        "envelope_status                = FROZEN",
        "exact_s_final_authority        = verify_r9_envelope_v1 verdict ONLY",
        "artifact_bytes                 = REQUIRED",
        "latest_snapshot_fallback       = PROHIBITED",
    ):
        assert line + "\n" in text, line
    assert "A frozen schema is not an R9 PASS" in text


def test_doc_is_stored_byte_exact():
    attributes = (ROOT / "docs" / "governance" / ".gitattributes").read_bytes().splitlines()
    assert b"r9-envelope-v1.md -text -diff" in attributes


def test_doc_citations_point_at_existing_lines():
    text = DOC.read_text(encoding="utf-8")
    cited = re.findall(r"`((?:contracts|execution|ops|storage)/[\w./]+\.py):(\d+)(?:-(\d+))?`", text)
    assert len(cited) >= 20
    for path, start, end in cited:
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        assert 1 <= int(start) <= int(end or start) <= len(lines), (path, start, end)


# --- reused existing names ------------------------------------------------------------------------------------


def _schema(model: Any, field: str) -> dict[str, Any]:
    prop = model.model_json_schema()["properties"][field]
    non_null = [branch for branch in prop.get("anyOf", [prop]) if branch.get("type") != "null"]
    assert len(non_null) == 1
    return {k: v for k, v in non_null[0].items() if k not in {"title", "description", "default"}}


def test_snapshot_identity_reuses_existing_names_and_constraints():
    from contracts.r9_envelope_v1 import R9SnapshotIdentityV1

    assert set(R9SnapshotIdentityV1.model_fields) == {"snapshot_id", "snapshot_sha256"}
    assert set(R9SnapshotIdentityV1.model_fields) <= set(ReconciliationAttestation.model_fields)
    assert _schema(R9SnapshotIdentityV1, "snapshot_id") == _schema(AccountSnapshotV1, "snapshot_id")
    assert _schema(R9SnapshotIdentityV1, "snapshot_sha256") == _schema(ReconciliationAttestation, "snapshot_sha256")


def test_collect_import_readback_reuse_attestation_and_evidence_row_names():
    from contracts.r9_envelope_v1 import R9ActiveReadbackV1, R9CollectV1, R9ImportV1

    assert _schema(R9CollectV1, "status") == _schema(ReconciliationAttestation, "status")
    for field in ("evidence_id", "report_sha256"):
        assert _schema(R9CollectV1, field) == _schema(ReconciliationAttestation, field)
    for model in (R9ImportV1, R9ActiveReadbackV1):
        assert _schema(model, "evidence_id") == _schema(ReconciliationAttestation, "evidence_id")
        assert _schema(model, "payload_sha256") == _schema(ReconciliationAttestation, "snapshot_sha256")
    migration = (ROOT / "storage/migrations/versions/20260910_02_reconciliation_evidence.py").read_text("utf-8")
    assert "payload_sha256 varchar(64) NOT NULL" in migration
    assert "CHECK (status IN ('ACTIVE', 'REVOKED'))" in migration
    assert set(_schema(R9ActiveReadbackV1, "status")["enum"]) == {"ACTIVE", "REVOKED"}


def test_capability_reuses_symbol_capability_names_and_measurement_states():
    from contracts.r9_envelope_v1 import R9CapabilityV1

    for field in ("canonical_symbol", "broker_symbol", "volume_min", "volume_step"):
        assert _schema(R9CapabilityV1, field) == _schema(SymbolCapability, field)
    assert set(_schema(R9CapabilityV1, "status")["enum"]) == set(MEASURED_STATES) | {"NOT_MEASURED"}
    view = (ROOT / "storage/migrations/versions/20260919_01_d0_canary_predicate_audit_views.py").read_text("utf-8")
    for column in ("snapshot_id", "canonical_symbol", "broker_symbol", "volume_min", "volume_step"):
        assert re.search(rf"\b{column}\b", view.split("RECONCILIATION_RECEIPT_SQL")[0]), column


def test_direct_receipt_reuses_direct_broker_receipt_names():
    from contracts.r9_envelope_v1 import R9DirectReceiptV1

    assert _schema(R9DirectReceiptV1, "reconciliation_id") == _schema(
        DirectBrokerReconciliationReceipt, "reconciliation_id"
    )
    assert _schema(R9DirectReceiptV1, "receipt_sha256") == _schema(DirectBrokerReconciliationReceipt, "receipt_sha256")
    view = (ROOT / "storage/migrations/versions/20260919_01_d0_canary_predicate_audit_views.py").read_text("utf-8")
    receipt_sql = view.split("RECONCILIATION_RECEIPT_SQL = ")[1]
    for column in ("r.reconciliation_id", "r.source_snapshot_id", "r.receipt_sha256"):
        assert column in receipt_sql


# INTEGRATION_GOVERNANCE_GUARD_CHANGE (owner D2, 2026-09-28): an import-aware (AST) guard over every production
# folder including tools/. Only these OFFLINE evidence verifiers may import the contract; any other importer is a
# runtime activation and fails. A mention in a docstring or string is not an import and is not allowlisted.
R9_CONTRACT_MODULE = "contracts.r9_envelope_v1"
R9_GUARDED_FOLDERS = ("api", "execution", "services", "storage", "ops", "core", "engine", "pipeline", "tools")
OFFLINE_R9_IMPORTERS = frozenset({"ops/demo_canary_verifier/side_ledger.py", "tools/shadow_harness/evaluator.py"})
# An offline importer may read evidence/schema files, never reach a network, DB, broker, MT5 or runtime service.
OFFLINE_FORBIDDEN_IMPORT_PREFIXES = (
    "requests",
    "httpx",
    "aiohttp",
    "socket",
    "urllib.request",
    "http.client",
    "websockets",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "redis",
    "MetaTrader5",
    "fastapi",
    "starlette",
    "uvicorn",
    "execution",
    "services",
    "api",
    "storage",
    "ea_interface",
    "ops.mt5_mcp.server",
)


def _imported_modules(source: str) -> set[str]:
    """Every module a source imports, including ``from contracts import r9_envelope_v1`` and dynamic
    ``importlib.import_module("...")`` / ``__import__("...")`` calls with a literal name."""

    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if name in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                modules.add(node.args[0].value)
    return modules


def _imports_r9_contract(source: str) -> bool:
    return R9_CONTRACT_MODULE in _imported_modules(source)


def test_the_import_scanner_catches_every_import_form_and_ignores_mentions():
    for evasion in (
        "import contracts.r9_envelope_v1\n",
        "from contracts.r9_envelope_v1 import verify_r9_envelope_v1\n",
        "from contracts import r9_envelope_v1\n",
        "import importlib\nimportlib.import_module('contracts.r9_envelope_v1')\n",
        "__import__('contracts.r9_envelope_v1')\n",
    ):
        assert _imports_r9_contract(evasion), evasion
    for mention in ('"""Uses contracts.r9_envelope_v1 verdicts."""\n', "NAME = 'contracts.r9_envelope_v1'\n"):
        assert not _imports_r9_contract(mention), mention


def test_contract_has_no_runtime_importer_and_no_execution_dependency():
    contract = (ROOT / "contracts" / "r9_envelope_v1.py").read_text("utf-8")
    assert not any(
        module == prefix or module.startswith(prefix + ".")
        for module in _imported_modules(contract)
        for prefix in ("execution", "services", "api", "storage", "ops", "tools")
    )
    importers = sorted(
        path.relative_to(ROOT).as_posix()
        for folder in R9_GUARDED_FOLDERS
        if (ROOT / folder).is_dir()
        for path in (ROOT / folder).rglob("*.py")
        if _imports_r9_contract(path.read_text("utf-8", errors="ignore"))
    )
    assert sorted(set(importers) - OFFLINE_R9_IMPORTERS) == []
    for relative in importers:
        imported = _imported_modules((ROOT / relative).read_text("utf-8"))
        offending = sorted(
            module
            for module in imported
            for prefix in OFFLINE_FORBIDDEN_IMPORT_PREFIXES
            if module == prefix or module.startswith(prefix + ".")
        )
        assert offending == [], (relative, offending)
