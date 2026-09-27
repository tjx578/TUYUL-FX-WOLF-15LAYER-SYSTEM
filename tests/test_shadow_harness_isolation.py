"""Per-symbol isolation and lineage-based cross-pair contamination for the offline shadow harness."""

from __future__ import annotations

from typing import Any, get_args

import pytest

from tests.shadow_harness_helpers import (
    broker_dry_run,
    bundle,
    candidate,
    digest,
    evaluate,
    exact_s,
    lineage,
    load_real,
    natural_chain,
    risk_dry_run,
    tradeplan,
)
from tools.shadow_harness.captures import (
    LINEAGE_FIELDS,
    CandidateCapture,
    Capture,
    ShadowCaptureBundle,
    evidence_scope_violations,
)
from tools.shadow_harness.isolation import (
    IsolationFinding,
    detect_cross_pair_contamination,
    detect_global_evidence_reuse_diagnostics,
    detect_price_overlap_diagnostics,
    validate_symbol_isolation,
)
from tools.shadow_harness.manifest import (
    CAPTURE_KINDS,
    GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS,
    GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS,
    PAIR_BINDING_REQUIRED_CAPTURE_KINDS,
    HarnessInputError,
)

MISSING = object()


def _codes(findings: tuple[IsolationFinding, ...]) -> list[str]:
    return sorted(item.code for item in findings)


def test_primary_lineage_fields_are_exactly_the_owner_list() -> None:
    assert LINEAGE_FIELDS == (
        "lifecycle_id",
        "thesis_id",
        "proof_id",
        "pressure_range_id",
        "target_id",
        "execution_box_id",
        "tradeplan_candidate_id",
    )


def test_clean_natural_chains_have_no_findings() -> None:
    loaded, universe = load_real()
    payload = bundle(
        loaded,
        universe,
        {symbol: natural_chain(symbol, universe) for symbol in ("EURUSD", "GBPUSD", "XAUUSD")},
    )
    parsed = ShadowCaptureBundle.model_validate(payload)
    assert validate_symbol_isolation(parsed, universe) == ()
    assert detect_cross_pair_contamination(parsed) == ()
    assert detect_price_overlap_diagnostics(parsed) == ()


def test_eurusd_capture_with_gbpusd_thesis_id_is_cross_pair_contamination_and_fails() -> None:
    loaded, universe = load_real()
    eur = natural_chain("EURUSD", universe)
    eur[0]["lineage"] = eur[0]["lineage"] | {"thesis_id": lineage("GBPUSD", 1)["thesis_id"]}
    eur[1]["lineage"] = eur[1]["lineage"] | {"thesis_id": lineage("GBPUSD", 1)["thesis_id"]}
    eur[2]["lineage"] = eur[2]["lineage"] | {"thesis_id": lineage("GBPUSD", 1)["thesis_id"]}
    gbp = natural_chain("GBPUSD", universe)
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}), loaded, universe)
    assert report.isolation_findings == ()  # anchors stay consistent inside EURUSD; only lineage leaks
    assert report.acceptance.cross_pair_contamination == 1
    finding = report.contamination_findings[0]
    assert (finding.code, finding.detector, finding.kind) == (
        "CROSS_PAIR_CONTAMINATION",
        "PRIMARY_LINEAGE",
        "LINEAGE_ID",
    )
    assert finding.fields == ("thesis_id",)
    assert finding.value == lineage("GBPUSD", 1)["thesis_id"]
    assert finding.symbols == ("EURUSD", "GBPUSD")
    assert not report.gate_passed
    assert report.gate_failures == ("CROSS_PAIR_CONTAMINATION",)


def test_every_primary_lineage_field_is_scanned() -> None:
    loaded, universe = load_real()
    for field in LINEAGE_FIELDS:
        gbp_value = lineage("GBPUSD", 1)[field]
        eur = candidate("EURUSD")
        eur["lineage"] = eur["lineage"] | {field: gbp_value}
        gbp = tradeplan("GBPUSD")
        gbp["lineage"] = gbp["lineage"] | {field: gbp_value}
        payload = bundle(loaded, universe, {"EURUSD": [eur], "GBPUSD": [gbp]})
        found = detect_cross_pair_contamination(ShadowCaptureBundle.model_validate(payload))
        assert [(item.kind, item.value) for item in found] == [("LINEAGE_ID", gbp_value)], field


