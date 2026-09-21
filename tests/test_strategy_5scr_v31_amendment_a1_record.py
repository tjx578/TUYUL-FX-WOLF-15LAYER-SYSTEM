"""v3.1-A1 amendment record: hash pinning, base SSOT immutability and entry completeness (L3, 2026-09-20)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "governance" / "strategy-5scr-v3.1-amendment-A1.json"
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fenced_lines_after(document: str, marker: str) -> list[str]:
    """The stripped, non-empty lines of the first fenced block that follows `marker`."""

    tail = document[document.index(marker) :]
    start = tail.index("```text\n") + len("```text\n")
    return [line.strip() for line in tail[start : tail.index("```", start)].splitlines() if line.strip()]


def test_amendment_document_is_byte_pinned():
    record = _record()
    assert _sha256(ROOT / record["document"]["path"]) == record["document"]["sha256"]


def test_base_ssot_is_unmodified_and_named_explicitly():
    base = _record()["base_ssot"]
    assert base["sha256"] == "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"
    assert _sha256(ROOT / base["path"]) == base["sha256"]
    assert base["document_bytes_modified"] is False


def test_record_grants_no_runtime_activation_and_no_dual_authority():
    """Ratification of the authority is never runtime activation, and never dual authority."""

    record = _record()
    assert record["status"] == "APPROVED_PER_ENTRY"
    assert (record["grants_runtime_activation"], record["dual_authority"]) == (False, False)
    assert record["effective_authority_model"] == "BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS"
    assert all(entry["runtime_activation"] == "EXPLICIT_ONLY" for entry in record["entries"])
    assert all(entry["approval"] in {"APPROVED", "PENDING"} for entry in record["entries"])


def test_every_entry_is_complete_typed_and_cites_base_clauses():
    entries = _record()["entries"]
    ids = [entry["entry_id"] for entry in entries]
    assert len(ids) == len(set(ids))
    document = (ROOT / _record()["document"]["path"]).read_text(encoding="utf-8")
    for entry in entries:
        assert set(entry) == REQUIRED_FIELDS, entry["entry_id"]
        assert entry["amendment_type"] in {"CONFLICT_OVERRIDE", "GAP_FILL"}
        assert entry["base_clause"] and all(re.fullmatch(r"§\d+[A-Z]?(\.\d+)*", c) for c in entry["base_clause"])
        assert all(isinstance(entry[flag], bool) for flag in ("shadow_required", "replay_required", "oos_required"))
        assert f"### {entry['entry_id']} · {entry['amendment_type']}" in document


def test_per_symbol_admission_is_recorded_as_a_conflict_override_of_the_global_block_fsm():
    (entry,) = [e for e in _record()["entries"] if e["source_pr"] == 492]
    assert entry["amendment_type"] == "CONFLICT_OVERRIDE"
    assert {"§7.2", "§7.3", "§24.3", "§27"} <= set(entry["base_clause"])
    assert (entry["shadow_required"], entry["replay_required"], entry["oos_required"]) == (True, True, True)


# --- PressureRange normative sections A1.1-A1.4 (entries A1-09..A1-12, 2026-09-21) -------------------------------


def _document() -> str:
    return (ROOT / _record()["document"]["path"]).read_text(encoding="utf-8")


def test_the_four_pressure_range_sections_are_registered_and_titled():
    """The owner asked for four normative sections. They are registered as entries so the machine record
    covers them, and each entry heading also carries its A1.x section title."""

    entries = {e["entry_id"]: e for e in _record()["entries"]}
    expected = {
        "A1-09": "A1.1 PressureRange material observation window",
        "A1-10": "A1.2 Material range derivation",
        "A1-11": "A1.3 Price coverage semantics",
        "A1-12": "A1.4 Change classification and downstream re-evaluation",
    }
    document = _document()
    for entry_id, title in expected.items():
        assert entry_id in entries, entry_id
        assert entries[entry_id]["amendment_type"] == "GAP_FILL"
        assert f"### {entry_id} · GAP_FILL · {title}" in document


def test_the_coverage_vocabulary_stays_closed_at_the_four_canonical_values():
    """Section 16.2 fixes four values. DEGRADED and UNAVAILABLE must appear only where the document forbids
    them, and STALE must stay on the observation and feed axes."""

    document = _document()
    for value in ("COMPLETE", "PARTIAL", "MISSING", "QUARANTINED"):
        assert value in document
    assert "`DEGRADED` and `UNAVAILABLE` must not be introduced" in document
    assert "must not be promoted into `price_coverage_status`" in document
    assert "No percentage threshold is introduced." in document


def test_change_classification_has_three_classes_and_grants_nothing_downstream_yet():
    """The two-class model misses the case where coverage moves while low/high are identical, so all three
    classes must be named; and the ExecutionBox consequence stays deferred to G7/12C."""

    document = _document()
    # Pin the definitions and their precedence, not merely the class names: a name-only check let the
    # COVERAGE_CHANGE definition line be deleted while every test stayed green (mutation v2, 2026-09-21).
    assert _fenced_lines_after(document, "three change classes over a normative field partition:")[:3] == [
        "GEOMETRY_MATERIAL : started_at, ended_at, coverage_anchor_rule, low, high",
        "COVERAGE          : price_coverage_status, coverage_gaps",
        "EVIDENCE          : source_price_ids, observed_through_utc",
    ]
    assert _fenced_lines_after(document, "Classification, highest precedence first:") == [
        "MATERIAL_RANGE_CHANGE = any GEOMETRY_MATERIAL field differs",
        "COVERAGE_CHANGE       = no GEOMETRY_MATERIAL difference AND any COVERAGE field differs",
        "EVIDENCE_REFRESH      = only EVIDENCE fields differ",
        "(no class)            = only NON_MATERIAL fields differ -> nothing is recorded (§15.2)",
    ]
    assert "Coverage may change while `low` and `high` are identical." in document
    assert "That case is `COVERAGE_CHANGE`, not\n    `EVIDENCE_REFRESH`" in document
    assert "deferred to G7/12C" in document
    assert "INTENTIONALLY NOT CREATED" in document  # G8: no material hash is invented
    assert "The range itself never holds authority in any state." in document


def test_the_owner_closure_decisions_are_normative_not_proposed():
    """Owner 2026-09-21: MarketEpisode close is the sole closure authority; neither lifecycle supersession nor
    raw-block termination closes the window; a closed canonical range never reopens."""

    document = _document()
    for fragment in (
        "**Closure authority (NORMATIVE, owner decision 2026-09-21):**",
        "**Lifecycle supersession does NOT close the window**",
        "**Raw-block termination alone does NOT close the window**",
        "**Reopening a closed canonical range: false**",
    ):
        assert fragment in document, fragment
    # Nothing in A1.1 may still be waiting on the owner.
    assert "OPEN-1" not in document and "OPEN-2" not in document
    assert "requires owner ratification" not in document


def test_evidence_cardinality_is_period_aligned_so_coverage_stays_computable():
    """G2/G6 consistency: coverage is evaluated per canonical period, so a flat list of raw tick ids would make
    coverage uncomputable from the record alone."""

    document = _document()
    for fragment in (
        "G2/G6 cardinality consistency",
        "`len(source_price_ids) == len(qualified set)`",
        "evidence never appears as a free list",
        "`tick:<id>` is therefore not a legal top-level",
        "**undecidable** coverage status and is rejected, never defaulted",
    ):
        assert fragment in document, fragment


def test_only_the_pressure_range_entries_are_approved_and_the_chain_is_provable():
    """The owner ratified the PressureRange sections on exact bytes. A1-01..A1-08 each declare shadow/replay/OOS
    evidence that does not exist, so they must not inherit approval - A1-01 is a CONFLICT_OVERRIDE of the v3.1
    global block FSM."""

    record = _record()
    approval = {e["entry_id"]: e["approval"] for e in record["entries"]}
    assert {k for k, v in approval.items() if v == "APPROVED"} == {"A1-09", "A1-10", "A1-11", "A1-12"}
    assert all(approval[f"A1-0{n}"] == "PENDING" for n in range(1, 9))
    for entry in record["entries"]:
        if entry["approval"] == "PENDING":
            assert entry["shadow_required"] or entry["replay_required"] or entry["oos_required"]

    # The approved document is the successor of the exact ratified bytes, and says so.
    ratification = record["ratification"]
    assert ratification["ratified_draft_sha256"] == ("5b23d8bb60ad03c6dbe00e55f393dbcae2758cfc99a516624b2809f22b1b26d4")
    assert ratification["ratified_draft_blob_id"] == "5c28c414a03f40070c1058cb6feb08fc50bbb0be"
    assert ratification["ratified_by"] == "OWNER"
    document = _document()
    assert ratification["ratified_draft_sha256"] in document
    assert "Implementation of `PressureRangeV1` requires a separate, explicit owner" in document
