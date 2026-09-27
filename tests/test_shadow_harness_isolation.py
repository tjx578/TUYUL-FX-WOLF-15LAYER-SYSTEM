"""Per-symbol isolation and lineage-based cross-pair contamination for the offline shadow harness."""

from __future__ import annotations

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
from tools.shadow_harness.captures import LINEAGE_FIELDS, ShadowCaptureBundle
from tools.shadow_harness.isolation import (
    IsolationFinding,
    detect_cross_pair_contamination,
    detect_global_evidence_reuse_diagnostics,
    detect_price_overlap_diagnostics,
    validate_symbol_isolation,
)
from tools.shadow_harness.manifest import HarnessInputError

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


def test_record_filed_under_another_symbol_key_is_symbol_contamination() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"EURUSD": [candidate("GBPUSD")]}), loaded, universe)
    kinds = [(item.detector, item.kind, item.value) for item in report.contamination_findings]
    assert kinds == [("PRIMARY_LINEAGE", "SYMBOL", "GBPUSD@EURUSD")]
    assert report.gate_failures == ("CROSS_PAIR_CONTAMINATION",)
    eur = next(item for item in report.symbols if item.symbol == "EURUSD")
    assert eur.status == "WAIT"  # a foreign record never counts as this pair's candidate


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


def test_mixed_scope_reuse_fails_closed_as_contamination() -> None:
    loaded, universe = load_real()
    eur = candidate("EURUSD", evidence_scope="GLOBAL")
    gbp = candidate("GBPUSD", evidence_sha256=eur["evidence_sha256"])  # PAIR-scoped carrier of the same digest
    report = evaluate(bundle(loaded, universe, {"EURUSD": [eur], "GBPUSD": [gbp]}), loaded, universe)
    [finding] = report.contamination_findings
    assert (finding.kind, finding.evidence_scopes) == ("EVIDENCE_SHA256", ("GLOBAL", "PAIR"))
    assert report.gate_failures == ("CROSS_PAIR_CONTAMINATION",)


def test_global_scoped_evidence_reuse_is_diagnostic_only_and_gate_unaffected() -> None:
    loaded, universe = load_real()
    shared = digest("market-wide-snapshot")
    eur = natural_chain("EURUSD", universe)
    gbp = natural_chain("GBPUSD", universe)
    eur[1] = eur[1] | {"evidence_scope": "GLOBAL", "evidence_sha256": shared}
    gbp[1] = gbp[1] | {"evidence_scope": "GLOBAL", "evidence_sha256": shared}
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}), loaded, universe)
    assert report.contamination_findings == ()
    assert report.acceptance.cross_pair_contamination == 0
    assert report.gate_passed and report.gate_failures == ()
    [diagnostic] = report.diagnostics
    assert (diagnostic.severity, diagnostic.kind, diagnostic.fields, diagnostic.value, diagnostic.symbols) == (
        "DIAGNOSTIC_ONLY",
        "GLOBAL_SCOPED_EVIDENCE_SHA256_REUSE",
        ("evidence_sha256",),
        shared,
        ("EURUSD", "GBPUSD"),
    )
    parsed = ShadowCaptureBundle.model_validate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}))
    assert detect_global_evidence_reuse_diagnostics(parsed) == report.diagnostics


def test_global_scope_never_excuses_lineage_reuse() -> None:
    loaded, universe = load_real()
    eur = candidate("EURUSD", evidence_scope="GLOBAL")
    eur["lineage"] = eur["lineage"] | {"thesis_id": lineage("GBPUSD", 1)["thesis_id"]}
    gbp = candidate("GBPUSD", evidence_scope="GLOBAL")
    report = evaluate(bundle(loaded, universe, {"EURUSD": [eur], "GBPUSD": [gbp]}), loaded, universe)
    assert [(item.detector, item.kind) for item in report.contamination_findings] == [("PRIMARY_LINEAGE", "LINEAGE_ID")]
    assert report.gate_failures == ("CROSS_PAIR_CONTAMINATION",)


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
