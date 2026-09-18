"""Check repository contracts retained from the legacy manual CI workflow.

Diagnostics contain only rule identifiers, paths and line numbers. This check
never imports application modules, contacts services, or prints source values.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft7Validator, SchemaError

SCHEMAS = ("schemas/l12_schema.json", "schemas/alert_schema.json")
BOUNDARIES = {
    "dashboard": ("override_verdict", "force_execute", "bypass_gate", "skip_constitution", "ignore_l12"),
    "ea_interface": ("generate_verdict", "wolf_score", "should_trade", "analyze_market"),
    "execution": ("confluence",),
}
BUILD_ARTIFACTS = {".coverage", "coverage.xml", "final_results.txt"}
IGNORE = re.compile(r"#\s*pyright\s*:\s*ignore\b")
SPECIFIC_IGNORE = re.compile(r"\s*\[\s*report[A-Za-z0-9]+(?:\s*,\s*report[A-Za-z0-9]+)*\s*\]")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int = 0

    def diagnostic(self) -> str:
        return f"{self.rule}: {json.dumps(self.path, ensure_ascii=True)}:{self.line}"


def _tracked_files(root: Path) -> list[str]:
    completed = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    return [name for name in completed.stdout.decode("utf-8").split("\0") if name]


def check_repository(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    try:
        tracked = _tracked_files(root)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return [Finding("tracked-files-unavailable", ".")]
    if not tracked:
        return [Finding("tracked-files-empty", ".")]

    for directory in ("config", *BOUNDARIES):
        if not (root / directory).is_dir():
            findings.append(Finding("required-directory-missing", directory))

    for name in SCHEMAS:
        try:
            schema = json.loads((root / name).read_text(encoding="utf-8"))
            Draft7Validator.check_schema(schema)
        except (OSError, UnicodeError):
            findings.append(Finding("schema-unreadable", name))
        except (ValueError, SchemaError):
            findings.append(Finding("schema-invalid", name))

    for name in tracked:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            findings.append(Finding("tracked-path-invalid", "."))
            continue
        path = root / relative
        if relative.name in BUILD_ARTIFACTS:
            findings.append(Finding("committed-build-artifact", name))
        is_yaml = relative.parts[0] == "config" and relative.suffix.lower() in {".yaml", ".yml"}
        if relative.suffix != ".py" and not is_yaml:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(Finding("source-unreadable", name))
            continue
        if is_yaml:
            try:
                yaml.safe_load(source)
            except yaml.YAMLError:
                findings.append(Finding("config-yaml-invalid", name))
            continue
        try:
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type != tokenize.COMMENT:
                    continue
                for match in IGNORE.finditer(token.string):
                    if not SPECIFIC_IGNORE.match(token.string, match.end()):
                        findings.append(Finding("blanket-pyright-ignore", name, token.start[0]))
        except (tokenize.TokenError, SyntaxError):
            findings.append(Finding("python-tokenization-failed", name))
        forbidden = BOUNDARIES.get(relative.parts[0], ())
        for line, text in enumerate(source.splitlines(), 1):
            if any(pattern in text for pattern in forbidden):
                findings.append(Finding("layer-boundary-violation", name, line))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    findings = check_repository(args.root)
    for finding in findings:
        print(finding.diagnostic())
    if findings:
        print(f"Repository contracts failed: {len(findings)} finding(s).")
        return 1
    print("Repository contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