@pytest.mark.parametrize("kind", ["CANDIDATE", "EXACT_S", "TRADEPLAN", "BROKER_ADAPTATION_DRY_RUN", "RISK_DRY_RUN"])
def test_pair_capture_with_mismatched_canonical_symbol_is_rejected(kind: str) -> None:
    loaded, universe = load_real()
    foreign = _record(kind, "GBPUSD")
    with pytest.raises(HarnessInputError) as info:
        evaluate(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD"), foreign]}), loaded, universe)
    assert info.value.code == "BUNDLE_SCHEMA_INVALID"
    assert "PAIR-scoped capture symbol GBPUSD does not match its key" in info.value.message


def test_symbol_detector_stays_as_defense_in_depth_for_constructed_bundles() -> None:
    loaded, universe = load_real()
    parsed = ShadowCaptureBundle.model_validate(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD")]}))
    foreign = CandidateCapture.model_validate(candidate("GBPUSD"))
    constructed = ShadowCaptureBundle.model_construct(header=parsed.header, captures_by_symbol={"EURUSD": (foreign,)})
    kinds = [(item.detector, item.kind, item.value) for item in detect_cross_pair_contamination(constructed)]
    assert kinds == [("PRIMARY_LINEAGE", "SYMBOL", "GBPUSD@EURUSD")]


def test_identical_prices_across_two_pairs_with_clean_lineage_is_not_contamination() -> None:
    loaded, universe = load_real()
    eur = natural_chain("EURUSD", universe)
    gbp = natural_chain("GBPUSD", universe)
    same = [dict(point) for point in eur[2]["prices"]]
    gbp[2] = gbp[2] | {"prices": same}
    gbp[3] = gbp[3] | {"prices": [dict(point) for point in eur[3]["prices"]]}
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}), loaded, universe)
    assert report.contamination_findings == ()
    assert report.acceptance.cross_pair_contamination == 0
    assert report.isolation_findings == ()
    assert report.gate_passed and report.gate_failures == ()
    [overlap] = report.diagnostics  # tradeplan + broker dry-run share one vector per pair
    assert (overlap.severity, overlap.kind, overlap.symbols) == (
        "DIAGNOSTIC_ONLY",
        "PRICE_VECTOR_OVERLAP",
        ("EURUSD", "GBPUSD"),
    )
    assert len(overlap.captures) == 4


def test_price_overlap_is_detected_after_normalisation_but_stays_diagnostic() -> None:
    loaded, universe = load_real()
    eur = natural_chain("EURUSD", universe)
    gbp = natural_chain("GBPUSD", universe)
    copied = [dict(point) for point in eur[2]["prices"]]
    copied[0]["value"] = copied[0]["value"] + "0"  # 1.1xxxx0 == 1.1xxxx
    gbp[2] = gbp[2] | {"prices": copied}
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}), loaded, universe)
    assert [item.kind for item in report.diagnostics] == ["PRICE_VECTOR_OVERLAP"]
    assert report.acceptance.cross_pair_contamination == 0
    assert report.gate_passed


def test_pair_scoped_evidence_reuse_across_pairs_is_contamination_and_fails() -> None:
    loaded, universe = load_real()
    eur = candidate("EURUSD")
    gbp = candidate("GBPUSD", evidence_sha256=eur["evidence_sha256"], candidate_id=eur["candidate_id"])
    report = evaluate(bundle(loaded, universe, {"EURUSD": [eur], "GBPUSD": [gbp]}), loaded, universe)
    assert sorted(item.kind for item in report.contamination_findings) == ["EVIDENCE_ID", "EVIDENCE_SHA256"]
    assert {item.detector for item in report.contamination_findings} == {"SECONDARY_PAIR_SCOPED_EVIDENCE"}
    assert {item.evidence_scopes for item in report.contamination_findings} == {("PAIR",)}
    assert report.acceptance.cross_pair_contamination == 2
    assert report.gate_failures == ("CROSS_PAIR_CONTAMINATION",)
    assert report.diagnostics == ()


def _record(kind: str, symbol: str, **overrides: Any) -> dict[str, Any]:
    _, universe = load_real()
    if kind == "BROKER_ADAPTATION_DRY_RUN":
        return broker_dry_run(symbol, universe, **overrides)
    builders = {
        "CANDIDATE": candidate,
        "EXACT_S": exact_s,
        "TRADEPLAN": tradeplan,
        "RISK_DRY_RUN": risk_dry_run,
    }
    return builders[kind](symbol, **overrides)


def _rejection(payload: dict[str, Any]) -> HarnessInputError:
    loaded, universe = load_real()
    with pytest.raises(HarnessInputError) as info:
        evaluate(payload, loaded, universe)
    assert info.value.code == "BUNDLE_SCHEMA_INVALID"
    return info.value


