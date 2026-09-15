"""Require canonical V1 replay in a guarded disposable clone, retaining its audit."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.run_strategy_persistence_acceptance import isolated_domain_database  # noqa: E402
from scripts.ci.validate_suite_junit import validate  # noqa: E402

TEST = "tests/integration/test_5scr_canonical_v1_handoff_replay.py"


def main() -> int:
    output = ROOT / "artifacts/python-suite"
    output.mkdir(parents=True, exist_ok=True)
    junit = output / "canonical-v1-replay.xml"
    lineage = output / "canonical-v1-lineage.json"
    if lineage.exists() or junit.exists():
        raise ValueError("REPLAY_RECEIPT_ALREADY_EXISTS")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    with isolated_domain_database():
        environment = dict(os.environ)
        environment.update(
            DATABASE_URL=environment["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"],
            WOLF15_LOAD_DOTENV="false",
            WOLF15_P5_REPLAY_RECEIPT=str(lineage),
            WOLF15_P5_REPLAY_SOURCE_COMMIT=commit,
        )
        subprocess.run(
            [sys.executable, "-m", "pytest", TEST, "-o", "addopts=", "-q", "--timeout=60", f"--junitxml={junit}"],
            cwd=ROOT,
            env=environment,
            check=True,
            timeout=240,
        )
    if validate(junit) != 3:
        raise ValueError("REPLAY_REQUIRED_CASES_NOT_ALL_PASSED")
    evidence = json.loads(lineage.read_text(encoding="utf-8"))
    if evidence["counts"] != {
        "commands": 1,
        "reservations": 1,
        "final_signals": 1,
        "execution_reports": 0,
        "broker_entities": 0,
    }:
        raise ValueError("REPLAY_EFFECT_COUNTS_MISMATCH")
    print("Required canonical V1 replay: 3 cases passed; isolated lineage receipt retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
