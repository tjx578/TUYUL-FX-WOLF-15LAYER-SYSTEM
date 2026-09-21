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


def test_ratification_approves_every_entry_and_activates_nothing():
    record = _record()
    assert record["status"] == "APPROVED_PER_ENTRY"
    assert (record["grants_runtime_activation"], record["dual_authority"]) == (False, False)
    assert record["runtime_activation"] == "EXPLICIT_ONLY"
    assert all(e["approval"] == "APPROVED" and e["runtime_activation"] == "EXPLICIT_ONLY" for e in record["entries"])
    # Only defined specs are approved; undefined routes have nothing to approve. No route is switched on.
    assert {r["route"]: r["approval"] for r in record["route_policies"]} == {
        "BREAK_RETEST": "APPROVED",
        "BREAKOUT_ACCEPTANCE": "APPROVED",
        "PULLBACK_CONTINUATION": "NOT_DEFINED",
        "FAILED_BREAKOUT_SELL": "NOT_DEFINED",
        "FAILED_BREAKDOWN_BUY": "NOT_DEFINED",
        "RANGE_FADE": "NOT_DEFINED",
    }
    assert {r["runtime_status"] for r in record["route_policies"]} == {"RUNTIME_DISABLED"}
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
    assert "a replacement is derived in the same re-evaluation" in text
    assert "transaction, the old box is `SUPERSEDED`, not `INVALIDATED`." in text
    assert "`SUPERSEDED` and `INVALIDATED` are terminal" in text
    assert "`EXPIRED` stays `RESERVED_UNREACHABLE_UNTIL_AUTHORITY_DEFINED`" in text


def _route(name: str) -> dict:
    (route,) = [r for r in _record()["route_policies"] if r["route"] == name]
    return route


def test_route_policies_match_the_record_and_read_no_m1_for_bounds():
    document = _document()
    for route in _record()["route_policies"]:
        if route["spec_status"] != "SPEC_DEFINED":
            assert route["bounds"] is None and "building_prerequisites" not in route
            continue
        assert f"`{route['route']}` · box policy `{route['box_policy_id']}` v1\n" in document
        assert f"freeze_reason            : {route['freeze_reason']}" in document
    assert "BUY  box                 : box_low = canon(C.low), box_high = canon(L)" in document
    assert "BUY  box                 : box_low = canon(L),      box_high = canon(C.low)" in document
    assert "SELL box                 : box_low = canon(C.high), box_high = canon(L)" in document
    assert "M15 (break, completion, freeze). M1: evidence only." in document
    assert _route("BREAK_RETEST")["bounds"] == {"BUY": ["C.low", "L"], "SELL": ["L", "C.high"]}
    assert _route("BREAKOUT_ACCEPTANCE")["bounds"] == {"BUY": ["L", "C.low"], "SELL": ["C.high", "L"]}


def test_the_successor_pins_the_predecessor_draft_and_records_content_decisions():
    review = _record()["content_review"]
    assert review["predecessor_draft_sha256"] == "c9243308158f738fb643b6a84c9ebb325cb1a7edceee869512ef9dfbb93f6dfb"
    assert review["predecessor_draft_blob_id"] == "ae26705c8a2ae23dc4297922b3efdb6fd3d1c478"
    assert review["content_status"] == "APPROVED_WITH_AMENDMENTS_PENDING_BYTE_RATIFICATION"
    assert review["entries_content_approved_with_clarification"] == ["A3-09"]
    assert sorted(review["entries_content_approved"] + review["entries_content_approved_with_clarification"]) == [
        f"A3-{i:02d}" for i in range(1, 11)
    ]
    assert review["routes_spec_approved"] == ["BREAK_RETEST", "BREAKOUT_ACCEPTANCE"]
    document = _document()
    assert review["predecessor_draft_sha256"] in document
    # The content-review pin survives ratification as history of how the ratified bytes were produced.
    assert "pinned in\n`content_review`" in document


def test_the_approved_document_is_the_provable_successor_of_the_ratified_bytes():
    """Ratification changes approval metadata only; sections 1–3 stay byte-identical to what the owner verified."""

    record = _record()
    ratification = record["ratification"]
    assert ratification["ratified_draft_sha256"] == "76f9cad5f6309afd1de03afba8eed9152637c7d1c44164df06bb6a7ae356008a"
    assert ratification["ratified_draft_blob_id"] == "176cd41958a0b6111fdcb7224d41bfbc71d81756"
    assert ratification["ratified_by"] == "OWNER"
    assert ratification["approved_entries"] == [f"A3-{i:02d}" for i in range(1, 11)]
    assert ratification["approved_route_specs"] == ["BREAK_RETEST", "BREAKOUT_ACCEPTANCE"]
    assert "PR #509 head c39f63f1 CI 40/40 + Security Gate PASS" in ratification["method"]
    # Computed from blob 176cd419; the approved successor must reproduce it byte for byte.
    assert ratification["ratified_normative_span_sha256"] == (
        "377365b8a83f434d13933b6700d8c8c07043ffcd56f28a0df479f191dd0f4b42"
    )
    raw = (ROOT / record["document"]["path"]).read_bytes()
    span = raw[raw.index(b"## 1. Why A3 is separate") : raw.index(b"## 4. Approval")]
    assert hashlib.sha256(span).hexdigest() == ratification["ratified_normative_span_sha256"]
    document = _document()
    assert "**Ratified 2026-09-22.**" in document
    assert "ratified_draft_sha256: 76f9cad5f6309afd1de03afba8eed9152637c7d1c44164df06bb6a7ae356008a" in document
    assert "Only approval metadata changed" in document