def test_global_scope_allow_list_is_explicit_and_empty_for_existing_kinds() -> None:
    kinds = get_args(get_args(Capture)[0])
    discriminators = tuple(sorted(get_args(model.model_fields["capture_kind"].annotation)[0] for model in kinds))
    assert discriminators == CAPTURE_KINDS
    assert GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS == ()  # no existing kind is system/global authority evidence
    assert GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS == CAPTURE_KINDS
    assert PAIR_BINDING_REQUIRED_CAPTURE_KINDS == ("CANDIDATE", "TRADEPLAN")


def test_candidate_with_global_scope_is_rejected() -> None:
    loaded, universe = load_real()
    error = _rejection(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD", evidence_scope="GLOBAL")]}))
    assert "CANDIDATE is pair-specific strategy evidence and can never be GLOBAL-scoped" in error.message


def test_tradeplan_with_global_scope_is_rejected() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[2] = chain[2] | {"evidence_scope": "GLOBAL"}
    error = _rejection(bundle(loaded, universe, {"EURUSD": chain}))
    assert "TRADEPLAN is pair-specific strategy evidence and can never be GLOBAL-scoped" in error.message


@pytest.mark.parametrize("kind", ["CANDIDATE", "EXACT_S", "TRADEPLAN", "BROKER_ADAPTATION_DRY_RUN", "RISK_DRY_RUN"])
def test_every_existing_kind_with_global_scope_rejects_the_bundle(kind: str) -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    index = [item["capture_kind"] for item in chain].index(kind)
    chain[index] = chain[index] | {"evidence_scope": "GLOBAL"}
    error = _rejection(bundle(loaded, universe, {"EURUSD": chain}))
    assert f"{kind} is pair-specific strategy evidence" in error.message


def test_shared_global_evidence_across_pairs_is_rejected_not_diagnostic() -> None:
    loaded, universe = load_real()
    shared = digest("market-wide-snapshot")
    eur = natural_chain("EURUSD", universe)
    gbp = natural_chain("GBPUSD", universe)
    eur[1] = eur[1] | {"evidence_scope": "GLOBAL", "evidence_sha256": shared}
    gbp[1] = gbp[1] | {"evidence_scope": "GLOBAL", "evidence_sha256": shared}
    _rejection(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}))


@pytest.mark.parametrize(
    ("drop", "unbound"),
    [
        ("candidate_revision", None),
        (None, "lifecycle_id"),
    ],
)
def test_pair_candidate_missing_lifecycle_or_revision_binding_is_rejected(
    drop: str | None, unbound: str | None
) -> None:
    loaded, universe = load_real()
    record = candidate("EURUSD")
    if drop is not None:
        del record[drop]
    if unbound is not None:
        record["lineage"] = record["lineage"] | {unbound: None}
    _rejection(bundle(loaded, universe, {"EURUSD": [record]}))


