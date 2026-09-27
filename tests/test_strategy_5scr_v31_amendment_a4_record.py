"""v3.1-A4 Structural Geometry amendment (DRAFT): hash pinning, isolation from A1–A3, and the owner locks most
easily eroded (OD-1 … OD-16)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "docs" / "governance"
RECORD = GOV / "strategy-5scr-v3.1-amendment-A4.json"
PRIOR = {key: GOV / f"strategy-5scr-v3.1-amendment-{key}.json" for key in ("A1", "A2", "A3")}
REQUIRED_FIELDS = {
    "entry_id",
    "owner_decision",
    "amendment_type",
    "source_pr",
    "base_documents",
    "base_clause",
    "base_behavior",
    "amended_behavior",
    "reason",
    "shadow_required",
    "replay_required",
    "oos_required",
    "runtime_activation",
    "approval",
}


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def _document() -> str:
    return (ROOT / _record()["document"]["path"]).read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(entry_id: str) -> str:
    document = _document()
    start = document.index(f"### {entry_id} ·")
    body = document.index("\n", start) + 1
    following = re.search(r"^#{2,3} ", document[body:], re.M)
    return document[start : body + following.start()] if following else document[start:]


def _record_entry(entry_id: str) -> dict:
    (entry,) = [e for e in _record()["entries"] if e["entry_id"] == entry_id]
    return entry


def _flags(entry_id: str) -> tuple[bool, bool, bool]:
    entry = _record_entry(entry_id)
    return entry["shadow_required"], entry["replay_required"], entry["oos_required"]


def test_amendment_document_is_byte_pinned():
    record = _record()
    assert _sha256(ROOT / record["document"]["path"]) == record["document"]["sha256"]


def test_base_documents_are_unmodified_and_pinned():
    record = _record()
    base = record["base_ssot"]
    assert base["sha256"] == "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"
    assert _sha256(ROOT / base["path"]) == base["sha256"]
    assert base["document_bytes_modified"] is False
    companion = record["companion_authority"]
    assert companion["sha256"] == "4420a32f981f18e9fcd9f0cd3f8aa22362216baf4fff241ab4d6700bbee2b172"
    assert (companion["location"], companion["document_bytes_modified"]) == ("OUTSIDE_REPOSITORY", False)
    assert companion["sha256"] in _document()


def test_a4_builds_on_the_exact_approved_a1_a2_a3_bytes():
    builds_on = _record()["builds_on"]
    document = _document()
    for key, record_path in PRIOR.items():
        prior = json.loads(record_path.read_text(encoding="utf-8"))
        assert builds_on[key]["sha256"] == prior["document"]["sha256"] == _sha256(ROOT / prior["document"]["path"])
        assert f"{key}: {{sha256: {builds_on[key]['sha256']}" in document
    assert builds_on["A1"]["entries_used"] == []
    assert builds_on["A2"]["entries_used"] == ["A2-01", "A2-02", "A2-05", "A2-07"]
    assert builds_on["A3"]["entries_used"] == ["A3-05", "A3-07", "A3-08", "A3-09", "A3-10", "A3-R1", "A3-R2"]


def test_draft_approves_nothing_and_activates_nothing():
    record = _record()
    assert record["status"] == "DRAFT_NOT_APPROVED"
    assert (record["grants_runtime_activation"], record["dual_authority"]) == (False, False)
    assert record["runtime_activation"] == "EXPLICIT_ONLY"
    assert "ratification" not in record
    assert all(e["approval"] == "PENDING" and e["runtime_activation"] == "EXPLICIT_ONLY" for e in record["entries"])
    assert {p["approval"] for p in record["geometry_policies"]} == {"PENDING"}
    assert {p["runtime_status"] for p in record["geometry_policies"]} == {"RUNTIME_DISABLED"}
    document = _document()
    assert "status: DRAFT_NOT_APPROVED\n" in document
    assert "**Not approved.**" in document
    assert "A4 APPROVED  ≠  StructuralGeometryV31 implementation authorized" in document
    assert "A4 APPROVED  ≠  any route RUNTIME_ELIGIBLE" in document
    assert "A4 APPROVED  ≠  net RR, broker adaptation or order type decided" in document
    assert "**Specification approval is not runtime approval.**" in document


def test_every_entry_is_complete_typed_and_maps_one_owner_decision():
    entries = _record()["entries"]
    assert [e["entry_id"] for e in entries] == [f"A4-{i:02d}" for i in range(1, 17)]
    assert [e["owner_decision"] for e in entries] == [f"OD-{i}" for i in range(1, 17)]
    assert _record()["content_source"]["decisions"] == [f"OD-{i}" for i in range(1, 17)]
    document = _document()
    for entry in entries:
        assert set(entry) == REQUIRED_FIELDS, entry["entry_id"]
        assert entry["amendment_type"] in {"CONFLICT_OVERRIDE", "GAP_FILL"}
        assert set(entry["base_documents"]) <= {"SSOT_V3_1", "AUDIT_REPLAY_V3"} and entry["base_documents"]
        assert entry["base_clause"] and all(re.fullmatch(r"§\d+(\.\d+)*", c) for c in entry["base_clause"])
        heading = f"### {entry['entry_id']} · {entry['amendment_type']}"
        assert heading in document
        assert f"- **Owner decision:** {entry['owner_decision']}." in _entry(entry["entry_id"])
        flags = (entry["shadow_required"], entry["replay_required"], entry["oos_required"])
        expected = " · ".join(
            f"**{name}_required:** {str(value).lower()}"
            for name, value in zip(("shadow", "replay", "oos"), flags, strict=True)
        )
        assert expected in _entry(entry["entry_id"]), entry["entry_id"]
    overrides = {e["entry_id"] for e in entries if e["amendment_type"] == "CONFLICT_OVERRIDE"}
    assert overrides == {"A4-04", "A4-07"}


def test_a4_never_touches_a1_a2_or_a3():
    record = _record()
    assert record["scope"] == "STRUCTURAL_GEOMETRY_ONLY"
    prior = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in PRIOR.items()}
    ids = {e["entry_id"] for e in record["entries"]}
    assert ids.isdisjoint({e["entry_id"] for p in prior.values() for e in p["entries"]})
    # A1-07 (thesis actionability) stays pending: A4-12 explicitly refuses to ratify it.
    assert all(e["approval"] == "PENDING" for e in prior["A1"]["entries"] if e["entry_id"] <= "A1-08")
    assert all(e["approval"] == "APPROVED" for e in prior["A2"]["entries"] + prior["A3"]["entries"])
    assert prior["A3"]["status"] == "APPROVED_PER_ENTRY"


def test_out_of_scope_items_stay_out():
    assert _record()["out_of_scope"] == [
        "ORDER_TYPE",
        "ORDER_PRICE",
        "BROKER_ADAPTATION",
        "COST_MODEL",
        "NET_RR",
        "ECONOMIC_MINIMUM_DISTANCE",
        "BROKER_SL_TRIGGER",
        "THESIS_INVALIDATION_A1_07",
        "RISK",
        "EXECUTION_COMMAND",
        "CHILD_CAMPAIGN",
    ]
    assert "Out of scope, and not decided anywhere in A4: order type, actual order price, broker adaptation" in (
        _document()
    )


def test_a4_01_sl_anchor_is_the_reference_candle_extreme_and_needs_full_evidence():
    text = _entry("A4-01")
    assert "BUY  : structural_sl_anchor = canon(R.low)" in text
    assert "SELL : structural_sl_anchor = canon(R.high)" in text
    assert "R    = the canonical M15 reference candle of the ordered structural proof" in text
    assert "canon = A3-05 canonicalization (Decimal(str(x)) into Price; reject, never round)" in text
    assert "This is a **new A4 policy**, not a claim that the SSOT already fixed this level." in text
    assert _flags("A4-01") == (True, True, True)
    for p in _record()["geometry_policies"]:
        assert p["structural_sl_anchor"] == {"BUY": "R.low", "SELL": "R.high"}


def test_a4_02_no_strategy_buffer_and_the_sl_is_never_moved():
    text = _entry("A4-02")
    assert "structural_sl = structural_sl_anchor\n" in text
    assert "carries buffer = NONE" in text
    assert "Forbidden inside A4 geometry: ±1 tick · ±N pip · ATR · spread multiple · metal $ offset." in text
    assert "may later **reject** the canonical SL; it may never move it silently." in text
    assert _flags("A4-02") == (True, True, True)
    assert {p["sl_buffer"] for p in _record()["geometry_policies"]} == {None}


def test_a4_03_gross_rr_has_no_minimum_and_net_stays_downstream():
    text = _entry("A4-03")
    assert "gross_rr_minimum  = NONE" in text
    assert "minimum_net_rr    = 1.5 (existing SSOT §17.3 authority, unchanged)" in text
    assert "net_rr            = computed AFTER broker/cost adaptation, never by A4" in text
    assert "A historical gross threshold of 2.0 is `LEGACY / NOT_CANONICAL_AUTHORITY`." in text
    assert "A4 creates no gross threshold." in text
    for p in _record()["geometry_policies"]:
        assert (p["gross_rr_minimum"], p["net_rr_status"]) == (None, "NET_RR_NOT_EVALUATED")


def test_a4_04_no_target_floor_and_no_farther_target():
    text = _entry("A4-04")
    assert "10-pip floor = NONE" in text
    assert "Not part of A4: FX minimum target 10 pip · metal $5 floor · any instrument minimum reward floor." in text
    assert "it belongs to G4 / broker-execution feasibility, never to target" in text
    assert "a failing setup is rejected, never re-targeted to a farther target." in text
    assert _flags("A4-04") == (True, True, True)


def test_a4_05_worst_case_rr_reference_is_not_an_order():
    text = _entry("A4-05")
    assert "A4 does **not** choose an order type." in text
    assert "BUY  rr_reference_entry = box_high" in text
    assert "SELL rr_reference_entry = box_low" in text
    assert "It is **not** an actual order price, a market order, a limit order or a stop order." in text
    assert "Order type and order price\n  belong to G4." in text


def test_a4_06_entry_interval_has_no_identity_of_its_own():
    text = _entry("A4-06")
    assert "entry interval identity = (execution_box_id, box_version)" in text
    assert "No `entry_interval_id` is created." in text


def test_a4_07_broker_facts_stay_in_g4_and_nothing_is_quantized():
    text = _entry("A4-07")
    assert "A4 / Strategy : canonical Decimal entry interval · canonical SL · canonical TP1 · gross RR" in text
    for fact in ("bid/ask", "spread", "drift", "tick size", "tick value", "stops level", "freeze level",
                 "order price", "volume", "margin"):  # fmt: skip
        assert fact in text[text.index("G4 / Broker") :], fact
    assert "`broker_constraint_interval` is not evaluated in A4." in text
    assert "**no tick-size quantization in A4.**" in text


def test_a4_08_a4_reads_no_cost_inputs():
    text = _entry("A4-08")
    assert "A4 must not read live spread · commission · swap · slippage" in text
    assert "net RR authority belongs to downstream Broker/Cost Adaptation." in text


def test_a4_09_tp1_is_the_target_price_without_offset():
    text = _entry("A4-09")
    assert "TP1 = selected StructuralTarget.price" in text
    assert "Forbidden: TP1 ± ticks · TP1 ± spread · TP1 haircut · farther target selection." in text
    assert "TP1 is never moved." in text
    for p in _record()["geometry_policies"]:
        assert (p["tp1"], p["tp1_offset"]) == ("SELECTED_TARGET_PRICE", None)


def test_a4_10_revision_domains_are_separate_and_a_target_change_never_bumps_the_box():
    text = _entry("A4-10")
    assert "ExecutionBox revision  ≠  StructuralGeometry revision  ≠  TradePlanCandidate revision" in text
    assert "No new logical `structural_geometry_id` is created" in text
    assert "It\n  does **not** force `box_version` to increment." in text
    assert "never mutated\n  retroactively." in text
    assert _record()["geometry_material"] == [
        "execution_box_id",
        "box_version",
        "structural_sl_anchor",
        "structural_sl",
        "target_id",
        "tp1",
        "rr_reference_entry",
        "geometry_policy_id",
        "geometry_policy_version",
    ]
    assert "`gross_rr` is derived from the projection and is not an extra material field." in text


def test_a4_11_gross_rr_is_exact_and_requires_positive_risk_and_reward():
    text = _entry("A4-11")
    assert "BUY  : risk = rr_reference_entry − structural_sl   reward = TP1 − rr_reference_entry" in text
    assert "SELL : risk = structural_sl − rr_reference_entry   reward = rr_reference_entry − TP1" in text
    assert "gross_rr = reward / risk" in text
    assert "required : risk > 0 and reward > 0, otherwise ROUTE_NO_VALID_ENTRY_DOMAIN" in text
    assert "no binary\n  float, no quantum, no rounding mode." in text


def test_a4_12_a1_07_is_not_ratified_and_the_three_invalidations_stay_apart():
    text = _entry("A4-12")
    assert "A4 does **not** ratify A1-07" in text
    assert "box invalidation  ≠  thesis invalidation  ≠  broker SL trigger" in text
    assert "close == L\n  does not invalidate" in text


def test_a4_13_reason_vocabulary_is_closed_and_names_nothing_a4_did_not_evaluate():
    codes = _record()["reason_codes"]
    text = _entry("A4-13")
    block = re.search(r"```text\n(.*?)```", text, re.S)
    assert block is not None
    assert block.group(1).split() == codes
    assert "Net RR status carried downstream: `NET_RR_NOT_EVALUATED`." in text
    assert "A4 never emits `RR_FAIL`, `RR_BELOW_MINIMUM`," in text
    for forbidden in ("RR_FAIL", "RR_BELOW_MINIMUM", "COST_FLOOR_FAILED", "TARGET_BELOW_EXECUTION_FLOOR"):
        assert forbidden not in codes


def test_a4_14_policy_registry_has_no_default_and_no_env_selection():
    text = _entry("A4-14")
    assert "selection by environment variable is\n  forbidden." in text
    assert "Unknown policy: reject\n  (`GEOMETRY_POLICY_UNKNOWN`)." in text
    assert "**There is no default policy.**" in text
    policies = _record()["geometry_policies"]
    assert [(p["route"], p["geometry_policy_id"], p["box_policy_id"]) for p in policies] == [
        ("BREAK_RETEST", "5scr.geometry-policy.break-retest", "5scr.box-policy.break-retest"),
        ("BREAKOUT_ACCEPTANCE", "5scr.geometry-policy.breakout-acceptance", "5scr.box-policy.breakout-acceptance"),
    ]
    a3_policies = {
        r["route"]: r["box_policy_id"]
        for r in json.loads(PRIOR["A3"].read_text(encoding="utf-8"))["route_policies"]
        if r["box_policy_id"]
    }
    assert {p["route"]: p["box_policy_id"] for p in policies} == a3_policies


def test_a4_15_handoff_binds_one_exact_revision_and_never_rebinds_a_reservation():
    text = _entry("A4-15")
    assert "resulting geometry material changed          → new TradePlanCandidate revision" in text
    assert "every handoff references an exact TradePlanCandidate\n  revision." in text
    assert "An old risk reservation is never silently rebound to a new revision." in text


def test_a4_16_separate_artifact_that_opens_no_trading():
    text = _entry("A4-16")
    assert "not an extension of A3" in text
    assert "only after owner ratification on exact bytes" in text
    assert "A4 approval alone opens no trading." in text


def test_geometry_policies_match_the_record_and_the_a3_boxes():
    document = _document()
    for p in _record()["geometry_policies"]:
        assert f"`{p['route']}` · geometry policy `{p['geometry_policy_id']}` v1\n" in document
    assert "BUY             : entry_interval [canon(C.low), canon(L)] · rr_reference canon(L)" in document
    assert "BUY             : entry_interval [canon(L), canon(C.low)] · rr_reference canon(C.low)" in document
    assert "SELL            : entry_interval [canon(C.high), canon(L)] · rr_reference canon(C.high)" in document
    references = {p["route"]: p["rr_reference_entry"] for p in _record()["geometry_policies"]}
    assert references == {
        "BREAK_RETEST": {"BUY": "L", "SELL": "L"},
        "BREAKOUT_ACCEPTANCE": {"BUY": "C.low", "SELL": "C.high"},
    }
    assert "The other four A3 routes have no box policy and therefore no geometry policy." in document


def test_open_questions_stay_open_and_are_not_silently_decided():
    record = _record()
    assert record["open_questions"] == ["Q-A4-1", "Q-A4-2", "Q-A4-3", "Q-A4-4"]
    document = _document()
    for question in record["open_questions"]:
        assert f"\n{question}  OPEN" in document, question
    assert "A4 adds no rule" in document
