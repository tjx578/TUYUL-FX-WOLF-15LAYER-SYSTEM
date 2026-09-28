"""Build the WOLF15 V31 G6 SOURCE_CANDIDATE manifest (v2) as separate evidence bound to one frozen commit.

Every value is read from git objects of the given revision (``git cat-file``), never from a working tree, so the
frozen candidate branch is never touched and a CRLF checkout cannot change a hash. Lane heads are pinned and must be
ancestors of the candidate. Runtime values that are not measured stay ``NOT_MEASURED``; gates that have not run
stay ``NOT_EXECUTED``.

Usage: python candidate_manifest.py <repo> <candidate_sha> <out.json>
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
CANDIDATE = sys.argv[2]
OUT = Path(sys.argv[3])

FROZEN_SOURCE_CANDIDATE_SHA = "1eb88680bf05ee1456ebb08acb8214e392ca2ac3"
AUTHORITY = {
    "SSOT_sha256": "docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md",
    "A1_sha256": "docs/governance/strategy-5scr-v3.1-amendment-A1.md",
    "A2_sha256": "docs/governance/strategy-5scr-v3.1-amendment-A2.md",
    "A3_sha256": "docs/governance/strategy-5scr-v3.1-amendment-A3.md",
    "A4_sha256": "docs/governance/strategy-5scr-v3.1-amendment-A4.md",
    "R9_freeze_sha256": "docs/governance/r9-envelope-v1.md",
}
AUTHORITY_PIN_PREFIX = {
    "SSOT_sha256": "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902",
    "A1_sha256": "1fed7f7b",
    "A2_sha256": "9cf9e531",
    "A3_sha256": "538b3b6f",
    "A4_sha256": "357a55b0",
    "R9_freeze_sha256": "2a5826a3",
}
LANE_HEADS = {
    "main_base": ("2ea21786df62ea082907f6a8401a30816e15fadb", None),
    "structural_geometry_head": ("bd6cae9ac26a2d94fc4a37090157ef797307287e", 513),
    "g4_head": ("4b1039052585574545b10032e461d758b397d183", 516),
    "a4_record_head": ("68b74f212d1d37d498a8585e6f3465aecd9a6572", 511),
    "r9_envelope_head": ("26e038eba61a00fcdabeb3c50e0d7a426ef877a9", 517),
    "lane_e_head": ("267c07249d1fd06ecb3730995c9041becdbf5922", 514),
    "lane_f_head": ("8ab7b4ae43bdeb76e188675f35f0b327ae9a82ae", 515),
}
SOURCES = {
    "LANE_E_SHADOW_HARNESS_POLICY": "tools/shadow_harness/policy/shadow_harness_policy_v1.json",
    "LANE_E_MANIFEST": "tools/shadow_harness/manifest.py",
    "LANE_E_ISOLATION": "tools/shadow_harness/isolation.py",
    "LANE_E_EVALUATOR": "tools/shadow_harness/evaluator.py",
    "G4_CONTRACT": "contracts/strategy_5scr_broker_adaptation_v31.py",
    "G4_ADAPTER": "risk/strategy_5scr_broker_adaptation_v31.py",
    "A4_GEOMETRY_CONTRACT": "contracts/strategy_5scr_structural_geometry_v31.py",
    "A4_GEOMETRY": "analysis/strategy_5scr_structural_geometry_v31.py",
    "R9_CONTRACT": "contracts/r9_envelope_v1.py",
    "LANE_F_SIDE_LEDGER": "ops/demo_canary_verifier/side_ledger.py",
    "LANE_F_CHAIN": "ops/demo_canary_verifier/chain.py",
    "LANE_F_ENVELOPE": "ops/demo_canary_verifier/envelope.py",
}


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def blob_bytes(rev: str, path: str) -> tuple[str, bytes]:
    blob = git("rev-parse", f"{rev}:{path}").decode().strip()
    return blob, git("cat-file", "blob", blob)


def entry(rev: str, path: str) -> dict[str, object]:
    blob, data = blob_bytes(rev, path)
    return {"path": path, "git_blob": blob, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main() -> int:
    sha = git("rev-parse", f"{CANDIDATE}^{{commit}}").decode().strip()
    if sha != FROZEN_SOURCE_CANDIDATE_SHA:
        raise SystemExit(f"{sha} is not the frozen source candidate {FROZEN_SOURCE_CANDIDATE_SHA}")
    authority = {name: entry(sha, path) for name, path in AUTHORITY.items()}
    for name, pin in AUTHORITY_PIN_PREFIX.items():
        if not str(authority[name]["sha256"]).startswith(pin):
            raise SystemExit(f"{name} sha256 {authority[name]['sha256']} does not match pin {pin}")
    for name, (head, _) in LANE_HEADS.items():
        if subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", head, sha]).returncode != 0:
            raise SystemExit(f"{name} {head} is not an ancestor of {sha}")
    policy = json.loads(blob_bytes(sha, SOURCES["LANE_E_SHADOW_HARNESS_POLICY"])[1])
    manifest = {
        "schema_version": "wolf15.v31-g6.source-candidate-manifest.v2",
        "evidence_kind": "SEPARATE_EVIDENCE_NOT_PART_OF_CANDIDATE_SOURCE",
        "source_candidate_sha": sha,
        "candidate_git_sha": sha,
        "candidate_tree_digest": git("rev-parse", f"{sha}^{{tree}}").decode().strip(),
        "candidate_branch": "wolf15-v31-demo-candidate",
        "source_candidate_freeze": {
            "status": "FROZEN",
            "by": "owner",
            "date": "2026-09-28",
            "ci_evidence": "PR #518 (draft) head == source_candidate_sha; 48/48 checks SUCCESS incl. Security Gate",
        },
        **{name: value["sha256"] for name, value in authority.items()},
        "authority_documents": authority,
        "r9_envelope_frozen_schema_sha256": "10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2",
        "r9_envelope_frozen_normative_span_sha256": "c9663fa7a752baa8f8723ef0241980d7fc9a55938ff480dc5703564e4e31b96f",
        "lane_heads": {name: {"git_sha": head, "pr": pr} for name, (head, pr) in LANE_HEADS.items()},
        "lane_e_policy": {
            "policy_version": policy.get("policy_version"),
            "account_snapshot_binding_fields_exempt_from_cross_pair_reuse": policy.get(
                "account_snapshot_binding_fields_exempt_from_cross_pair_reuse"
            ),
        },
        "g4_policy": {"minimum_net_rr": "1.5", "policy_instance": "SUPPLIED_AT_EVALUATION_NOT_PINNED_IN_SOURCE"},
        "owner_decisions_in_source": ["D1", "D2", "D3-A", "D3-B", "D3-C"],
        "sources": {name: entry(sha, path) for name, path in SOURCES.items()},
        "EA_EX5_SHA256": "NOT_MEASURED",
        "EA_PRESET_SHA256": "NOT_MEASURED",
        "DEMO_ACCOUNT_BINDING": "NOT_MEASURED",
        "RUNTIME_CANDIDATE_BINDING": "NOT_FROZEN",
        "R9_PASS": "NOT_EXECUTED",
        "NATURAL_30_PAIR_SHADOW": "NOT_EXECUTED",
        "G6_READY": False,
        "G6_READY_FOR_DEMO": False,
        "RUNTIME_WIRING": "NONE",
        "RUNTIME_ACTIVATION": "NONE",
        "COMMAND_ENQUEUE_ARM_ORDER": 0,
        "BROKER_EFFECT": 0,
    }
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    OUT.write_bytes(data)
    print(f"manifest {OUT.name} sha256={hashlib.sha256(data).hexdigest()} bytes={len(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
