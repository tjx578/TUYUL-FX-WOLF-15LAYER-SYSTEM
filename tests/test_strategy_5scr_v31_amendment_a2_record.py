"""v3.1-A2 Structural Target amendment: hash pinning, scope isolation and the rules most easily eroded."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "governance" / "strategy-5scr-v3.1-amendment-A2.json"
A1_RECORD = ROOT / "docs" / "governance" / "strategy-5scr-v3.1-amendment-A1.json"
REQUIRED_FIELDS = {
    "entry_id",
    "amendment_type",
    "source_pr",
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


def test_amendment_document_is_byte_pinned():
    record = _record()
    assert _sha256(ROOT / record["document"]["path"]) == record["document"]["sha256"]


def test_base_ssot_is_unmodified_and_named_explicitly():
    base = _record()["base_ssot"]
    assert base["sha256"] == "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"
    assert _sha256(ROOT / base["path"]) == base["sha256"]
    assert base["document_bytes_modified"] is False


def test_a2_approval_grants_no_runtime_activation():
    """Ratification of the authority is never runtime activation and never implementation authority."""

    record = _record()
    assert record["status"] == "APPROVED_PER_ENTRY"
    assert (record["grants_runtime_activation"], record["dual_authority"]) == (False, False)
    assert record["effective_authority_model"] == "BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS"
    assert all(entry["runtime_activation"] == "EXPLICIT_ONLY" for entry in record["entries"])
    # A2-07 is a draft: approving A2-01..A2-06 must never sweep it in.
    approval = {entry["entry_id"]: entry["approval"] for entry in record["entries"]}
    assert approval == {**{f"A2-0{i}": "APPROVED" for i in range(1, 7)}, "A2-07": "PENDING"}


def test_the_approved_document_is_the_provable_successor_of_the_ratified_bytes():
    ratification = _record()["ratification"]
    assert ratification["ratified_draft_sha256"] == ("4780c8989bfad0f6322ff3543774cc637f3e32c68d0e5747670fe18267608815")
    assert ratification["ratified_draft_blob_id"] == "d8433a126c689fea3ea6f859cddeacdd4a4ed1c9"
    assert ratification["ratified_by"] == "OWNER"
    assert ratification["approved_entries"] == ["A2-01", "A2-02", "A2-03", "A2-04", "A2-05", "A2-06"]
    document = _document()
    assert ratification["ratified_draft_sha256"] in document
    # Approving the authority does not open either implementation gate.
    assert "A2-01 APPROVED  ≠  StructuralTarget implementation authorized" in document
    assert "A2-01 APPROVED  ≠  ExecutionBox implementation authorized" in document
    assert "The 12B" in document and "implementation gate stays closed" in document


def test_every_entry_is_complete_typed_and_cites_base_clauses():
    entries = _record()["entries"]
    ids = [entry["entry_id"] for entry in entries]
    assert ids == ["A2-01", "A2-02", "A2-03", "A2-04", "A2-05", "A2-06", "A2-07"]
    document = _document()
    for entry in entries:
        assert set(entry) == REQUIRED_FIELDS, entry["entry_id"]
        assert entry["amendment_type"] in {"CONFLICT_OVERRIDE", "GAP_FILL"}
        assert entry["base_clause"] and all(re.fullmatch(r"§\d+[A-Z]?(\.\d+)*", c) for c in entry["base_clause"])
        assert all(isinstance(entry[flag], bool) for flag in ("shadow_required", "replay_required", "oos_required"))
        assert f"### {entry['entry_id']} · {entry['amendment_type']}" in document


def test_a2_is_scoped_to_structural_target_and_never_touches_a1():
    """The owner asked for a separate artifact so A1's pending conflict overrides stay isolated."""

    record = _record()
    assert record["scope"] == "STRUCTURAL_TARGET_ONLY"
    assert record["amendment_id"] == "WOLF15-5SCR-SSOT-V3.1-A2"
    a1 = json.loads(A1_RECORD.read_text(encoding="utf-8"))
    assert {e["entry_id"] for e in a1["entries"]} & {e["entry_id"] for e in record["entries"]} == set()
    # A1-01..A1-08 must still be PENDING; A2 may not move them.
    assert all(e["approval"] == "PENDING" for e in a1["entries"] if e["entry_id"] <= "A1-08")


