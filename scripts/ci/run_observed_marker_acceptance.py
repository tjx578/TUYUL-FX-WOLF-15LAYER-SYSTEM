"""Require historical marker preservation in one guarded empty database per case."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.validate_suite_junit import validate  # noqa: E402


def main() -> int:
    receipt = ROOT / "artifacts/python-suite/observed-marker.xml"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(WOLF15_RUN_OBSERVED_MARKER_CI="1", WOLF15_LOAD_DOTENV="false")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_observed_marker_migration_postgres.py",
            "-o",
            "addopts=",
            "-q",
            "--timeout=120",
            f"--junitxml={receipt}",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        timeout=600,
    )
    if validate(receipt) != 4:
        raise ValueError("OBSERVED_MARKER_REQUIRED_CASES_NOT_ALL_PASSED")
    print("Required historical marker upgrade: 4 cases passed; isolated audit retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
