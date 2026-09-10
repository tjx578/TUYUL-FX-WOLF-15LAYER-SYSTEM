"""Run current Docs Hygiene run blocks locally without mutating workflows."""

import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

root = Path.cwd()
out = Path(__file__).resolve().parent
wf = root / ".github/workflows/docs-hygiene.yml"
config = yaml.safe_load(wf.read_text(encoding="utf-8"))
results = []
for job in ["reading-order", "legacy-quarantine", "cross-references", "docs-gate"]:
    for ix, step in enumerate(config["jobs"][job]["steps"]):
        if "run" not in step:
            continue
        script = step["run"]
        if job == "docs-gate":
            for key in ["reading-order", "legacy-quarantine", "cross-references"]:
                state = "success" if all(r["exit_code"] == 0 for r in results if r["job"] == key) else "failure"
                script = script.replace("${{ needs." + key + ".result }}", state)
        name = f"{job}-{ix}"
        target = out / (name + ".sh")
        target.write_text(script, encoding="utf-8", newline="\n")
        env = dict(os.environ)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
        process = subprocess.run(
            ["C:/Program Files/Git/bin/bash.exe", "--noprofile", "--norc", "-eo", "pipefail", str(target)],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )
        (out / (name + ".log")).write_text(process.stdout + process.stderr, encoding="utf-8")
        results.append(
            {
                "job": job,
                "step": step["name"],
                "exit_code": process.returncode,
                "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
                "log": name + ".log",
            }
        )
        print(job, process.returncode, process.stdout.strip())
files = [
    "docs/architecture/contracts/operational-api-event-acceptance-spec.md",
    "docs/architecture/guardrails/tick-spike-filter.md",
    "docs/architecture/operations/go-live-checklist.md",
    "docs/architecture/operations/observability-async-workers.md",
]
receipt = {
    "scope": "Exact run blocks from docs-hygiene.yml; local Git Bash; gate expressions resolved from preceding local outcomes",
    "timestamp_utc": datetime.datetime.now(datetime.UTC).isoformat(),
    "workflow_sha256": hashlib.sha256(wf.read_bytes()).hexdigest(),
    "head_at_check": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "modified_source_sha256": {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files},
    "results": results,
    "remote_ci": "NOT_EXECUTED by this subtask",
}
(out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
sys.exit(1 if any(r["exit_code"] for r in results) else 0)
