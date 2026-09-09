#!/usr/bin/env python3
"""Validate the portable planning bundle; never run WOLF15 or authorize trading.

Usage: python tools/validate_pursuit_package.py [package_directory]
Standard library only. Output is JSON; exit 0 means DOCUMENT_PACKAGE_PASS.
It does not establish repository correctness, runtime acceptance, or permission.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    errors: list[str] = []
    checks: list[str] = []

    def check(condition: bool, label: str) -> None:
        (checks if condition else errors).append(label)

    def read(name: str):
        return json.loads((root / name).read_text(encoding="utf-8"))

    plan = read("WOLF15_PURSUIT_PLAN.json")
    with (root / "sources/canonical-backlog-41.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    canonical = [r["ID"] for r in rows]
    actions = plan["actions"]
    ids = [a["id"] for a in actions]
    by_id = {a["id"]: a for a in actions}
    check(len(canonical) == len(set(canonical)) == 41, "41 unique canonical source actions")
    check(len(ids) == len(set(ids)) == 54, "54 unique GOAP nodes")
    check(set(plan["canonical_action_ids"]) == set(canonical), "canonical IDs preserved")
    check(set(ids) == set(canonical) | {"G00"} | {f"K{i:02d}" for i in range(1, 13)}, "only G00 and 12 local slices supplement canonical actions")
    for milestone in (f"P{i}" for i in range(1, 7)):
        expected = {r["ID"] for r in rows if r["Milestone"] == milestone}
        check(set(plan["milestones"][milestone]) == expected, f"{milestone} canonical membership")
        check(bool(plan["milestone_extra_gates"].get(milestone)), f"{milestone} has explicit extra closure gates")
    goal_effects = {by_id[i]["effects"][0] for i in canonical}
    check(set(plan["goal_state"]) == goal_effects, "all canonical closure effects in goal")
    check(len(plan["goal_acceptance"]) == 6, "six milestone acceptance records")

    remaining = set(ids)
    ordered: list[str] = []
    while remaining:
        ready = sorted(i for i in remaining if set(by_id[i]["hard_dependencies"]) <= set(ordered))
        if not ready:
            break
        ordered.extend(ready)
        remaining.difference_update(ready)
    check(not remaining, "hard dependency graph is acyclic with known nodes")
    blockers = {b["predicate"] for b in plan["blockers"]}
    possible = set(plan["current_state"]) | blockers
    for action_id in ordered:
        a = by_id[action_id]
        check(set(a["preconditions"]) <= possible, f"{action_id}: prerequisite has a producer or explicit external blocker")
        possible.update(a["effects"])
        check(a["execution_status"] not in {"DONE", "COMPLETED", "PASS"}, f"{action_id}: planning does not claim execution")

    release_ids = {"D01", "E07", "D02", "N05", "J02", "J03"}
    for action_id in sorted(release_ids):
        a = by_id[action_id]
        check("C05" in a["hard_dependencies"] and "release.candidate_gates_bound" in a["preconditions"], f"{action_id}: governance and current release proof precede operation")
    check("authority.github_admin" not in by_id["C05"]["preconditions"], "governance no-op does not force admin mutation authority")
    check("governance.change_scope_resolved" in by_id["C05"]["preconditions"], "conditional governance mutation remains explicit")
    check(set(plan["predicate_binding_rules"]["release_actions"]) == release_ids, "release-specific predicate binding is declared")
    check(plan["execution_authority"] == "PLANNING_ONLY" and plan["plan_status"] == "PARTIAL_PLAN", "plan retains planning-only partial status")
    check(all(v is False for v in plan["authority_flags"].values()), "planning document has no external/trading grants")
    check(plan["no_readme_updates"] is True, "README preservation is explicit")
    check(plan["next_action"] == "G00", "fresh source discovery is first")

    gate_report = read("review/goap-validation.json")
    check(gate_report["status"] == "VALID" and not gate_report["errors"], "native GOAP validator passed")
    check(gate_report["plan_sha256"] == digest(root / "WOLF15_PURSUIT_PLAN.json"), "native GOAP report matches exact plan bytes")
    envelope = read("review/authority-envelope.json")
    audit_report = read("review/authority-validation.json")
    check(audit_report["status"] == "PASS" and not audit_report["errors"], "authority envelope validator passed")
    check(audit_report["input_sha256"] == digest(root / "review/authority-envelope.json"), "authority report matches exact envelope bytes")
    check(all(v is False for v in envelope["authority"]["controls"].values()), "authority controls remain false")
    for source in envelope["sources"]:
        path = (root / source["locator"]).resolve()
        check(path.is_relative_to(root) and path.is_file() and digest(path) == source["sha256"], f"audit source identity: {source['id']}")

    failures = read("WOLF15_FAILURE_PLAYBOOK.json")["cases"]
    check(len(failures) == len({c["id"] for c in failures}) == 48, "48 unique projected/reported failure cases")
    check(all(set(c["action_refs"]) <= set(canonical) for c in failures), "failure cases reference actual canonical actions")
    check(all(c["retry_trigger_and_exit_evidence"] and c["provenance"] for c in failures), "failure cases declare provenance and retry/exit condition")
    for name in ("WOLF15_BINDING_INPUTS.template.json", "WOLF15_GATE_RECEIPT.template.json"):
        check(read(name)["runtime_usable"] is False, f"{name}: non-executable template")

    # Check only authored Markdown links; archived originals preserve their bytes and provenance.
    authored = [p for p in root.glob("*.md")] + list((root / "review").glob("*.md"))
    link_count = 0
    for path in authored:
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", content):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            filename = target.split("#", 1)[0]
            if not filename:
                continue  # Fragment labels are presentation, not evidence binding.
            destination = (path.parent / filename).resolve()
            link_count += 1
            check(destination.is_relative_to(root) and destination.is_file(), f"local document link: {path.relative_to(root)} -> {filename}")

    manifest = read("PACKAGE_MANIFEST.json")
    declared: set[str] = set()
    for entry in manifest["files"]:
        rel = entry["path"]
        check(rel not in declared, f"unique manifest member: {rel}")
        declared.add(rel)
        path = (root / rel).resolve()
        safe = path.is_relative_to(root) and path.is_file()
        check(safe and digest(path) == entry["sha256"] and path.stat().st_size == entry["bytes"], f"manifest bytes: {rel}")
        check(path.name.lower() != "readme.md", f"no README deliverable: {rel}")
    expected = {
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
        and "work" not in p.relative_to(root).parts
        and "__pycache__" not in p.relative_to(root).parts
        and p.name != "PACKAGE_MANIFEST.json"
        and p.relative_to(root).as_posix() != "review/package-validation.json"
        and p.suffix != ".zip"
    }
    check(declared == expected, "manifest covers every shipped stable member")
    result = {
        "status": "DOCUMENT_PACKAGE_PASS" if not errors else "DOCUMENT_PACKAGE_FAIL",
        "scope": "Planning artifact structure, declared authority boundaries, links and byte identity only.",
        "runtime_or_engineering_acceptance": "NOT_EXECUTED",
        "program_status": "INCOMPLETE / HOLD (latest user-reported checkpoint)",
        "plan_status": plan["plan_status"],
        "canonical_actions": len(canonical), "goap_nodes": len(actions),
        "milestone_counts": dict(Counter(r["Milestone"] for r in rows)),
        "failure_cases": len(failures), "local_file_links_checked": link_count,
        "stable_manifest_files": len(declared), "checks_passed": len(checks),
        "plan_sha256": digest(root / "WOLF15_PURSUIT_PLAN.json"),
        "manifest_sha256": digest(root / "PACKAGE_MANIFEST.json"),
        "errors": errors,
        "limitations": [
            "Does not execute WOLF15, PostgreSQL migrations, CI, MT5 or broker operations.",
            "Does not validate live credentials, current repository HEAD, authorization or external resource availability.",
            "Not a cryptographic signature or a substitute for independent runtime evidence.",
            "The manifest excludes itself and this generated report to avoid circular hashes.",
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "DOCUMENT_PACKAGE_FAIL", "error": str(exc), "runtime_or_engineering_acceptance": "NOT_EXECUTED"}))
        raise SystemExit(1)
