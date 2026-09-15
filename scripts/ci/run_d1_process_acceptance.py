"""Run opt-in D1 process campaigns on newly created disposable Docker resources."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.validate_suite_junit import validate  # noqa: E402
from tests.integration.test_orchestrator_legacy_import_redis import PRODUCT_PATHS  # noqa: E402
from tests.integration.test_orchestrator_process_recovery import REDIS_IMAGE  # noqa: E402

POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
TESTS = (
    "tests/integration/test_orchestrator_container_entrypoints.py",
    "tests/integration/test_orchestrator_process_recovery.py",
    "tests/integration/test_orchestrator_legacy_import_redis.py",
)


def main() -> int:
    folder = ROOT / "artifacts/python-suite/d1-process"
    folder.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    binding = {
        "scope": "CI_SOURCE_BINDING_ONLY_NOT_PRODUCTION_IMPORT_AUTHORITY",
        "source": {
            "commit": commit,
            "product_files": {
                path: {"working_sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
                for path in sorted(PRODUCT_PATHS)
            },
        },
    }
    binding_path = folder / "source-binding.json"
    binding_path.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "TMPDIR", "RUNNER_TEMP", "VIRTUAL_ENV"}
    }
    environment.update(
        PYTHONPATH=str(ROOT),
        PYTHON_DOTENV_DISABLED="1",
        WOLF15_LOAD_DOTENV="false",
        WOLF15_RUN_PROCESS_RECOVERY="1",
        WOLF15_PROCESS_RECOVERY_EVIDENCE=str(folder / "recovery"),
        WOLF15_IMPORT_REVIEW_RECEIPT=str(binding_path),
        WOLF15_IMPORT_REVIEW_RECEIPT_SHA256=hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        WOLF15_IMPORT_PRODUCT_COMMIT=commit,
        WOLF15_RUN_T14_CONTAINER_SMOKE="1",
        WOLF15_T14_EXPECTED_COMMIT=commit,
        WOLF15_T14_EXPECTED_TREE=tree,
        WOLF15_T14_REDIS_IMAGE=REDIS_IMAGE,
        WOLF15_T14_POSTGRES_IMAGE=POSTGRES_IMAGE,
        WOLF15_T14_RECEIPT_PATH=str(folder / "t14.json"),
    )
    for image in (REDIS_IMAGE, POSTGRES_IMAGE):
        subprocess.run(["docker", "pull", image], check=True, timeout=180)
    junit = ROOT / "artifacts/python-suite/d1-process.xml"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *TESTS,
            "--noconftest",
            "-o",
            "addopts=",
            "-q",
            "--timeout=1200",
            f"--junitxml={junit}",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        timeout=1500,
    )
    print(f"D1 process cases executed without skip: {validate(junit)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