def test_target_first_precedence_is_a_conflict_override_of_the_summary_ordering():
    (entry,) = [e for e in _record()["entries"] if e["entry_id"] == "A2-01"]
    assert entry["amendment_type"] == "CONFLICT_OVERRIDE"
    assert {"§5", "§17.1", "§28", "§16.1"} == set(entry["base_clause"])
    document = _document()
    assert "**Structural target selection precedes route-specific ExecutionBox materialization.**" in document
    assert "**`RouteEvaluation` is not moved.**" in document


def test_nearest_origin_excludes_every_forbidden_price_source():
    document = _document()
    assert "decision_price = the latest authoritative, non-future price observation" in document
    # The list must stay a prohibition: naming the sources is worthless if they become permitted.
    assert "**Forbidden as origin:** a live broker ask/bid" in document
    assert "Permitted as origin" not in document
    # Fragments must not span the document's line wraps, so each is kept short.
    for forbidden in ("live broker ask/bid", "future candle data", "an eventual fill price", "route-derived"):
        assert forbidden in document, forbidden
    assert "PRE-FILTER, not a tie-breaker" in document


def test_freshness_is_not_a_clock_and_introduces_no_threshold():
    document = _document()
    assert "A wall-clock TTL is **not** canonical" in document
    assert "**`NON_CANONICAL / ADVISORY_ONLY`**" in document
    assert "`freshness_status == FRESH`" in document
    assert "No universal threshold such as `tested_count <= N` is implied" in document
    assert "**Freshness is not consumption.**" in document


def test_consumption_is_market_truth_and_never_a_trade_lifecycle_event():
    document = _document()
    assert "Consumption is market-evidence truth" in document
    assert "**`ExecutionBox.CONSUMED` must not be imported.**" in document
    assert "**TEST ≠ CONSUME:**" in document
    # The liquidity FSM must not be generalised to the other seven sources.
    assert "authority for the **`LIQUIDITY` source only**" in document
    assert "**`NOT_DEFINED_BY_AUTHORITY`**" in document


def test_eligibility_is_six_predicates_and_nearest_is_applied_after_them():
    document = _document()
    for predicate in (
        "1. STRUCTURAL",
        "2. AUTHORITATIVE",
        "3. IN THESIS DIRECTION",
        "4. FRESH",
        "5. UNCONSUMED",
        "6. NOT PASSED AT decision_time",
    ):
        assert predicate in document, predicate
    assert "`nearest` is applied **after** all six filters, never as one of them." in document
    assert "Target selection never reads RR" in document


def test_tie_policy_freezes_only_what_the_existing_selector_already_proves():
    document = _document()
    assert "primary key   = minimum positive directional distance from decision_price" in document
    assert "secondary key = ascending target_id" in document
    # formed_at is excluded because it would smuggle in a market preference, not because it is unneeded.
    assert "**`formed_at` is EXCLUDED**" in document
    assert "older structure preferred" in document
    for excluded in (
        "TargetSource precedence",
        "formed_at precedence",
        "RR precedence",
        "timeframe precedence",
        "source-quality score",
    ):
        assert excluded in document, excluded
    # target_id resolves determinism only; if it is ever non-deterministic that is a separate identity gap.
    assert "**`target_id` carries no structural claim.**" in document
    assert "independent of deployment, request or worker randomness" in document
    assert "must not be patched by" in document  # a non-deterministic id is an identity gap, not a formed_at fix


def test_point_target_consumption_fixes_no_candle_field():
    """Owner correction 2026-09-21: completion is source-policy-bound, and wick/close/bid/ask stays open."""

    document = _document()
    assert "consumed_at = the first authoritative target-completion evidence" in document
    assert "**completion rule is source-policy-bound**" in document
    assert "deliberately fixes NO candle field as the completion criterion" in document
    for open_choice in ("a wick touch", "a close through the level", "a bid touch", "an ask touch"):
        assert open_choice in document, open_choice
    assert "a target has no completion rule and therefore cannot be consumed" in document


def test_the_a2_07_draft_leaves_the_ratified_entries_byte_identical():
    """Adding a draft entry must not touch one byte of the ratified A2-01..A2-06 text."""

    record = _record()
    draft = record["draft_revision"]
    assert draft["base_approved_document_sha256"] == (
        "9ca93cca0f10fb2de30e858f978b2b0b4908fda5ed9eb9d9ad597990fe6165e7"
    )
    assert draft["base_approved_blob_id"] == "cf07bd46b4b54edbc0f6fa6b69b6d5a99fd34184"
    assert draft["pending_entries"] == ["A2-07"]
    assert set(draft["pending_entries"]).isdisjoint(record["ratification"]["approved_entries"])
    raw = (ROOT / record["document"]["path"]).read_bytes()
    span = raw[raw.index("### A2-01 ·".encode()) : raw.index("### A2-07 ·".encode())]
    assert hashlib.sha256(span).hexdigest() == draft["approved_entries_span_sha256"]
    assert draft["approved_entries_span_sha256"] == ("cb82a987ac2b22f5c8da83348f11175676fdae92b63251bdbfc0590e2a88891f")
    assert "- **Status:** DRAFT — `PENDING`." in _document()


