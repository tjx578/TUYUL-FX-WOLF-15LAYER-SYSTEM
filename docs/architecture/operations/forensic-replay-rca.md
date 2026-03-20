# Forensic Replay RCA (P2-6)

Status: implemented
Owner domain: observability / data engineering / backend

## Purpose

Provide minimum, durable artifacts so core incidents can be reconstructed from append-only truth instead of ad hoc logs.

## Minimum Replay Artifacts

The replay pipeline requires these artifact types per correlation ID:

- `event_history`
- `verdict_provenance`
- `firewall_result`
- `execution_lifecycle`
- `freshness_snapshot`

Coverage is computed by `journal.forensic_replay.replay_coverage_report`.

## Artifact Sources

- Verdict provenance: `storage/l12_cache.py` via `append_replay_artifact("verdict_provenance", ...)`
- Firewall result: `risk/firewall.py` via `append_replay_artifact("firewall_result", ...)`
- Freshness snapshot: `api/allocation_router.py` in `_runtime_take_precheck`
- Execution lifecycle + event history: `api/allocation_router.py` in:
  - `_confirm_trade_internal` (`ORDER_PLACED`)
  - `record_trade_lifecycle_event`

All artifacts are append-only JSONL in `storage/forensics/replay_artifacts.jsonl`.

## RCA Reconstruction Tool

CLI script:

- `python scripts/forensic_replay_rca.py --correlation-id <id>`

Optional strict mode (non-zero exit when artifacts incomplete):

- `python scripts/forensic_replay_rca.py --correlation-id <id> --strict`

Optional custom log paths:

- `--artifact-log <path>`
- `--audit-log <path>`

## Forensic Data Inputs

The reconstruction utility merges:

- Forensic artifact JSONL (`storage/forensics/replay_artifacts.jsonl`)
- Audit trail JSONL (`storage/audit/audit_trail.jsonl`)

Timeline entries are sorted by timestamp and emitted as a machine-readable JSON report.

## Boundary Notes

- Journal/replay remains write-only append behavior for artifact emission.
- No market-direction logic is added to execution/dashboard.
- L12 authority boundaries remain unchanged.
