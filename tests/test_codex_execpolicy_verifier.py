"""Protect policy inputs and the documented environment launcher contract."""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def verifier():
    path = ROOT / ".codex/verify_execpolicy.py"
    spec = importlib.util.spec_from_file_location("wolf15_execpolicy_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("target", ["baseline", "baseline_alias", "baseline_hardlink", "candidate", "binary", "script"])
def test_output_cannot_overwrite_inputs(verifier, tmp_path, monkeypatch, target):
    candidate = tmp_path / "candidate.rules"
    candidate.write_text(
        'prefix_rule(pattern=[["python"]], decision="prompt", match=[["python", "--version"]], not_match=[["rg", "--files"]])\n',
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.rules"
    baseline.write_text('prefix_rule(pattern=[["python"]], decision="prompt")\n', encoding="utf-8")
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"not an executable; must never be started")
    script = Path(verifier.__file__)
    originals = {p: p.read_bytes() for p in (candidate, baseline, binary, script)}
    targets = {"baseline": baseline, "candidate": candidate, "binary": binary, "script": script}
    (tmp_path / "nested").mkdir()
    targets["baseline_alias"] = tmp_path / "nested" / ".." / "baseline.rules"
    targets["baseline_hardlink"] = tmp_path / "baseline-alias.rules"
    os.link(baseline, targets["baseline_hardlink"])

    def forbidden_process(*args, **kwargs):
        raise AssertionError("Input/output collision must be rejected before starting Codex")

    monkeypatch.setattr(verifier.subprocess, "run", forbidden_process)
    monkeypatch.setattr(
        verifier.sys,
        "argv",
        [
            "verify_execpolicy.py",
            "--codex",
            str(binary),
            "--rules",
            str(candidate),
            "--baseline",
            str(baseline),
            "--output",
            str(targets[target]),
        ],
    )
    with pytest.raises(ValueError, match="Output must not overwrite"):
        verifier.main()
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_rules_cover_readme_virtualenv_launchers(verifier):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    names = re.findall(r"^python -m venv ([.\w-]+)\s*$", readme, flags=re.MULTILINE)
    assert names, "No documented virtualenv command found"
    rules = verifier.literal_rules(ROOT / ".codex/rules/settings-local.rules")
    covered = {token for rule in rules for token in rule["pattern"][0]}
    for name in names:
        expected = {
            f"{name}/bin/python",
            f"./{name}/bin/python",
            f"{name}/bin/python3",
            f"./{name}/bin/python3",
            f"{name}/Scripts/python.exe",
            f"./{name}/Scripts/python.exe",
            f"{name}\\Scripts\\python.exe",
            f".\\{name}\\Scripts\\python.exe",
        }
        assert expected <= covered, f"Missing documented launchers: {sorted(expected - covered)}"