def test_q_r1_building_and_frozen_may_share_one_authoritative_close():
    document = _document()
    assert "BUILDING has no minimum dwell time." in document
    assert "the transition is ordered and its\n                     event ordering is deterministic." in document
    assert "No artificial extra candle is required." in document
    common = _route("BREAK_RETEST")
    assert (common["same_close_building_to_frozen"], common["minimum_building_dwell"]) == (True, None)


def test_q_r2_the_acceptance_box_needs_a_strict_accepted_side_and_has_no_fallback():
    guard = _route("BREAKOUT_ACCEPTANCE")["acceptance_side_guard"]
    assert guard == {"BUY": "C.low > L", "SELL": "C.high < L", "on_failure": "NO_CANONICAL_BOX"}
    assert _route("BREAK_RETEST")["acceptance_side_guard"] is None
    document = _document()
    assert "acceptance_side_guard    : BUY requires C.low > L · SELL requires C.high < L (strict" in document
    assert "**If the acceptance-side guard fails, A3-R2 MUST NOT FREEZE A BOX.**" in document
    assert "There is no fallback to `[C.low, C.high]`" in document
    assert "The full acceptance candle range `[C.low, C.high]` is **not** the box." in document


def test_q_r3_post_freeze_invalidation_is_a_strict_close_beyond_l_and_never_a_stop_loss():
    invalidation = _route("BREAK_RETEST")["post_freeze_invalidation"]
    assert invalidation == {
        "BUY": "M15_CLOSE_BELOW_L",
        "SELL": "M15_CLOSE_ABOVE_L",
        "close_equal_to_L": "NOT_INVALIDATED",
    }
    assert _route("BREAK_RETEST")["invalidation_is_stop_loss"] is False
    document = _document()
    assert "BUY  : after FROZEN, an authoritative closed M15 candle with close < L invalidates" in document
    assert "SELL : after FROZEN, an authoritative closed M15 candle with close > L invalidates" in document
    assert "close == L does not invalidate" in document
    assert "**Box invalidation ≠ broker stop ≠ risk SL ≠ order stop level.**" in document


def test_q_r4_failed_reclaim_stays_unmapped_without_fallback():
    assert _record()["resolved_questions"]["Q-R4"] == "FAILED_RECLAIM_UNMAPPED"
    text = _entry("A3-04")
    assert "**It stays UNMAPPED (Q-R4):**" in text
    assert "There is no fallback `FAILED_RECLAIM → BREAK_RETEST` and no implicit" in text


def test_q_r5_pressure_range_authority_gates_the_box_and_never_the_target():
    for name in ("BREAK_RETEST", "BREAKOUT_ACCEPTANCE"):
        assert "PRESSURE_RANGE_STRUCTURAL_AUTHORITY_TRUE" in _route(name)["building_prerequisites"]
    document = _document()
    assert "PressureRange.structural_authority == true\n" in document
    assert "is an ExecutionBox formation prerequisite, not a StructuralTarget\n  predicate." in document
    assert "Target eligibility stays exactly A2-05's six predicates." in document
    assert "**no canonical BUILDING box**, with no downgrade and no fallback to M1." in document


def test_a3_08_and_a3_09_carry_the_owner_locks():
    text = _entry("A3-08")
    assert "box_version starts at 1 and increments by exactly +1; no skipped versions; append-only" in text
    assert "route or policy changed                                   → new execution_box_id, box_version = 1" in text
    text = _entry("A3-09")
    assert "freeze_evidence_id (canonical identity of the closed candle that satisfied the FROZEN predicate)" in text
    assert "**AUTHORITY_MATERIAL is material for revision semantics**" in text
    assert "LINEAGE is never\n    hashed merely because an id changed" in text


def test_content_approved_sections_carry_no_proposed_label():
    """An approved normative section that still says "proposed" contradicts its own status (owner, 2026-09-22)."""

    review = _record()["content_review"]
    assert review["label_cleanup_predecessor_sha256"] == (
        "b69781ebec098689ae920a8e37abed7eefd682023aa8ce8bc1e487680f65c20f"
    )
    assert review["label_cleanup_predecessor_blob_id"] == "e9dba29f1c5ea77503c3685118e91a341bb5056d"
    assert review["label_cleanup_scope"] == "FOUR_STALE_PROPOSED_LABELS_ONLY"
    approved = review["entries_content_approved"] + review["entries_content_approved_with_clarification"]
    for entry_id in approved:
        assert "propos" not in _entry(entry_id).lower(), entry_id
    document = _document()
    route_section = document[document.index("## 3. Route policies") : document.index("## 4. Approval")]
    assert "propos" not in route_section.lower()
    assert "### A3-10 · GAP_FILL · SUPERSEDED vs INVALIDATED\n" in document


def test_every_question_is_resolved_and_none_left_open():
    record = _record()
    assert "open_questions" not in record
    assert sorted(record["resolved_questions"]) == ["Q-R1", "Q-R2", "Q-R3", "Q-R4", "Q-R5"]
    document = _document()
    for question in record["resolved_questions"]:
        assert f"\n{question}  CLOSED" in document, question
    assert "not chosen here" not in document
