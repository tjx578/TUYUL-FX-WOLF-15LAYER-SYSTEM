import hashlib
import json

import pytest

from scripts.ci.secret_scan_receipt import summarize_findings


def test_findings_preserve_source_binding_without_exposing_raw(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text("fixture source")
    row = {
        "SourceMetadata": {"Data": {"Filesystem": {"file": str(path), "line": 1}}},
        "DetectorName": "FixtureDetector",
        "Raw": "fixture-secret-never-print",
        "ExtraData": {"password": "also-never-print"},
        "Verified": False,
    }
    result = summarize_findings(json.dumps(row), tmp_path)
    assert len(result) == 1
    assert result[0]["disposition"] == "REVIEW_REQUIRED"
    assert result[0]["source_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "never-print" not in json.dumps(result)


@pytest.mark.parametrize("output", ["not json", "{}", '{"Raw": "x"}'])
def test_malformed_scanner_output_is_not_a_clean_scan(tmp_path, output):
    with pytest.raises((ValueError, KeyError)):
        summarize_findings(output, tmp_path)


def test_external_source_path_is_rejected(tmp_path):
    row = {
        "SourceMetadata": {"Data": {"Filesystem": {"file": "../outside.py"}}},
        "DetectorName": "FixtureDetector",
        "Raw": "fixture",
    }
    with pytest.raises(ValueError):
        summarize_findings(json.dumps(row), tmp_path)


def test_review_is_bound_to_both_source_bytes_and_detected_value(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text("reviewed fixture source")
    row = {
        "SourceMetadata": {"Data": {"Filesystem": {"file": str(path), "line": 1}}},
        "DetectorName": "FixtureDetector",
        "Raw": "reviewed dummy",
    }
    original = summarize_findings(json.dumps(row), tmp_path)[0]
    reviewed = ({**original, "reason": "explicit dummy fixture"},)
    assert summarize_findings(json.dumps(row), tmp_path, reviewed)[0]["disposition"] == "REVIEWED_EXACT_BYTES"
    row["Raw"] = "different credential"
    assert summarize_findings(json.dumps(row), tmp_path, reviewed)[0]["disposition"] == "REVIEW_REQUIRED"
    row["Raw"] = "reviewed dummy"
    path.write_text("changed fixture source")
    assert summarize_findings(json.dumps(row), tmp_path, reviewed)[0]["disposition"] == "REVIEW_REQUIRED"


def test_verified_finding_cannot_use_reviewed_exception(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text("reviewed dummy source")
    row = {
        "SourceMetadata": {"Data": {"Filesystem": {"file": str(path)}}},
        "DetectorName": "FixtureDetector",
        "Raw": "reviewed dummy",
        "Verified": False,
    }
    original = summarize_findings(json.dumps(row), tmp_path)[0]
    reviewed = ({**original, "reason": "explicit dummy fixture"},)
    row["Verified"] = True
    assert summarize_findings(json.dumps(row), tmp_path, reviewed)[0]["disposition"] == "REVIEW_REQUIRED"


def test_review_hash_normalizes_checkout_line_endings(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_bytes(b"reviewed dummy source\n")
    row = {
        "SourceMetadata": {"Data": {"Filesystem": {"file": str(path)}}},
        "DetectorName": "FixtureDetector",
        "Raw": "reviewed dummy",
    }
    original = summarize_findings(json.dumps(row), tmp_path)[0]
    reviewed = ({**original, "reason": "explicit dummy fixture"},)
    path.write_bytes(b"reviewed dummy source\r\n")
    assert summarize_findings(json.dumps(row), tmp_path, reviewed)[0]["disposition"] == "REVIEWED_EXACT_BYTES"
