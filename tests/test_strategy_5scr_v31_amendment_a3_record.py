"""v3.1-A3 ExecutionBox amendment (DRAFT): hash pinning, isolation from A1/A2, and the rules most easily eroded."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "docs" / "governance"
RECORD = GOV / "strategy-5scr-v3.1-amendment-A3.json"
A1_RECORD = GOV / "strategy-5scr-v3.1-amendment-A1.json"
A2_RECORD = GOV / "strategy-5scr-v3.1-amendment-A2.json"
REQUIRED_FIELDS = {
    "entry_id",
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
ROUTES = (
    "BREAK_RETEST",
    "BREAKOUT_ACCEPTANCE",
    "PULLBACK_CONTINUATION",
    "FAILED_BREAKOUT_SELL",
    "FAILED_BREAKDOWN_BUY",
    "RANGE_FADE",
)


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def _document() -> str:
    return (ROOT / _record()["document"]["path"]).read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(entry_id: str) -> str:
    document = _document()
    start = document.index(f"### {entry_id} ·")
    body = document.index("\n", start) + 1  # search for the next heading after this heading's own line
    following = re.search(r"^#{2,3} ", document[body:], re.M)
    return document[start : body + following.start()] if following else document[start:]


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


def test_a3_builds_on_the_exact_ratified_a1_and_a2_bytes():
    builds_on = _record()["builds_on"]
    for key, record_path in (("A1", A1_RECORD), ("A2", A2_RECORD)):
        pinned = json.loads(record_path.read_text(encoding="utf-8"))["document"]["sha256"]
        assert (
            builds_on[key]["sha256"]
            == pinned
            == _sha256(ROOT / json.loads(record_path.read_text())["document"]["path"])
        )
    assert builds_on["A2"]["entries_used"] == ["A2-01", "A2-07"]


def test_the_draft_grants_no_approval_and_no_runtime_activation():
    record = _record()
    assert record["status"] == "DRAFT_NOT_APPROVED"
    assert (record["grants_runtime_activation"], record["dual_authority"]) == (False, False)
    assert record["runtime_activation"] == "EXPLICIT_ONLY"
    assert all(e["approval"] == "PENDING" and e["runtime_activation"] == "EXPLICIT_ONLY" for e in record["entries"])
    assert all(r["approval"] == "PENDING" for r in record["route_policies"])
    document = _document()
    assert "A3 APPROVED  ≠  ExecutionBoxV31 implementation authorized" in document
    assert "A3 APPROVED  ≠  any route RUNTIME_ELIGIBLE" in document
    assert "**Specification approval is not runtime approval.**" in document


def test_every_entry_is_complete_typed_and_cites_its_base_documents():
    entries = _record()["entries"]
    assert [e["entry_id"] for e in entries] == [f"A3-{i:02d}" for i in range(1, 11)]
    document = _document()
    for entry in entries:
        assert set(entry) == REQUIRED_FIELDS, entry["entry_id"]
        assert entry["amendment_type"] in {"CONFLICT_OVERRIDE", "GAP_FILL"}
        assert set(entry["base_documents"]) <= {"SSOT_V3_1", "AUDIT_REPLAY_V3"} and entry["base_documents"]
        assert entry["base_clause"] and all(re.fullmatch(r"§\d+(\.\d+)*", c) for c in entry["base_clause"])
        assert f"### {entry['entry_id']} · {entry['amendment_type']}" in document


def test_a3_never_touches_a1_or_a2():
    record = _record()
    assert record["scope"] == "EXECUTION_BOX_ONLY"
    a1 = json.loads(A1_RECORD.read_text(encoding="utf-8"))
    a2 = json.loads(A2_RECORD.read_text(encoding="utf-8"))
    ids = {e["entry_id"] for e in record["entries"]}
    assert ids.isdisjoint({e["entry_id"] for e in a1["entries"] + a2["entries"]})
    assert all(e["approval"] == "PENDING" for e in a1["entries"] if e["entry_id"] <= "A1-08")
    assert all(e["approval"] == "APPROVED" for e in a2["entries"])


def test_out_of_scope_items_stay_out():
    assert _record()["out_of_scope"] == [
        "CONSUMED_TRIGGER",
        "EXPIRED_TRIGGER",
        "STRUCTURAL_SL",
        "TP1",
        "RR",
        "T10",
        "BROKER",
        "RISK",
        "EXECUTION_COMMAND",
        "CHILD_CAMPAIGN",
    ]


def test_a3_01_target_first_also_overrides_the_audit_workflow_ordering():
    (entry,) = [e for e in _record()["entries"] if e["entry_id"] == "A3-01"]
    assert (entry["amendment_type"], entry["base_documents"]) == ("CONFLICT_OVERRIDE", ["AUDIT_REPLAY_V3", "SSOT_V3_1"])
    text = _entry("A3-01")
    assert "A2-01's precedence applies to Audit/Replay v3 as well" in text
    assert "**SSOT §17.1 controls**" in text
    assert "`RouteEvaluation` is not moved." in text


def test_a3_02_m1_is_evidence_and_never_freeze_authority():
    text = _entry("A3-02")
    assert "M1/tick MUST NOT independently:" in text
    assert "create a canonical ExecutionBox · freeze a canonical ExecutionBox · determine route policy" in text
    assert (
        "**Freeze authority = an approved route policy (A3-03) + the closed-candle authority that policy names.**"
        in text
    )
    assert "Evidence is not authority." in text


def test_a3_03_an_incomplete_route_policy_produces_no_canonical_box():
    text = _entry("A3-03")
    fields = re.search(r"```text\n(.*?)```", text, re.S)
    assert fields is not None
    names = [line.split()[0] for line in fields.group(1).splitlines() if line.strip()]
    assert names == [
        "route",
        "box_policy_id,",
        "eligible_proof_forms",
        "closed_candle_authority",
        "source_evidence_requirements",
        "building_predicate",
        "box_low_derivation,",
        "frozen_predicate,",
        "invalidation_basis",
        "future_evidence_prohibition",
    ]
    assert "`NOT_CANONICALLY_IMPLEMENTABLE`, and a route without a canonical" in text
    # The list must stay a prohibition: naming the fallbacks is worthless if the sentence flips to allowing them.
    assert "There is no fallback to M1, to `ExecutionBoxV1`," in text
    for fallback in ("to M1", "to `ExecutionBoxV1`", 'the v2 "first M15 after the', "any generic interval"):
        assert fallback in text, fallback
    assert "an implementer may not choose it" in text


def test_a3_04_route_vocabulary_is_closed_and_nothing_is_switched_on():
    routes = _record()["route_policies"]
    assert tuple(r["route"] for r in routes) == ROUTES
    assert {r["runtime_status"] for r in routes} == {"RUNTIME_DISABLED"}
    assert {r["evidence_status"] for r in routes} == {"EVIDENCE_PENDING"}
    defined = {r["route"] for r in routes if r["spec_status"] == "SPEC_DEFINED"}
    assert defined == {"BREAK_RETEST", "BREAKOUT_ACCEPTANCE"}
    assert all(r["box_policy_id"] is None for r in routes if r["route"] not in defined)
    assert "FAILED_RECLAIM" not in {r["route"] for r in routes}
    text = _entry("A3-04")
    assert "`FAILED_RECLAIM` is a completion kind of the CONTINUATION proof, **not** a route." in text
    assert "**A3 approval turns no route on.**" in text
    for entry_id in ("A3-03", "A3-04"):
        (entry,) = [e for e in _record()["entries"] if e["entry_id"] == entry_id]
        assert (entry["shadow_required"], entry["replay_required"], entry["oos_required"]) == (True, True, True)


def test_a3_05_box_bounds_are_canonical_decimal_and_never_float():
    text = _entry("A3-05")
    assert "**No new precision is introduced for the box.**" in text
    assert "`Decimal(str(value))`" in text
    assert "rejected, never rounded or quantized" in text
    assert "`1.1000` and `1.1` hash identically" in text
    for forbidden in (
        "float arithmetic feeding `material_box_hash`",
        "float equality deciding a box version",
        "`tick_size`",
    ):
        assert forbidden in text, forbidden


def test_a3_06_a_pressure_range_change_alone_never_versions_the_box():
    text = _entry("A3-06")
    assert "→ box derivation re-evaluation is REQUIRED" in text
    assert "→ does NOT force a box_version increment" in text
    assert "`pressure_range_id` is carried as a lineage input, never as a material field by itself." in text


def test_a3_07_target_facts_are_obligations_never_states():
    text = _entry("A3-07")
    for fact, required in (
        ("TARGET_UNCHANGED", "false"),
        ("TARGET_MATERIAL_CHANGE", "true"),
        ("TARGET_NO_LONGER_ELIGIBLE", "true"),
        ("TARGET_INVALIDATED", "true"),
    ):
        assert f"| `{fact}` | {required} |" in text, fact
    assert "`resulting_box_state` is **never** mapped from a target fact." in text


def test_a3_08_logical_identity_excludes_every_revision_driver():
    text = _entry("A3-08")
    assert "[box_derivation_version, strategy_thesis_id, route, box_policy_id, box_policy_version]" in text
    assert "box revision     = (execution_box_id, box_version)" in text
    for outside in (
        "`pressure_range_id`",
        "`target_id`",
        "the ordered-proof revision",
        "admission class",
        "every clock",
    ):
        assert outside in text, outside
    assert "creates a **new** `execution_box_id`" in text
    assert "Versions are contiguous (no skipped numbers), append-only, never" in text


def test_a3_09_target_and_range_are_lineage_and_never_hashed():
    text = _entry("A3-09")
    assert "GEOMETRY_MATERIAL  : box_low, box_high (canonical Price, A3-05)" in text
    assert "material_box_hash = canonical_sha256_v31(GEOMETRY_MATERIAL ∪ AUTHORITY_MATERIAL)" in text
    lineage = text[text.index("LINEAGE (not hashed)") : text.index("NON_MATERIAL")]
    assert "pressure_range_id" in lineage and "target_id" in lineage
    non_material = text[text.index("NON_MATERIAL") :]
    for field in ("broker quote", "reference price", "box_version itself", "telemetry count"):
        assert field in non_material, field
    assert "**`target_id` is LINEAGE, not material.**" in text


def test_a3_10_a_concurrent_replacement_supersedes_rather_than_invalidates():
    text = _entry("A3-10")
    assert "SUPERSEDED  = a valid successor exists" in text
    assert "INVALIDATED = the box's basis is lost and NO valid successor exists" in text
    assert "the\n    old box is `SUPERSEDED`, not `INVALIDATED`." in text
    assert "`SUPERSEDED` and `INVALIDATED` are terminal" in text
    assert "`EXPIRED` stays `RESERVED_UNREACHABLE_UNTIL_AUTHORITY_DEFINED`" in text


def test_route_drafts_match_the_record_and_read_no_m1_for_bounds():
    document = _document()
    for route in _record()["route_policies"]:
        if route["spec_status"] != "SPEC_DEFINED":
            continue
        assert f"`{route['route']}` · box policy `{route['box_policy_id']}` v1 (proposed)" in document
        assert f"freeze_reason            : {route['freeze_reason']}" in document
    assert "BUY  box                 : box_low = canon(C.low), box_high = canon(L)" in document
    assert "BUY  box                 : box_low = canon(L),      box_high = canon(C.low)" in document
    assert "M15 (break, completion, freeze). M1: evidence only." in document


def test_open_questions_are_recorded_not_decided():
    record = _record()
    assert record["open_questions"] == ["Q-R1", "Q-R2", "Q-R3", "Q-R4", "Q-R5"]
    document = _document()
    for question in record["open_questions"]:
        assert f"\n{question}  " in document, question
    assert "(strategy content — not chosen here)" in document
