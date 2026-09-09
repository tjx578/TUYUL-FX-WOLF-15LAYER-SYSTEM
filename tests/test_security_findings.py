import json
import subprocess
import sys
from pathlib import Path

from scripts.ci.security_findings import classify, digest


def fixture(tmp_path: Path):
    path = tmp_path / "fixture.txt"
    path.write_bytes(b"synthetic fixture\n")
    row = {
        "DetectorName": "Synthetic",
        "Raw": "synthetic",
        "Verified": False,
        "SourceMetadata": {"Data": {"Filesystem": {"file": "fixture.txt", "line": 1}}},
    }
    manifest = {
        "findings": [
            {
                "file": "fixture.txt",
                "detector": "Synthetic",
                "raw_sha256": digest(b"synthetic"),
                "file_sha256_lf": digest(path.read_bytes()),
            }
        ]
    }
    return row, manifest


def test_exact_reviewed_fingerprint_passes(tmp_path):
    row, manifest = fixture(tmp_path)
    assert not classify([row], manifest, tmp_path)["unresolved"]


def test_changed_value_detector_and_verified_result_fail(tmp_path):
    row, manifest = fixture(tmp_path)
    for field, value in [("Raw", "different"), ("DetectorName", "Other"), ("Verified", True)]:
        assert classify([{**row, field: value}], manifest, tmp_path)["unresolved"]


def test_changed_file_fails(tmp_path):
    row, manifest = fixture(tmp_path)
    (tmp_path / "fixture.txt").write_text("new credential added")
    assert classify([row], manifest, tmp_path)["unresolved"]


def test_paths_outside_root_fail(tmp_path):
    row, manifest = fixture(tmp_path)
    row["SourceMetadata"]["Data"]["Filesystem"]["file"] = "../fixture.txt"
    assert classify([row], manifest, tmp_path)["unresolved"]


def test_cli_preserves_scanner_error_and_malformed_output(tmp_path):
    raw = tmp_path / "raw.jsonl"
    manifest = tmp_path / "review.json"
    manifest.write_text(json.dumps({"findings": []}))
    raw.write_text("sensitive-malformed-input")
    for status in (1, 183, 0):
        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci/security_findings.py",
                str(raw),
                "--manifest",
                str(manifest),
                "--scanner-exit",
                str(status),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "sensitive-malformed-input" not in result.stdout + result.stderr


def test_cli_rejects_findings_exit_with_empty_output(tmp_path):
    raw = tmp_path / "raw.jsonl"
    manifest = tmp_path / "review.json"
    raw.write_text("")
    manifest.write_text(json.dumps({"findings": []}))
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci/security_findings.py",
            str(raw),
            "--manifest",
            str(manifest),
            "--scanner-exit",
            "183",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
