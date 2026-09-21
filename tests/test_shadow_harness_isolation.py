"""Per-symbol isolation and cross-pair contamination for the offline shadow harness."""

from __future__ import annotations

from tests.shadow_harness_helpers import (
    broker_dry_run,
    bundle,
    candidate,
    evaluate,
    lineage,
    load_real,
    natural_chain,
    risk_dry_run,
    tradeplan,
)
from tools.shadow_harness.captures import ShadowCaptureBundle
from tools.shadow_harness.isolation import (
    IsolationFinding,
    detect_cross_pair_contamination,
    validate_symbol_isolation,
)


def _codes(findings: tuple[IsolationFinding, ...]) -> list[str]:
    return sorted(item.code for item in findings)


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


def test_lineage_id_borrowed_from_another_pair_is_isolation_and_contamination() -> None:
    loaded, universe = load_real()
    stolen = candidate("GBPUSD")
    stolen["lineage"] = stolen["lineage"] | {"thesis_id": lineage("EURUSD", 1)["thesis_id"]}
    report = evaluate(bundle(loaded, universe, {"EURUSD": [candidate("EURUSD")], "GBPUSD": [stolen]}), loaded, universe)
    codes = _codes(report.isolation_findings)
    assert codes == ["LINEAGE_SCOPE_VIOLATION", "LINEAGE_SCOPE_VIOLATION"]
    assert report.acceptance.cross_pair_contamination == 1
    finding = report.contamination_findings[0]
    assert finding.kind == "LINEAGE_ID"
    assert finding.symbols == ("EURUSD", "GBPUSD")
    assert not report.gate_passed


def test_price_vector_reused_under_another_pair_is_contamination_after_normalisation() -> None:
    loaded, universe = load_real()
    eur = natural_chain("EURUSD", universe)
    gbp = natural_chain("GBPUSD", universe)
    copied = [dict(point) for point in eur[2]["prices"]]
    copied[0]["value"] = copied[0]["value"] + "0"  # 1.1xxxx0 == 1.1xxxx
    gbp[2] = gbp[2] | {"prices": copied}
    report = evaluate(bundle(loaded, universe, {"EURUSD": eur, "GBPUSD": gbp}), loaded, universe)
    kinds = [item.kind for item in report.contamination_findings]
    assert kinds == ["PRICE_VECTOR"]
    assert report.acceptance.cross_pair_contamination == 1
    assert report.isolation_findings == ()


def test_evidence_digest_and_id_reuse_across_pairs_is_contamination() -> None:
    loaded, universe = load_real()
    eur = candidate("EURUSD")
    gbp = candidate("GBPUSD", evidence_sha256=eur["evidence_sha256"], candidate_id=eur["candidate_id"])
    report = evaluate(bundle(loaded, universe, {"EURUSD": [eur], "GBPUSD": [gbp]}), loaded, universe)
    assert sorted(item.kind for item in report.contamination_findings) == ["EVIDENCE_ID", "EVIDENCE_SHA256"]
    assert report.acceptance.cross_pair_contamination == 2


def test_record_filed_under_wrong_symbol_key() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"EURUSD": [candidate("GBPUSD")]}), loaded, universe)
    assert _codes(report.isolation_findings) == ["SYMBOL_KEY_MISMATCH"]
    assert "ISOLATION_VIOLATION" in report.gate_failures
    eur = next(item for item in report.symbols if item.symbol == "EURUSD")
    assert eur.status == "WAIT"  # a foreign record never counts as this pair's candidate


def test_unknown_symbol_key_is_isolation_violation_and_not_thirty() -> None:
    loaded, universe = load_real()
    report = evaluate(bundle(loaded, universe, {"BTCUSD": [candidate("BTCUSD")]}), loaded, universe)
    assert "UNKNOWN_SYMBOL_KEY" in _codes(report.isolation_findings)
    assert report.acceptance.pair_30_evaluated is False


def test_broker_symbol_must_match_frozen_map() -> None:
    loaded, universe = load_real()
    chain = natural_chain("XAUUSD", universe)
    chain[3] = chain[3] | {"broker_symbol": "XAUUSD"}
    report = evaluate(bundle(loaded, universe, {"XAUUSD": chain}), loaded, universe)
    assert _codes(report.isolation_findings) == ["BROKER_SYMBOL_MISMATCH"]


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
