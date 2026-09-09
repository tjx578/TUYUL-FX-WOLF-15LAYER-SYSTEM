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
