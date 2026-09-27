"""Owner decision D1 (2026-09-28, policy 1.5.0): snapshot S is an ACCOUNT snapshot, not a pair snapshot.

* the same verified S (and the one R9 artifact) bound by the EXACT_S captures of all 30 pairs of
  ``WOLF15_XM_30_V1`` is NOT cross-pair contamination;
* ONLY ``exact_s_id`` / ``exact_s_sha256`` / ``r9_artifact_sha256`` are exempt, and only while a reused value is
  carried by those fields alone; every other pair-specific id / digest stays pair-bound;
* EXACT_S stays ``evidence_scope = "PAIR"`` (the GLOBAL allow-list stays empty);
* the exemption grants no acceptance: EXACT_S_ACCEPTED still needs the ``verify_r9_envelope_v1`` verdict AND every
  capture bound to ``snapshot_s`` / ``artifact_sha256``;
* the policy file cannot widen (or otherwise change) the pinned exemption list.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.shadow_harness_helpers import (
    POLICY_PATH,
    R9_ARTIFACT_BYTES,
    R9_ARTIFACT_SHA256,
    S_ID,
    S_SHA256,
    bound_exact_s,
    bundle,
    digest,
    encode,
    evaluate,
    lineage,
    load_real,
    natural_chain,
    r9_envelope,
)
from tools.shadow_harness import isolation as isolation_module
from tools.shadow_harness.evaluator import ShadowHarnessReport, load_bundle_bytes
from tools.shadow_harness.manifest import (
    ACCOUNT_SNAPSHOT_BINDING_FIELDS_EXEMPT_FROM_CROSS_PAIR_REUSE,
    GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS,
    HarnessInputError,
    SymbolUniverse,
    load_policy_bytes,
)

EXEMPT = ("exact_s_id", "exact_s_sha256", "r9_artifact_sha256")
EXACT_S_INDEX = 1  # natural_chain: CANDIDATE, EXACT_S, TRADEPLAN, BROKER_ADAPTATION_DRY_RUN, RISK_DRY_RUN
RISK_INDEX = 4
VICTIM = "GBPUSD"
DONOR = "EURUSD"


def _bound_chain(universe: SymbolUniverse, symbol: str) -> list[dict[str, Any]]:
    chain = natural_chain(symbol, universe)
    chain[EXACT_S_INDEX] = bound_exact_s(symbol)
    return chain


def _all_30_same_s(universe: SymbolUniverse) -> dict[str, list[dict[str, Any]]]:
    return {symbol: _bound_chain(universe, symbol) for symbol in universe.symbols}


def _evaluate_30(captures: dict[str, list[dict[str, Any]]]) -> ShadowHarnessReport:
    loaded, universe = load_real()
    return evaluate(
        bundle(loaded, universe, captures),
        loaded,
        universe,
        r9_envelope=r9_envelope(),
        r9_artifact=R9_ARTIFACT_BYTES,
    )


def _contaminated_values(report: ShadowHarnessReport) -> dict[str, set[str]]:
    return {finding.value: set(finding.fields) for finding in report.contamination_findings}


def _policy_payload() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


# --- the exemption is pinned in code and in the policy -------------------------------------------------------------


def test_exemption_is_exactly_the_three_account_snapshot_binding_fields() -> None:
    assert ACCOUNT_SNAPSHOT_BINDING_FIELDS_EXEMPT_FROM_CROSS_PAIR_REUSE == EXEMPT
    assert isolation_module.ACCOUNT_SNAPSHOT_BINDING_FIELDS_EXEMPT_FROM_CROSS_PAIR_REUSE is (
        ACCOUNT_SNAPSHOT_BINDING_FIELDS_EXEMPT_FROM_CROSS_PAIR_REUSE
    )
    loaded, universe = load_real()
    assert loaded.policy.policy_version == "1.5.0"
    assert tuple(loaded.policy.account_snapshot_binding_fields_exempt_from_cross_pair_reuse) == EXEMPT
    assert GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS == () == tuple(loaded.policy.global_scope_allowed_capture_kinds)
    assert "EXACT_S" in loaded.policy.global_scope_forbidden_capture_kinds
    assert len(universe.symbols) == 30


@pytest.mark.parametrize(
    "exempt",
    [
        [*EXEMPT, "evidence_sha256"],
        [*EXEMPT, "capture_id"],
        [*EXEMPT, "lifecycle_id"],
        [*EXEMPT, "thesis_id"],
        [*EXEMPT, "candidate_id"],
        [*EXEMPT, "execution_box_id"],
        [*EXEMPT, "tradeplan_candidate_id"],
        [*EXEMPT, "*"],
        ["exact_s_id", "exact_s_sha256"],
        ["r9_artifact_sha256", "exact_s_sha256", "exact_s_id"],
        [*EXEMPT, "exact_s_id"],
        [],
        ["evidence_sha256"],
    ],
    ids=[
        "widen-evidence-sha256",
        "widen-capture-id",
        "widen-lifecycle-id",
        "widen-thesis-id",
        "widen-candidate-id",
        "widen-execution-box-id",
        "widen-tradeplan-candidate-id",
        "widen-wildcard",
        "narrow",
        "reordered",
        "duplicated",
        "empty",
        "replaced",
    ],
)
def test_policy_cannot_widen_or_change_the_exemption(exempt: list[str]) -> None:
    payload = _policy_payload() | {"account_snapshot_binding_fields_exempt_from_cross_pair_reuse": exempt}
    with pytest.raises(HarnessInputError) as info:
        load_policy_bytes(json.dumps(payload).encode())
    assert info.value.code == "POLICY_SCHEMA_INVALID"


def test_policy_cannot_make_exact_s_global() -> None:
    for mutation in (
        {"global_scope_allowed_capture_kinds": ["EXACT_S"]},
        {
            "global_scope_forbidden_capture_kinds": [
                "BROKER_ADAPTATION_DRY_RUN",
                "CANDIDATE",
                "RISK_DRY_RUN",
                "TRADEPLAN",
            ]
        },
    ):
        with pytest.raises(HarnessInputError) as info:
            load_policy_bytes(json.dumps(_policy_payload() | mutation).encode())
        assert info.value.code == "POLICY_SCHEMA_INVALID"


def test_exact_s_declared_global_still_rejects_the_bundle() -> None:
    loaded, universe = load_real()
    captures = _all_30_same_s(universe)
    captures[DONOR][EXACT_S_INDEX] = bound_exact_s(DONOR, evidence_scope="GLOBAL")
    with pytest.raises(HarnessInputError) as info:
        evaluate(bundle(loaded, universe, captures), loaded, universe)
    assert info.value.code == "BUNDLE_SCHEMA_INVALID"


# --- required 1: the same verified S across all 30 pairs ----------------------------------------------------------


def test_same_verified_s_across_all_30_pairs_is_not_contamination_and_accepts() -> None:
    _, universe = load_real()
    report = _evaluate_30(_all_30_same_s(universe))

    assert report.acceptance.pair_30_evaluated is True
    assert report.acceptance.cross_pair_contamination == 0
    assert report.contamination_findings == ()
    assert report.isolation_findings == ()
    assert (report.gate_passed, report.gate_failures) == (True, ())

    dependent = report.dependent_acceptance
    assert dependent.r9_envelope_verification.exact_s_accepted is True
    assert len(dependent.candidates) == 30
    assert {row.symbol for row in dependent.candidates} == set(universe.symbols)
    for row in dependent.candidates:
        assert row.exact_s_evaluation == "R9_ENVELOPE_BOUND"
        assert (row.exact_s_id, row.exact_s_sha256, row.r9_artifact_sha256) == (S_ID, S_SHA256, R9_ARTIFACT_SHA256)
    assert dependent.exact_s_accepted is True

    assert report.r9_envelope_status == "FROZEN"
    assert report.shadow_acceptance.blockers == ()
    assert report.shadow_acceptance_passed is True
    assert report.shadow_acceptance.demo_precondition is True

    # the exempt reuse is visible (DIAGNOSTIC_ONLY), never silently dropped
    binding = {item.value: item for item in report.diagnostics if item.kind == "ACCOUNT_SNAPSHOT_BINDING_REUSE"}
    assert set(binding) == {S_ID, S_SHA256, R9_ARTIFACT_SHA256}
    assert binding[S_ID].fields == ("exact_s_id",)
    assert binding[S_SHA256].fields == ("exact_s_sha256",)
    assert binding[R9_ARTIFACT_SHA256].fields == ("r9_artifact_sha256",)
    assert all(item.symbols == tuple(sorted(universe.symbols)) for item in binding.values())
    assert all(item.severity == "DIAGNOSTIC_ONLY" for item in report.diagnostics)
    assert all(capture["evidence_scope"] == "PAIR" for chain in _all_30_same_s(universe).values() for capture in chain)
    # the report round-trips through its own derived-field validators
    assert ShadowHarnessReport.model_validate(report.to_json_dict()).shadow_acceptance_passed is True


def test_same_foreign_s_across_30_pairs_is_not_contamination_but_is_not_accepted() -> None:
    """The exemption grants no acceptance authority: a consistent S that is not the verified snapshot_s fails."""

    _, universe = load_real()
    captures = _all_30_same_s(universe)
    for symbol, chain in captures.items():
        chain[EXACT_S_INDEX] = bound_exact_s(
            symbol, exact_s_id="snap-foreign-account-s", exact_s_sha256=digest("foreign-s")
        )
    report = _evaluate_30(captures)
    assert report.acceptance.cross_pair_contamination == 0
    assert report.gate_passed is True
    assert {row.exact_s_evaluation for row in report.dependent_acceptance.candidates} == {"SNAPSHOT_S_NOT_BOUND"}
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance.blockers == ("EXACT_S_NOT_ACCEPTED",)
    assert report.shadow_acceptance_passed is False


def test_same_s_across_30_pairs_without_a_verified_envelope_is_not_accepted() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, _all_30_same_s(universe)), loaded, universe)
    assert report.acceptance.cross_pair_contamination == 0
    assert report.gate_passed is True
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance_passed is False


# --- required 2: same S, one capture carries a foreign lifecycle_id ----------------------------------------------


@pytest.mark.parametrize("index", [EXACT_S_INDEX, RISK_INDEX], ids=["exact-s", "risk-dry-run"])
def test_same_s_with_a_foreign_lifecycle_id_is_contamination(index: int) -> None:
    _, universe = load_real()
    captures = _all_30_same_s(universe)
    foreign_lifecycle = lineage(DONOR, 1)["lifecycle_id"]
    victim = captures[VICTIM][index]
    victim["lineage"] = victim["lineage"] | {"lifecycle_id": foreign_lifecycle}

    report = _evaluate_30(captures)
    assert report.acceptance.cross_pair_contamination >= 1
    assert "CROSS_PAIR_CONTAMINATION" in report.gate_failures
    assert report.gate_passed is False
    finding = next(item for item in report.contamination_findings if item.value == foreign_lifecycle)
    assert (finding.detector, finding.kind, finding.fields) == ("PRIMARY_LINEAGE", "LINEAGE_ID", ("lifecycle_id",))
    assert finding.symbols == (DONOR, VICTIM)
    assert report.shadow_acceptance_passed is False
    assert "GATE_NOT_PASSED" in report.shadow_acceptance.blockers


# --- required 3: same S, one pair carries a wrong exact_s_sha256 ------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "evaluation"),
    [
        ({"exact_s_sha256": digest("some-other-account-s")}, "SNAPSHOT_S_NOT_BOUND"),
        ({"exact_s_id": "snap-some-other-account-s"}, "SNAPSHOT_S_NOT_BOUND"),
        ({"r9_artifact_sha256": digest("some-other-r9-artifact")}, "R9_ARTIFACT_NOT_BOUND"),
    ],
    ids=["wrong-exact-s-sha256", "wrong-exact-s-id", "wrong-r9-artifact-sha256"],
)
def test_same_s_with_one_pair_wrongly_bound_is_not_exact_s_accepted(overrides: dict[str, Any], evaluation: str) -> None:
    _, universe = load_real()
    captures = _all_30_same_s(universe)
    captures[VICTIM][EXACT_S_INDEX] = bound_exact_s(VICTIM, **overrides)

    report = _evaluate_30(captures)
    assert report.acceptance.cross_pair_contamination == 0
    assert report.gate_passed is True
    rows = {row.symbol: row for row in report.dependent_acceptance.candidates}
    assert rows[VICTIM].exact_s_evaluation == evaluation
    assert rows[VICTIM].exact_s_accepted is False
    assert all(row.exact_s_accepted for symbol, row in rows.items() if symbol != VICTIM)
    assert report.dependent_acceptance.r9_envelope_verification.exact_s_accepted is True
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance.blockers == ("EXACT_S_NOT_ACCEPTED",)
    assert report.shadow_acceptance_passed is False


# --- required 4: the same capture_id reused across pairs ---------------------------------------------------------


@pytest.mark.parametrize("index", [EXACT_S_INDEX, RISK_INDEX], ids=["exact-s", "risk-dry-run"])
def test_same_s_with_a_capture_id_reused_across_pairs_is_contamination(index: int) -> None:
    _, universe = load_real()
    captures = _all_30_same_s(universe)
    reused = captures[DONOR][index]["capture_id"]
    captures[VICTIM][index] = captures[VICTIM][index] | {"capture_id": reused}

    report = _evaluate_30(captures)
    assert "CROSS_PAIR_CONTAMINATION" in report.gate_failures
    assert _contaminated_values(report) == {reused: {"capture_id"}}
    finding = report.contamination_findings[0]
    assert (finding.detector, finding.kind, finding.symbols) == (
        "SECONDARY_PAIR_SCOPED_EVIDENCE",
        "EVIDENCE_ID",
        (DONOR, VICTIM),
    )
    assert report.shadow_acceptance_passed is False


# --- an exempt field can never shelter another field -------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "field"),
    [
        (EXACT_S_INDEX, "evidence_sha256"),
        (0, "evidence_sha256"),
        (0, "candidate_id"),
        (RISK_INDEX, "risk_evaluation_id"),
        (3, "adaptation_id"),
    ],
)
def test_pair_evidence_reused_across_pairs_still_fails_beside_the_exempt_s(index: int, field: str) -> None:
    _, universe = load_real()
    captures = _all_30_same_s(universe)
    reused = captures[DONOR][index][field]
    captures[VICTIM][index] = captures[VICTIM][index] | {field: reused}

    report = _evaluate_30(captures)
    assert "CROSS_PAIR_CONTAMINATION" in report.gate_failures
    assert _contaminated_values(report) == {reused: {field}}
    assert report.dependent_acceptance.exact_s_accepted is True  # S itself is still correctly bound everywhere
    assert report.shadow_acceptance_passed is False


@pytest.mark.parametrize(
    "field", ["thesis_id", "proof_id", "pressure_range_id", "target_id", "execution_box_id", "tradeplan_candidate_id"]
)
def test_pair_lineage_ids_are_never_exempt(field: str) -> None:
    _, universe = load_real()
    captures = _all_30_same_s(universe)
    foreign = lineage(DONOR, 1)[field]
    risk = captures[VICTIM][RISK_INDEX]
    risk["lineage"] = risk["lineage"] | {field: foreign}

    report = _evaluate_30(captures)
    assert "CROSS_PAIR_CONTAMINATION" in report.gate_failures
    assert foreign in _contaminated_values(report)
    assert report.shadow_acceptance_passed is False


@pytest.mark.parametrize(
    ("index", "field", "value", "exempt_field"),
    [
        (EXACT_S_INDEX, "evidence_sha256", S_SHA256, "exact_s_sha256"),
        (0, "evidence_sha256", S_SHA256, "exact_s_sha256"),
        (EXACT_S_INDEX, "evidence_sha256", R9_ARTIFACT_SHA256, "r9_artifact_sha256"),
        (RISK_INDEX, "evidence_sha256", R9_ARTIFACT_SHA256, "r9_artifact_sha256"),
        (EXACT_S_INDEX, "capture_id", S_ID, "exact_s_id"),
        (0, "candidate_id", S_ID, "exact_s_id"),
    ],
    ids=[
        "exact-s-evidence-sha-is-s",
        "candidate-evidence-sha-is-s",
        "exact-s-evidence-sha-is-r9",
        "risk-evidence-sha-is-r9",
        "exact-s-capture-id-is-s-id",
        "candidate-id-is-s-id",
    ],
)
def test_account_snapshot_value_in_a_non_exempt_field_is_contamination(
    index: int, field: str, value: str, exempt_field: str
) -> None:
    """A pair-specific field carrying the S / R9 value cannot hide behind the exemption: every observation counts."""

    _, universe = load_real()
    captures = _all_30_same_s(universe)
    captures[VICTIM][index] = captures[VICTIM][index] | {field: value}

    report = _evaluate_30(captures)
    assert "CROSS_PAIR_CONTAMINATION" in report.gate_failures
    contaminated = _contaminated_values(report)
    assert contaminated[value] == {field, exempt_field}
    finding = next(item for item in report.contamination_findings if item.value == value)
    assert len(finding.symbols) == 30
    assert not any(item.value == value for item in report.diagnostics)
    assert report.shadow_acceptance_passed is False


def test_detector_exemption_is_bound_to_the_exact_s_capture_kind() -> None:
    """The exempt field names only exist on EXACT_S; the same S reused through a candidate id is contamination."""

    loaded, universe = load_real()
    parsed = load_bundle_bytes(encode(bundle(loaded, universe, _all_30_same_s(universe))), loaded, universe)
    assert isolation_module.detect_cross_pair_contamination(parsed) == ()
    reuse = isolation_module.detect_account_snapshot_binding_reuse_diagnostics(parsed)
    assert {item.value for item in reuse} == {S_ID, S_SHA256, R9_ARTIFACT_SHA256}
    assert {ref.capture_id.split("-")[1] for item in reuse for ref in item.captures} == {"exact_s"}
