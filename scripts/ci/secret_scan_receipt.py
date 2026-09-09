"""Capture scanner findings without publishing credential material.

Every finding still fails this gate. Review uses exact source-file and finding
hashes; an unverified result is not silently treated as a false positive.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def summarize_findings(output: str, root: Path) -> list[dict]:
    findings = []
    for line in output.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        metadata = row["SourceMetadata"]["Data"]["Filesystem"]
        path = Path(metadata["file"])
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        relative = path.relative_to(root.resolve()).as_posix()
        raw = row["Raw"]
        if not isinstance(raw, str) or not raw or not isinstance(row["DetectorName"], str):
            raise ValueError("INVALID_SCANNER_FINDING")
        findings.append(
            {
                "path": relative,
                "line": metadata.get("line"),
                "detector": row["DetectorName"],
                "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "source_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "disposition": "REVIEW_REQUIRED",
            }
        )
    return findings


def main():
    root = Path.cwd()
    receipt = {"accepted": False, "scope": "SOURCE_SECRET_DETECTION_NO_CREDENTIAL_VALIDATION", "findings": []}
    try:
        receipt["source_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        result = subprocess.run(
            [
                "trufflehog",
                "filesystem",
                ".",
                "--no-update",
                "--no-verification",
                "--json",
                "--fail",
                "--exclude-paths=.github/trufflehog-exclude.txt",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        receipt["scanner_exit"] = result.returncode
        receipt["findings"] = summarize_findings(result.stdout, root)
        receipt["accepted"] = result.returncode == 0 and not receipt["findings"]
        if result.returncode not in (0, 183):
            receipt["failure_class"] = "SCANNER_PROCESS_FAILURE"
        # Neither stdout nor stderr is written: both may contain secrets.
    except Exception as exc:
        receipt["failure_class"] = type(exc).__name__
    target = root / "artifacts/secret-scan/receipt.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"accepted": receipt["accepted"], "findings": len(receipt["findings"])}))
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
