from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from deploy.railway.migration_runner import run_migrations

ROOT = Path(__file__).resolve().parents[1]


def ci_workflow():
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def test_dashboard_lint_and_tests_are_required_without_soft_failure() -> None:
    steps = ci_workflow()["jobs"]["dashboard"]["steps"]
    lint = next(step for step in steps if step.get("name") == "Lint")
    tests = next(step for step in steps if step.get("name") == "Dashboard tests")
    assert lint["run"] == "npm run lint"
    assert tests["run"] == "npm test"
    assert not lint.get("continue-on-error", False)
    assert not tests.get("continue-on-error", False)


def _run_contract_guard(tmp_path: Path, content: str | None) -> subprocess.CompletedProcess:
    steps = ci_workflow()["jobs"]["drift-guard"]["steps"]
    step = next(step for step in steps if step.get("name") == "L12 signal must not carry account state")
    source = step["run"].split("python - <<'PYEOF'\n", 1)[1].rsplit("PYEOF", 1)[0]
    if content is not None:
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts/redis_stream_contracts.py").write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={**{key: os.environ[key] for key in ("SystemRoot", "PATH") if key in os.environ}, "PYTHONUTF8": "1"},
        encoding="utf-8",
    )


def test_missing_required_contract_fails_ci(tmp_path) -> None:
    assert _run_contract_guard(tmp_path, None).returncode == 1


def test_missing_verdict_declaration_fails_ci(tmp_path) -> None:
    assert _run_contract_guard(tmp_path, "class Unrelated: pass\n").returncode == 1


@pytest.mark.parametrize(
    "source",
    [
        "# class VerdictPayload is missing\nclass Unrelated: pass\n",
        "text = 'class VerdictPayload is missing'\n",
        "class VerdictPayload: pass\nclass VerdictPayload: pass\n",
        "class VerdictPayload(\n",
    ],
)
def test_spoofed_duplicate_or_malformed_verdict_fails_ci(tmp_path, source) -> None:
    assert _run_contract_guard(tmp_path, source).returncode != 0


def test_account_state_in_verdict_fails_ci(tmp_path) -> None:
    assert _run_contract_guard(tmp_path, "class VerdictPayload:\n    balance: float\n").returncode == 1


def test_clean_verdict_passes_ci(tmp_path) -> None:
    assert _run_contract_guard(tmp_path, "class VerdictPayload:\n    symbol: str\n").returncode == 0


def test_failed_migration_propagates_exit_and_redacts_output(capsys) -> None:
    # A subprocess fixture only; never invokes Alembic or connects to a database.
    fixture = "print('postgresql://fixture:private-fixture-password@localhost/example'); raise SystemExit(7)"
    assert run_migrations((sys.executable, "-c", fixture)) == 7
    output = capsys.readouterr()
    assert "private-fixture-password" not in output.out


def test_successful_migration_propagates_exit(capsys) -> None:
    assert run_migrations((sys.executable, "-c", "print('fixture-migration-ok')")) == 0
    assert "fixture-migration-ok" in capsys.readouterr().out