@pytest.mark.parametrize("revision", [0, -1, "1", True, 1.0, None])
def test_candidate_and_tradeplan_revision_must_be_strict_positive_int(revision: object) -> None:
    loaded, universe = load_real()
    _rejection(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD", candidate_revision=revision)]}))
    chain = natural_chain("EURUSD", universe)
    chain[2] = chain[2] | {"tradeplan_revision": revision}
    _rejection(bundle(loaded, universe, {"EURUSD": chain}))


@pytest.mark.parametrize("field", ["tradeplan_revision", "lineage.tradeplan_candidate_id", "lineage.lifecycle_id"])
def test_pair_tradeplan_missing_candidate_or_revision_binding_is_rejected(field: str) -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    if field.startswith("lineage."):
        chain[2]["lineage"] = chain[2]["lineage"] | {field.removeprefix("lineage."): None}
    else:
        del chain[2][field]
    _rejection(bundle(loaded, universe, {"EURUSD": chain}))


def test_scope_rule_names_every_unbound_pair_binding_field() -> None:
    bound = CandidateCapture.model_validate(candidate("EURUSD"))
    unbound = bound.model_copy(update={"lineage": bound.lineage.model_copy(update={"lifecycle_id": None})})
    assert evidence_scope_violations("EURUSD", bound) == ()
    assert evidence_scope_violations("EURUSD", unbound) == (
        "EURUSD/cap-candidate-EURUSD-1: PAIR-scoped CANDIDATE must bind lineage.lifecycle_id",
    )
    assert evidence_scope_violations("GBPUSD", bound) == (
        "GBPUSD/cap-candidate-EURUSD-1: PAIR-scoped capture symbol EURUSD does not match its key",
    )


def test_scope_aware_detectors_stay_as_defense_in_depth_for_constructed_bundles() -> None:
    """Unreachable through parsing under policy 1.3.0; the detectors still classify an already-built bundle."""

    loaded, universe = load_real()
    shared = digest("market-wide-snapshot")
    parsed = ShadowCaptureBundle.model_validate(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD")]}))

    def built(symbol: str, scope: str) -> CandidateCapture:
        capture = CandidateCapture.model_validate(candidate(symbol, evidence_sha256=shared))
        return capture.model_copy(update={"evidence_scope": scope})

    all_global = ShadowCaptureBundle.model_construct(
        header=parsed.header,
        captures_by_symbol={"EURUSD": (built("EURUSD", "GLOBAL"),), "GBPUSD": (built("GBPUSD", "GLOBAL"),)},
    )
    assert detect_cross_pair_contamination(all_global) == ()
    [diagnostic] = detect_global_evidence_reuse_diagnostics(all_global)
    assert (diagnostic.kind, diagnostic.value, diagnostic.symbols) == (
        "GLOBAL_SCOPED_EVIDENCE_SHA256_REUSE",
        shared,
        ("EURUSD", "GBPUSD"),
    )
    mixed = ShadowCaptureBundle.model_construct(
        header=parsed.header,
        captures_by_symbol={"EURUSD": (built("EURUSD", "GLOBAL"),), "GBPUSD": (built("GBPUSD", "PAIR"),)},
    )
    [finding] = detect_cross_pair_contamination(mixed)
    assert (finding.kind, finding.evidence_scopes) == ("EVIDENCE_SHA256", ("GLOBAL", "PAIR"))
    assert detect_global_evidence_reuse_diagnostics(mixed) == ()


@pytest.mark.parametrize("scope", [MISSING, None, "", "pair", "UNKNOWN", "SYMBOL"])
def test_missing_or_unknown_evidence_scope_is_rejected_never_global(scope: object) -> None:
    loaded, universe = load_real()
    record = candidate("EURUSD")
    if scope is MISSING:
        del record["evidence_scope"]
    else:
        record["evidence_scope"] = scope
    with pytest.raises(HarnessInputError) as info:
        evaluate(bundle(loaded, universe, {"EURUSD": [record]}), loaded, universe)
    assert info.value.code == "BUNDLE_SCHEMA_INVALID"


def test_unknown_symbol_key_is_isolation_violation_and_not_thirty() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"BTCUSD": [candidate("BTCUSD")]}), loaded, universe)
    assert "UNKNOWN_SYMBOL_KEY" in _codes(report.isolation_findings)
    assert report.acceptance.pair_30_evaluated is False
    assert report.gate_failures == ("30_PAIR_EVALUATED",)


def test_broker_symbol_must_match_frozen_map() -> None:
    loaded, universe = load_real()
    chain = natural_chain("XAUUSD", universe)
    chain[3] = chain[3] | {"broker_symbol": "XAUUSD"}
    report = evaluate(bundle(loaded, universe, {"XAUUSD": chain}), loaded, universe)
    assert _codes(report.isolation_findings) == ["BROKER_SYMBOL_MISMATCH"]
    assert report.gate_failures == ("30_PAIR_EVALUATED",)


def test_tradeplan_without_candidate_is_unanchored_not_fabricated() -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(
            loaded,
            universe,
            {"EURUSD": [tradeplan("EURUSD"), broker_dry_run("EURUSD", universe), risk_dry_run("EURUSD")]},
        ),
        loaded,
        universe,
    )
    assert _codes(report.isolation_findings) == ["UNANCHORED_LINEAGE"]
    eur = next(item for item in report.symbols if item.symbol == "EURUSD")
    assert (eur.status, eur.candidate_count) == ("WAIT", 0)
    assert report.acceptance.pair_30_evaluated is False


def test_exact_s_without_candidate_is_unanchored() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"EURUSD": [exact_s("EURUSD")]}), loaded, universe)
    assert _codes(report.isolation_findings) == ["UNANCHORED_LINEAGE"]


def test_dry_run_must_reference_same_symbol_tradeplan() -> None:
    loaded, universe = load_real()
    chain = natural_chain("EURUSD", universe)
    chain[4] = risk_dry_run("EURUSD", n=2)
    report = evaluate(bundle(loaded, universe, {"EURUSD": chain}), loaded, universe)
    assert _codes(report.isolation_findings) == ["UNANCHORED_LINEAGE"]


def test_duplicate_capture_id_within_symbol() -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe, {"EURUSD": [candidate("EURUSD"), candidate("EURUSD")]}), loaded, universe
    )
    assert _codes(report.isolation_findings) == ["DUPLICATE_CAPTURE_ID"]
    assert report.acceptance.cross_pair_contamination == 0
