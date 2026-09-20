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


def test_amendment_document_is_byte_pinned():
    record = _record()
    assert _sha256(ROOT / record["document"]["path"]) == record["document"]["sha256"]


def test_base_ssot_is_unmodified_and_named_explicitly():
    base = _record()["base_ssot"]
    assert base["sha256"] == "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"
    assert _sha256(ROOT / base["path"]) == base["sha256"]
    assert base["document_bytes_modified"] is False


def test_record_grants_no_runtime_activation_and_no_dual_authority():
    record = _record()
    assert record["status"] == "DRAFT_NOT_APPROVED"
    assert (record["grants_runtime_activation"], record["dual_authority"]) == (False, False)
    assert record["effective_authority_model"] == "BASE_SSOT_PLUS_EXPLICIT_AMENDMENTS"
    assert all(entry["runtime_activation"] == "EXPLICIT_ONLY" for entry in record["entries"])
    assert all(entry["approval"] == "PENDING" for entry in record["entries"])


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
    for klass in ("MATERIAL_RANGE_CHANGE", "COVERAGE_CHANGE", "EVIDENCE_REFRESH"):
        assert klass in document
    assert "Coverage may change while `low` and `high` are identical." in document
    assert "deferred to G7/12C" in document
    assert "INTENTIONALLY NOT CREATED" in document  # G8: no material hash is invented
    assert "The range itself never holds authority in any state." in document