def _a2_07() -> str:
    document = _document()
    return document[document.index("### A2-07 ·") : document.index("## 3. Non-normative annex")]


def test_revision_facts_are_a_closed_vocabulary_with_frozen_precedence():
    (entry,) = [e for e in _record()["entries"] if e["entry_id"] == "A2-07"]
    assert (entry["amendment_type"], entry["approval"]) == ("GAP_FILL", "PENDING")
    assert set(entry["base_clause"]) == {"§15.1", "§21.6", "§17.2"}
    text = _a2_07()
    assert "(closed, exactly four values)" in text
    # The whole fenced block must be exactly the four values: a fifth value or a missing one fails.
    vocabulary = re.search(r"```text\n((?: *TARGET_\w+\n)+) *```", text)
    assert vocabulary and vocabulary.group(1).split() == [
        "TARGET_UNCHANGED",
        "TARGET_MATERIAL_CHANGE",
        "TARGET_INVALIDATED",
        "TARGET_NO_LONGER_ELIGIBLE",
    ]
    assert "TARGET_INVALIDATED  >  TARGET_NO_LONGER_ELIGIBLE  >  TARGET_MATERIAL_CHANGE  >  TARGET_UNCHANGED" in text
    assert "One classification reports exactly one value, the highest-semantic cause" in text
    assert "not independent flags" in text


def test_ineligibility_is_never_reported_as_invalidation():
    text = _a2_07()
    assert "explicitly invalidates the" in text and "structural invalidation only" in text
    assert "Staleness, consumption, being passed, a direction change or loss of authority is NOT" in text
    assert "target consumed                                            → TARGET_NO_LONGER_ELIGIBLE" in text
    assert "The target is not deleted historically" in text
    # All six A2-05 predicates stay the only eligibility surface the fact refers to.
    assert "still satisfies all six A2-05 predicates" in text


def test_a_new_nearer_target_is_a_material_change_not_silence():
    text = _a2_07()
    assert "A. same target_id, but canonical material relevant to geometry changed" in text
    assert "B. a different target_id is selected because the canonical eligible set or nearest solution changed" in text
    assert "nearer eligible target became authoritative                → TARGET_MATERIAL_CHANGE" in text


def test_revision_facts_never_encode_an_execution_box_reaction():
    text = _a2_07()
    assert "It must **not** encode any mapping from a target fact to an ExecutionBox FSM state" in text
    assert "is **12C authority** and is left `NOT_DEFINED` by A2" in text
    assert "It does **not** by itself revise any" in text
    # The forbidden mappings appear exactly once, inside the prohibition block, and nowhere as a rule.
    forbidden = text[text.index("All of the following are forbidden here:") :]
    for mapping in ("→ box_version++", "→ ExecutionBox.INVALIDATED", "→ SUPERSEDED"):
        assert text.count(mapping) == 1 and mapping in forbidden, mapping
    # §21.6 reason codes are not renamed or replaced.
    assert "it does not rename, replace or remove any reason code" in text


def test_a2_07_fixes_no_target_id_formula_and_no_material_field_list():
    text = _a2_07()
    assert "A2-07 fixes no `target_id` derivation formula and no list of material target fields." in text
    assert "uuid" not in text.lower() and "sha256(" not in text


def test_zone_runtime_semantics_are_not_active():
    document = _document()
    assert "`ZONE_TARGET_RUNTIME_SEMANTICS = NOT_ACTIVE`" in document
    assert "A near edge, a far edge or a midpoint must **never** be chosen" in document


def test_freshness_provenance_allows_equivalents_but_never_loses_the_semantics():
    document = _document()
    assert "**literal field names are not mandated**" in document
    assert "equivalent provenance already present in a contract is acceptable" in document
    assert "**No such provenance exists in the current contract**" in document


def test_the_annex_records_what_the_contract_does_not_have_yet():
    document = _document()
    assert "point-only" in document
    assert "**Freshness-policy provenance is missing.**" in document
    assert "**T10 deferred, not dropped.**" in document
    assert "Target selection stays RR-blind" in document
