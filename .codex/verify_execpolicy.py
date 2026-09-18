"""Native policy verification only: target commands are data, never executed."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def literal_rules(path: Path) -> list[dict]:
    result = []
    for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "prefix_rule"
            and not node.value.args
        ):
            raise ValueError("Candidate must contain only literal prefix_rule calls")
        rule = {kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords}
        if len(rule) != len(node.value.keywords) or rule.get("decision") != "prompt":
            raise ValueError("Candidate must explicitly keep prompt decisions")
        pattern = rule.get("pattern")
        if not (
            isinstance(pattern, list)
            and len(pattern) == 1
            and isinstance(pattern[0], list)
            and pattern[0]
            and all(isinstance(t, str) and t for t in pattern[0])
        ):
            raise ValueError("Candidate launcher patterns must have one literal union")
        if not rule.get("match") or not rule.get("not_match"):
            raise ValueError("Candidate must include positive and negative examples")
        result.append(rule)
    if not result:
        raise ValueError("Empty candidate")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True, help="Inspected native Codex executable")
    parser.add_argument(
        "--rules",
        type=Path,
        action="append",
        required=True,
        help="First file is the candidate; repeat for additional policy layers",
    )
    parser.add_argument("--baseline", type=Path, help="Optional old rules for coverage comparison")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary = args.codex.resolve(strict=True)
    rules = [p.resolve(strict=True) for p in args.rules]
    baseline_path = args.baseline.resolve(strict=True) if args.baseline else None
    output_path = args.output.resolve()
    protected = [binary, *rules, Path(__file__).resolve()]
    if baseline_path is not None:
        protected.append(baseline_path)
    if output_path in protected or (output_path.exists() and any(output_path.samefile(path) for path in protected)):
        raise ValueError("Output must not overwrite policy, baseline, executable or verifier")
    candidate = literal_rules(rules[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def invoke(paths: list[Path], argv: list[str], *, resolve: bool = False) -> dict:
        command = [str(binary), "execpolicy", "check"]
        for path in paths:
            command += ["--rules", str(path)]
        if resolve:
            command.append("--resolve-host-executables")
        command += ["--", *argv]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            shell=False,
        )
        if completed.returncode:
            return {"exit_code": completed.returncode, "decision": None, "matches": 0}
        output = json.loads(completed.stdout)
        return {
            "exit_code": 0,
            "decision": output.get("decision"),
            "matches": len(output.get("matchedRules", [])),
        }

    version = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    ).stdout.strip()
    tokens = sorted({t for rule in candidate for t in rule["pattern"][0]})
    cases = [[t, "--version"] for t in tokens]
    cases += [
        ["python", "-m", "pytest", "tests/test_signal_json_gate_adapter.py", "-v"],
        ["python", "-c", "print('policy-only')"],
        ["python", "-"],
        ["py", "-3", "-m", "pytest"],
        ["pytest", "--collect-only"],
        ["powershell.exe", "-NoProfile", "-Command", "Get-Date"],
        ["pwsh", "-Command", "Get-Location"],
        ["bash", "-lc", "git status --short"],
        ["cmd.exe", "/c", "echo policy-only"],
        ["railway", "variables", "--help"],
        ["railway.exe", "service", "--help"],
        ["railway.cmd", "status", "--json"],
        ["git", "stash", "list"],
        ["git.exe", "-C", ".", "status", "--short"],
        ["gh", "pr", "view", "484"],
        ["docker", "ps"],
        ["psql", "--version"],
        ["redis-cli", "--help"],
        ["uv", "run", "pytest"],
        ["pip", "install", "--help"],
        ["npm.cmd", "run", "lint"],
        ["npx", "--help"],
    ]
    checks = []
    for argv in cases:
        observed = invoke(rules, argv)
        checks.append(
            {
                "argv": argv,
                **observed,
                "passed": observed["exit_code"] == 0 and observed["decision"] == "prompt" and observed["matches"] > 0,
            }
        )
    for argv in [
        ["python-helper", "--version"],
        ["railway-helper", "--version"],
        ["unknown-runtime", "--version"],
        ["echo", "python"],
    ]:
        observed = invoke([rules[0]], argv)
        checks.append(
            {
                "argv": argv,
                **observed,
                "expected": "NO_MATCH",
                "passed": observed == {"exit_code": 0, "decision": None, "matches": 0},
            }
        )

    with tempfile.TemporaryDirectory(prefix="policy-fixtures-", dir=args.output.parent) as folder:
        allow = Path(folder) / "allow.rules"
        deny = Path(folder) / "forbidden.rules"
        malformed = Path(folder) / "invalid-inline.rules"
        allow.write_text(
            'prefix_rule(pattern=["python", "-m", "pytest"], decision="allow")\n',
            encoding="utf-8",
        )
        deny.write_text(
            'prefix_rule(pattern=["python", "-m", "pytest"], decision="forbidden")\n',
            encoding="utf-8",
        )
        malformed.write_text(
            'prefix_rule(pattern=["python"], decision="prompt", match=[["git", "status"]])\n',
            encoding="utf-8",
        )
        for paths, expected in [
            ([rules[0], allow], "prompt"),
            ([allow, rules[0]], "prompt"),
            ([rules[0], allow, deny], "forbidden"),
            ([deny, allow, rules[0]], "forbidden"),
        ]:
            observed = invoke(paths, ["python", "-m", "pytest"])
            checks.append(
                {
                    "case": "precedence",
                    "file_order": [p.name for p in paths],
                    **observed,
                    "expected": expected,
                    "passed": observed["exit_code"] == 0 and observed["decision"] == expected,
                }
            )
        invalid = invoke([malformed], ["python", "--version"])
        checks.append(
            {
                "case": "invalid_inline_example_rejected",
                **invalid,
                "passed": invalid["exit_code"] != 0,
            }
        )

    baseline = None
    if baseline_path is not None:
        old = literal_rules_baseline(baseline_path)
        old_tokens = {t for rule in old for t in rule["pattern"][0]}
        comparisons = []
        for token in tokens:
            observed = invoke([baseline_path], [token, "--version"])
            expected = "prompt" if token in old_tokens else None
            comparisons.append(
                {
                    "token": token,
                    **observed,
                    "expected": expected,
                    "passed": observed["exit_code"] == 0 and observed["decision"] == expected,
                }
            )
        baseline = {
            "sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "original_tokens_preserved": old_tokens <= set(tokens),
            "cases": comparisons,
        }

    observations = [
        {
            "argv": [sys.executable, "--version"],
            "resolve_host_executables": resolve,
            **invoke([rules[0]], [sys.executable, "--version"], resolve=resolve),
        }
        for resolve in (False, True)
    ]
    passed = all(c["passed"] for c in checks) and (
        baseline is None or (baseline["original_tokens_preserved"] and all(c["passed"] for c in baseline["cases"]))
    )
    report = {
        "codex_version": version,
        "codex_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "rules": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in rules],
        "launcher_count": len(tokens),
        "checks": checks,
        "baseline": baseline,
        "absolute_path_observations": observations,
        "passed": passed,
        "target_commands_executed": False,
        "effective_runtime_policy_verified": False,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": passed,
                "checks": len(checks),
                "baseline_cases": len(baseline["cases"]) if baseline else 0,
                "absolute_path_observations": observations,
                "report": str(args.output),
            }
        )
    )
    return 0 if passed else 1


def literal_rules_baseline(path: Path) -> list[dict]:
    # Parse literals without executing policy text in Python; native Codex remains the validator.
    output = []
    for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "prefix_rule"
            and not node.value.args
        ):
            raise ValueError("Unsupported baseline statement")
        output.append({kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords})
    return output


if __name__ == "__main__":
    raise SystemExit(main())
