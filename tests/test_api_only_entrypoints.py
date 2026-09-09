from __future__ import annotations

import builtins
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ("start_api.sh", "start_api_consolidated.sh")


def _bash() -> str:
    # Windows system32/bash is the WSL launcher, not the shell under test.
    path = Path("C:/Program Files/Git/bin/bash.exe") if os.name == "nt" else None
    result = str(path) if path is not None and path.is_file() else shutil.which("bash")
    assert result, "An installed Bash runtime is required for entrypoint behavior tests"
    if os.name == "nt":
        assert path is not None and path.is_file(), "Git Bash is required; do not invoke WSL"
    return result


def _shell_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return f"/{value[0].lower()}{value[2:]}" if os.name == "nt" else value


def _run_entrypoint(tmp_path: Path, name: str, switch: str | None) -> tuple[subprocess.CompletedProcess, list[str]]:
    recorder = tmp_path / "gunicorn"
    record = tmp_path / "gunicorn-record.txt"
    recorder.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf "%s\\n" "LAUNCH" "$WOLF15_SERVICE_ROLE" "$@" >> "$WOLF15_TEST_RECORD"\n',
        encoding="utf-8",
        newline="\n",
    )
    recorder.chmod(0o755)
    env = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
    env.update(WOLF15_TEST_RECORD=_shell_path(record), PORT="8765", GUNICORN_WORKERS="3")
    if switch is not None:
        env["WOLF15_EMBED_ORCHESTRATOR"] = switch
    result = subprocess.run(
        [
            _bash(),
            "-c",
            'export PATH="$1:$PATH"; exec bash "$2"',
            "entrypoint-test",
            _shell_path(tmp_path),
            _shell_path(ROOT / "deploy/railway" / name),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    return result, record.read_text(encoding="utf-8").splitlines() if record.exists() else []


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize("switch", ["true", "1", "yes", "on", "TrUe", " \tYeS \n"])
def test_api_entrypoints_reject_embedded_owner_before_launch(tmp_path, name, switch) -> None:
    result, lines = _run_entrypoint(tmp_path, name, switch)
    assert result.returncode == 1, result.stderr
    assert "WOLF15_EMBED_ORCHESTRATOR is no longer supported" in result.stderr
    assert lines == []


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize("switch", [None, "false", " FaLsE ", "0", "off", ""])
def test_api_entrypoints_launch_exactly_one_api_process(tmp_path, name, switch) -> None:
    result, lines = _run_entrypoint(tmp_path, name, switch)
    assert result.returncode == 0, result.stderr
    assert lines.count("LAUNCH") == 1
    assert lines[:3] == ["LAUNCH", "api", "app:app"]
    assert lines[lines.index("--bind") + 1] == "0.0.0.0:8765"
    assert lines[lines.index("--workers") + 1] == "3"
    assert lines[lines.index("--keep-alive") + 1] == "75"


def test_railway_default_uses_canonical_api_entrypoint() -> None:
    config = tomllib.loads((ROOT / "railway.toml").read_text(encoding="utf-8"))
    assert config["deploy"]["startCommand"] == "bash deploy/railway/start_api.sh"


@pytest.mark.asyncio
@pytest.mark.parametrize("switch", ["true", "1", "yes", "on", " TrUe ", "\tYES\n"])
async def test_api_lifespan_rejects_embedded_owner_before_consumer_import(monkeypatch, switch) -> None:
    from api.app_factory import lifespan

    monkeypatch.setenv("WOLF15_EMBED_ORCHESTRATOR", switch)
    imported_consumers: list[str] = []
    original_import = builtins.__import__

    def reject_consumer_import(name, *args, **kwargs):
        if name in {"infrastructure.redis_client", "infrastructure.redis_url", "storage.trade_outbox_worker"}:
            imported_consumers.append(name)
            raise AssertionError("Consumer import occurred before API-only ownership guard")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_consumer_import)
    with pytest.raises(RuntimeError, match="WOLF15_EMBED_ORCHESTRATOR is no longer supported"):
        async with lifespan(FastAPI()):
            pytest.fail("Embedded ownership must fail before entering the application lifespan")
    assert imported_consumers == []
