"""Fail closed on scanner errors and findings outside reviewed exact fingerprints."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify(rows: list[dict], manifest: dict, root: Path) -> dict:
    allowed = manifest["findings"]
    accepted, unresolved = [], []
    for row in rows:
        location = row.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {})
        name = str(location.get("file", "")).replace("\\", "/")
        if name.startswith("./"):
            name = name[2:]
        safe = {"detector": row.get("DetectorName"), "file": name, "line": location.get("line")}
        path = (root / name).resolve()
        bound = path.is_relative_to(root.resolve()) and path.is_file()
        raw = row.get("Raw")
        match = False
        if bound and isinstance(raw, str) and raw and not row.get("Verified", False):
            file_hash = digest(path.read_bytes().replace(b"\r\n", b"\n"))
            match = any(
                entry["file"] == name
                and entry["detector"] == row.get("DetectorName")
                and entry["raw_sha256"] == digest(raw.encode())
                and entry["file_sha256_lf"] == file_hash
                for entry in allowed
            )
        (accepted if match else unresolved).append(safe)
    return {"reviewed_false_positives": accepted, "unresolved": unresolved}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--scanner-exit", type=int, required=True)
    args = parser.parse_args()
    # 183 is TruffleHog's documented findings exit; all other failures stay failures.
    if args.scanner_exit not in (0, 183):
        print(json.dumps({"status": "SCANNER_ERROR", "exit": args.scanner_exit}))
        return 2
    try:
        rows = [json.loads(line) for line in args.raw.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        result = classify(rows, json.loads(args.manifest.read_text()), args.root)
        if args.scanner_exit == 183 and not rows:
            raise ValueError("findings exit with empty output")
    except (OSError, ValueError, KeyError, TypeError):
        print('{"status":"INVALID_SCAN_DATA"}')
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 1 if result["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
