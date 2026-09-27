"""Owner decisions E1 (exact-S), E2 (capture bundle v1) and E4 (derived gate) for the offline shadow harness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.shadow_harness_helpers import (
    POLICY_PATH,
    broker_dry_run,
    bundle,
    candidate,
    digest,
    encode,
    evaluate,
    exact_s,
    lineage,
    load_real,
    measured_exact_s,
    natural_chain,
    risk_dry_run,
    tradeplan,
)
from tools.shadow_harness.captures import BUNDLE_HEADER_FIELDS
from tools.shadow_harness.cli import EXIT_GATE_PASSED, main
from tools.shadow_harness.evaluator import (
    GATE_FLAG_ORDER,
    R9_BINDING_MODE,
    R9_ENVELOPE_FROZEN_STATUSES,
    R9_ENVELOPE_REQUIRED_COMPONENTS,
    AcceptanceBlock,
    CandidateExactS,
    ExactSDependentAcceptance,
    ShadowHarnessReport,
    derive_gate_failures,
    derive_shadow_acceptance_blockers,
    r9_envelope_is_frozen,
)
from tools.shadow_harness.manifest import HarnessInputError, sha256_hex

R9 = digest("r9-artifact-bytes")


def _rejected(payload: dict[str, Any]) -> str:
    loaded, universe = load_real()
    with pytest.raises(HarnessInputError) as info:
        evaluate(payload, loaded, universe)
    return info.value.code


# --- E1: exact-S is never fabricated; absent / NOT_MEASURED never passes -------------------------


def test_pre_r9_not_measured_exact_s_makes_dependent_acceptance_false() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"EURUSD": natural_chain("EURUSD", universe)}), loaded, universe)
    dependent = report.dependent_acceptance
    assert dependent.exact_s_accepted is False
    assert [(row.exact_s_evaluation, row.exact_s_accepted) for row in dependent.candidates] == [("NOT_MEASURED", False)]
    assert (dependent.candidates[0].exact_s_id, dependent.candidates[0].exact_s_sha256) == (None, None)
    assert report.to_json_dict()["dependent_acceptance"]["EXACT_S_ACCEPTED"] is False
    # the five-flag gate does not assert exact-S; it can pass while exact-S stays unaccepted
    assert report.gate_passed is True


def test_absent_exact_s_is_never_accepted() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD")]}), loaded, universe)
    assert [row.exact_s_evaluation for row in report.dependent_acceptance.candidates] == ["ABSENT"]
    assert report.dependent_acceptance.exact_s_accepted is False


def test_no_candidates_means_no_exact_s_evidence_and_never_accepted() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe), loaded, universe)
    assert report.dependent_acceptance.candidates == ()
    assert report.dependent_acceptance.exact_s_accepted is False


def test_measured_exact_s_without_supplied_r9_artifact_is_not_accepted() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[1] = measured_exact_s("EURUSD", R9)
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe)
    row = report.dependent_acceptance.candidates[0]
    assert (row.exact_s_evaluation, row.exact_s_accepted) == ("R9_ARTIFACT_NOT_SUPPLIED", False)
    assert report.dependent_acceptance.exact_s_accepted is False
    other = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe, frozenset({digest("other")}))
    assert other.dependent_acceptance.exact_s_accepted is False


def test_measured_exact_s_bound_to_supplied_r9_artifact_is_accepted() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[1] = measured_exact_s("EURUSD", R9)
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe, frozenset({R9}))
    row = report.dependent_acceptance.candidates[0]
    assert (row.exact_s_evaluation, row.exact_s_accepted, row.r9_artifact_sha256) == ("R9_BOUND", True, R9)
    assert report.dependent_acceptance.exact_s_accepted is True
    assert report.dependent_acceptance.supplied_r9_artifact_sha256s == (R9,)


def test_one_unmeasured_candidate_keeps_dependent_acceptance_false() -> None:
    loaded, universe = load_real()
    eur = natural_chain("EURUSD", universe)
    eur[1] = measured_exact_s("EURUSD", R9)
    gbp = natural_chain("GBPUSD", universe)
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}), loaded, universe, frozenset({R9}))
    assert [row.exact_s_evaluation for row in report.dependent_acceptance.candidates] == ["R9_BOUND", "NOT_MEASURED"]
    assert report.dependent_acceptance.exact_s_accepted is False


def test_two_exact_s_for_one_candidate_is_ambiguous_not_accepted() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain.append(measured_exact_s("EURUSD", R9, capture_id="cap-exact-s-EURUSD-dup", evidence_sha256=digest("dup")))
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe, frozenset({R9}))
    row = report.dependent_acceptance.candidates[0]
    assert (row.exact_s_evaluation, row.exact_s_accepted, row.exact_s_id) == ("AMBIGUOUS", False, None)


@pytest.mark.parametrize(
    "record",
    [
        exact_s("EURUSD", exact_s_id="exact-s-EURUSD-1"),
        exact_s("EURUSD", exact_s_sha256=digest("fabricated")),
        exact_s("EURUSD", r9_artifact_sha256=R9),
        measured_exact_s("EURUSD", R9) | {"r9_artifact_sha256": None},
        measured_exact_s("EURUSD", R9) | {"exact_s_id": None},
        measured_exact_s("EURUSD", R9) | {"exact_s_sha256": None},
        exact_s("EURUSD", exact_s_status="PASS"),
    ],
)
def test_exact_s_status_and_evidence_must_agree(record: dict[str, Any]) -> None:
    loaded, universe = load_real()
    assert _rejected(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD"), record]})) == "BUNDLE_SCHEMA_INVALID"


def test_exact_s_status_is_required_not_defaulted() -> None:
    loaded, universe = load_real()
    record = exact_s("EURUSD")
    del record["exact_s_status"]
    assert _rejected(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD"), record]})) == "BUNDLE_SCHEMA_INVALID"


def test_exact_s_acceptance_cannot_be_constructed_true_without_r9_binding() -> None:
    with pytest.raises(ValidationError):
        CandidateExactS(
            symbol="EURUSD",
            candidate_id="cand-EURUSD-1",
            exact_s_evaluation="NOT_MEASURED",
            exact_s_id=None,
            exact_s_sha256=None,
            r9_artifact_sha256=None,
            exact_s_accepted=True,
        )
    with pytest.raises(ValidationError):
        ExactSDependentAcceptance.model_validate(
            {
                "EXACT_S_ACCEPTED": True,
                "rule": "R9_ARTIFACT_BOUND",
                "supplied_r9_artifact_sha256s": [],
                "candidates": [],
            }
        )


def test_invalid_r9_digest_is_rejected() -> None:
    loaded, universe = load_real()
    with pytest.raises(HarnessInputError) as info:
        evaluate(bundle(loaded, universe), loaded, universe, frozenset({"not-a-digest"}))
    assert info.value.code == "R9_ARTIFACT_DIGEST_INVALID"


def test_cli_binds_exact_s_to_supplied_r9_artifact_file(tmp_path: Path) -> None:
    loaded, universe = load_real()
    artifact = tmp_path / "r9.bin"
    artifact.write_bytes(b"r9 artifact bytes")
    chain = natural_chain("EURUSD", universe)
    chain[1] = measured_exact_s("EURUSD", sha256_hex(artifact.read_bytes()))
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(encode(bundle(loaded, universe, {"EURUSD": chain})))
    base = ["--policy", str(POLICY_PATH), "--bundle", str(bundle_path)]
    without = tmp_path / "without.json"
    assert main([*base, "--out", str(without)]) == EXIT_GATE_PASSED
    assert json.loads(without.read_text(encoding="utf-8"))["dependent_acceptance"]["EXACT_S_ACCEPTED"] is False
    with_r9 = tmp_path / "with.json"
    assert main([*base, "--out", str(with_r9), "--r9-artifact", str(artifact)]) == EXIT_GATE_PASSED
    written = json.loads(with_r9.read_text(encoding="utf-8"))
    assert written["dependent_acceptance"]["EXACT_S_ACCEPTED"] is True
    # exit 0 is the five-flag gate only; final SHADOW acceptance stays false while the R9 envelope is not frozen
    assert (written["shadow_acceptance_passed"], written["r9_envelope_status"]) == (False, "NOT_FROZEN")


# --- E2: shadow_capture_bundle/v1 header ------------------------------------------------------


def test_header_fields_are_exactly_the_owner_list() -> None:
    assert BUNDLE_HEADER_FIELDS == (
        "schema_version",
        "candidate_git_sha",
        "candidate_tree_digest",
        "manifest_hash",
        "SSOT_hash",
        "A1_hash",
        "A2_hash",
        "A3_hash",
        "A4_hash",
        "configuration_digest",
        "created_at",
    )


@pytest.mark.parametrize(
    "version",
    ["shadow_capture_bundle/v2", "wolf15.shadow-harness.bundle.v1", "SHADOW_CAPTURE_BUNDLE/V1", "", None, 1],
)
def test_unknown_schema_version_is_rejected(version: object) -> None:
    loaded, universe = load_real()
    assert _rejected(bundle(loaded, universe, header_overrides={"schema_version": version})) == (
        "BUNDLE_SCHEMA_VERSION_UNKNOWN"
    )


@pytest.mark.parametrize("field", BUNDLE_HEADER_FIELDS)
def test_missing_header_field_is_rejected(field: str) -> None:
    loaded, universe = load_real()
    payload = bundle(loaded, universe)
    del payload["header"][field]
    expected = "BUNDLE_SCHEMA_VERSION_UNKNOWN" if field == "schema_version" else "BUNDLE_HEADER_FIELD_MISSING"
    assert _rejected(payload) == expected


def test_missing_header_is_rejected() -> None:
    loaded, universe = load_real()
    payload = bundle(loaded, universe)
    del payload["header"]
    assert _rejected(payload) == "BUNDLE_HEADER_MISSING"


def test_a4_hash_is_nullable_until_approved_but_never_omittable() -> None:
    loaded, universe = load_real()
    assert evaluate(bundle(loaded, universe), loaded, universe).provenance.bundle_header.a4_hash is None
    approved = evaluate(bundle(loaded, universe, header_overrides={"A4_hash": digest("a4")}), loaded, universe)
    assert approved.provenance.bundle_header.a4_hash == digest("a4")
    for field in ("A1_hash", "SSOT_hash", "configuration_digest"):
        assert _rejected(bundle(loaded, universe, header_overrides={field: None})) == "BUNDLE_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "overrides",
    [
        {"unexpected_header_field": "x"},
        {"created_at": "2026-09-22T08:00:00"},
        {"candidate_git_sha": "abc123"},
        {"candidate_tree_digest": "Z" * 40},
        {"A2_hash": "0" * 63},
    ],
)
def test_malformed_header_is_rejected(overrides: dict[str, Any]) -> None:
    loaded, universe = load_real()
    assert _rejected(bundle(loaded, universe, header_overrides=overrides)) == "BUNDLE_SCHEMA_INVALID"


def test_unknown_top_level_section_is_rejected() -> None:
    loaded, universe = load_real()
    payload = bundle(loaded, universe) | {"bundle_schema": "wolf15.shadow-harness.bundle.v1"}
    assert _rejected(payload) == "BUNDLE_SCHEMA_INVALID"


def test_report_marks_bundle_implementation_only_non_canonical_and_echoes_header() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe), loaded, universe).to_json_dict()
    provenance = report["provenance"]
    assert provenance["bundle_schema_version"] == "shadow_capture_bundle/v1"
    assert provenance["bundle_marking"] == ["IMPLEMENTATION_ONLY", "NON_CANONICAL"]
    assert list(provenance["bundle_header"]) == list(BUNDLE_HEADER_FIELDS)
    assert provenance["bundle_header"]["manifest_hash"] == universe.canonical_sha256
    assert provenance["bundle_header"]["configuration_digest"] == loaded.policy_sha256


# --- E4: gate_passed / gate_failures are derived only -----------------------------------------


def test_supplied_gate_passed_rejected() -> None:
    loaded, universe = load_real()
    assert _rejected(bundle(loaded, universe) | {"gate_passed": True}) == "DERIVED_FIELD_SUPPLIED"


def test_supplied_gate_failures_rejected() -> None:
    loaded, universe = load_real()
    assert _rejected(bundle(loaded, universe) | {"gate_failures": []}) == "DERIVED_FIELD_SUPPLIED"


def test_supplied_derived_fields_rejected_anywhere_in_capture_input() -> None:
    loaded, universe = load_real()
    in_header = bundle(loaded, universe, header_overrides={"gate_passed": True})
    assert _rejected(in_header) == "DERIVED_FIELD_SUPPLIED"
    in_capture = bundle(loaded, universe, {"EURUSD": [candidate("EURUSD", gate_failures=[])]})
    assert _rejected(in_capture) == "DERIVED_FIELD_SUPPLIED"


def test_gate_failures_are_derived_in_fixed_flag_order() -> None:
    loaded, universe = load_real()
    eur = [
        candidate("EURUSD", pair_selection_source="OPERATOR", direction_selection_source="OPERATOR"),
        exact_s("EURUSD"),
        tradeplan("EURUSD"),
        broker_dry_run("EURUSD", universe, broker_submit_attempted=True),
        risk_dry_run("EURUSD"),
    ]
    gbp = candidate("GBPUSD")
    gbp["lineage"] = gbp["lineage"] | {"target_id": lineage("EURUSD", 1)["target_id"]}
    symbols = tuple(symbol for symbol in universe.symbols if symbol != "AUDCAD")
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": [gbp]}, symbols=symbols), loaded, universe)
    assert report.gate_failures == GATE_FLAG_ORDER
    assert report.gate_passed is False
    assert report.gate_failures == derive_gate_failures(report.acceptance, loaded.policy)


def test_derive_gate_failures_is_a_pure_function_of_the_five_flags() -> None:
    loaded, _ = load_real()
    clean = AcceptanceBlock.model_validate(
        {
            "30_PAIR_EVALUATED": True,
            "OPERATOR_PAIR_SELECTION": False,
            "OPERATOR_DIRECTION_SELECTION": False,
            "CROSS_PAIR_CONTAMINATION": 0,
            "BROKER_SUBMIT": 0,
        }
    )
    assert derive_gate_failures(clean, loaded.policy) == ()
    dirty = clean.model_copy(update={"broker_submit": 1, "pair_30_evaluated": False})
    assert derive_gate_failures(dirty, loaded.policy) == ("30_PAIR_EVALUATED", "BROKER_SUBMIT")


@pytest.mark.parametrize(
    "mutation",
    [
        {"gate_passed": False},
        {"gate_failures": ["BROKER_SUBMIT"]},
        {"gate_failures": ["BROKER_SUBMIT", "30_PAIR_EVALUATED"], "gate_passed": False},
    ],
)
def test_report_rejects_inconsistent_gate(mutation: dict[str, Any]) -> None:
    loaded, universe = load_real()
    original = evaluate(bundle(loaded, universe), loaded, universe).to_json_dict()
    assert ShadowHarnessReport.model_validate(original).gate_passed is True
    dumped = original | mutation
    with pytest.raises(ValidationError):
        ShadowHarnessReport.model_validate(dumped)


# --- Final SHADOW acceptance: shadow_acceptance_passed = gate_passed AND EXACT_S_ACCEPTED AND R9 envelope ---


@pytest.mark.parametrize(
    ("gate_passed", "exact_s_accepted", "expected_blockers"),
    [
        (True, True, ()),
        (True, False, ("EXACT_S_NOT_ACCEPTED",)),
        (False, True, ("GATE_NOT_PASSED",)),
        (False, False, ("GATE_NOT_PASSED", "EXACT_S_NOT_ACCEPTED")),
    ],
)
def test_shadow_acceptance_truth_table_with_a_frozen_envelope(
    gate_passed: bool, exact_s_accepted: bool, expected_blockers: tuple[str, ...]
) -> None:
    # A frozen envelope is not producible under policy 1.2.0; this exercises the pure derivation only.
    blockers = derive_shadow_acceptance_blockers(
        gate_passed=gate_passed, exact_s_accepted=exact_s_accepted, r9_envelope_frozen=True
    )
    assert blockers == expected_blockers
    assert (not blockers) is (gate_passed and exact_s_accepted)


def test_not_frozen_envelope_blocks_even_when_gate_and_exact_s_pass() -> None:
    blockers = derive_shadow_acceptance_blockers(gate_passed=True, exact_s_accepted=True, r9_envelope_frozen=False)
    assert blockers == ("R9_ENVELOPE_NOT_FROZEN",)
    assert not R9_ENVELOPE_FROZEN_STATUSES
    assert r9_envelope_is_frozen("NOT_FROZEN") is False
    assert r9_envelope_is_frozen("FROZEN") is False  # no status counts as frozen until the schema exists


def test_gate_passed_with_exact_s_false_is_final_acceptance_false() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"EURUSD": natural_chain("EURUSD", universe)}), loaded, universe)
    assert report.gate_passed is True  # unchanged five-flag meaning
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance_passed is False
    dumped = report.to_json_dict()
    assert dumped["shadow_acceptance_passed"] is False
    assert dumped["shadow_acceptance"]["label"] == "FINAL_NATURAL_SHADOW_ACCEPTANCE"
    assert dumped["shadow_acceptance"]["DEMO_PRECONDITION"] is False
    assert dumped["shadow_acceptance"]["blockers"] == ["EXACT_S_NOT_ACCEPTED", "R9_ENVELOPE_NOT_FROZEN"]


def test_gate_failed_with_exact_s_true_is_final_acceptance_false() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[1] = measured_exact_s("EURUSD", R9)
    symbols = tuple(symbol for symbol in universe.symbols if symbol != "AUDCAD")
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}, symbols=symbols), loaded, universe, frozenset({R9}))
    assert report.gate_passed is False
    assert report.dependent_acceptance.exact_s_accepted is True
    assert report.shadow_acceptance_passed is False
    assert report.shadow_acceptance.blockers == ("GATE_NOT_PASSED", "R9_ENVELOPE_NOT_FROZEN")


def test_r9_hash_match_without_frozen_envelope_is_final_acceptance_false() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[1] = measured_exact_s("EURUSD", R9)
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe, frozenset({R9}))
    assert report.gate_passed is True
    assert report.dependent_acceptance.candidates[0].exact_s_evaluation == "R9_BOUND"
    assert report.dependent_acceptance.exact_s_accepted is True
    assert report.r9_envelope_status == "NOT_FROZEN"
    assert report.shadow_acceptance_passed is False
    assert report.shadow_acceptance.demo_precondition is False
    assert report.shadow_acceptance.blockers == ("R9_ENVELOPE_NOT_FROZEN",)
    assert report.shadow_acceptance.r9_binding == R9_BINDING_MODE == "R9_ARTIFACT_SHA256_MATCH_ONLY"
    assert report.shadow_acceptance.r9_envelope_required_components == R9_ENVELOPE_REQUIRED_COMPONENTS
    assert R9_ENVELOPE_REQUIRED_COMPONENTS == (
        "source_artifact=R9",
        "artifact_sha256",
        "snapshot_identity_S",
        "collect_identity",
        "import_identity",
        "ACTIVE_readback_identity",
        "capability_result",
        "direct_receipt_result",
    )


@pytest.mark.parametrize("field", ["shadow_acceptance_passed", "DEMO_PRECONDITION", "r9_envelope_status"])
def test_supplied_final_acceptance_fields_rejected(field: str) -> None:
    loaded, universe = load_real()
    supplied: dict[str, Any] = {field: "FROZEN" if field == "r9_envelope_status" else True}
    assert _rejected(bundle(loaded, universe) | supplied) == "DERIVED_FIELD_SUPPLIED"
    in_capture = bundle(loaded, universe, {"EURUSD": [candidate("EURUSD", **supplied)]})
    assert _rejected(in_capture) == "DERIVED_FIELD_SUPPLIED"


def _mutated(original: dict[str, Any], section: str | None, updates: dict[str, Any]) -> dict[str, Any]:
    if section is None:
        return original | updates
    return original | {section: original[section] | updates}


@pytest.mark.parametrize(
    ("section", "updates"),
    [
        (None, {"shadow_acceptance_passed": True}),
        ("shadow_acceptance", {"DEMO_PRECONDITION": True}),
        ("shadow_acceptance", {"blockers": []}),
        ("shadow_acceptance", {"blockers": ["EXACT_S_NOT_ACCEPTED", "R9_ENVELOPE_NOT_FROZEN"]}),
        ("shadow_acceptance", {"r9_envelope_required_components": ["artifact_sha256"]}),
        (None, {"r9_envelope_status": "FROZEN"}),
    ],
)
def test_report_rejects_inconsistent_shadow_acceptance(section: str | None, updates: dict[str, Any]) -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[1] = measured_exact_s("EURUSD", R9)
    original = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe, frozenset({R9})).to_json_dict()
    assert ShadowHarnessReport.model_validate(original).shadow_acceptance_passed is False
    with pytest.raises(ValidationError):
        ShadowHarnessReport.model_validate(_mutated(original, section, updates))
