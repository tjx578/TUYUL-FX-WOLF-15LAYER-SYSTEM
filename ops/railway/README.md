# Railway Production Deployment (Wolf-15)

## Services

1. `wolf15-api` → `bash deploy/railway/start_api.sh`
2. `wolf15-engine` → `bash deploy/railway/start_engine.sh`
3. `wolf15-ingest` → `bash deploy/railway/start_ingest.sh`
4. `wolf15-orchestrator` → `bash deploy/railway/start_orchestrator.sh`
5. `wolf15-allocation` → `bash deploy/railway/start_allocation.sh`
6. `wolf15-execution` → `bash deploy/railway/start_execution.sh`
7. `wolf15-migrator` (one-shot) → `bash deploy/railway/start_migrator.sh`

## Infra

- 1x Redis (event spine)
- 1x Postgres (source of truth)

## Redis Topics

- `context:stream`
- `signals:global`
- `allocation:request`
- `execution:queue`
- `trade:updates`
- `account:updates`

## Non-Negotiable Runtime Guards

- API rejects execution if no Layer-12 verdict ID.
- Allocation must call prop guard before enqueue execution.
- Execution must never alter strategy fields (direction/entry/SL/TP).
- Journal writes are append-only (no update/delete path).

## P2 Operational Maturity

- Role-scoped readiness checks:
  - API: `/healthz` (liveness), `/readyz` (freshness + producer heartbeat gate)
  - Ingest: `/healthz` on `INGEST_HEALTH_PORT` / `PORT`
  - Engine: `/healthz` on `ENGINE_HEALTH_PORT` / `PORT`
  - Orchestrator: `/healthz` on `ORCHESTRATOR_HEALTH_PORT` / `PORT`
- Observability machine-auth boundary:
  - Endpoints: `/metrics`, `/healthz`, `/readyz`
  - Headers: `X-Machine-Key: <key>` or `Authorization: Bearer <key>`
  - Env mode: `OBSERVABILITY_AUTH_MODE=optional|required|disabled`
  - Env key: `OBSERVABILITY_MACHINE_KEY` (fallback `MACHINE_OBSERVABILITY_KEY`)
- Orchestrator observability surfaces:
  - Redis state key: `wolf15:orchestrator:state`
  - API read model: `GET /api/v1/orchestrator/state`
  - Prometheus gauges via `GET /metrics`:
    - `wolf_orchestrator_heartbeat_age_seconds`
    - `wolf_orchestrator_ready`
    - `wolf_orchestrator_mode{mode=...}`

- Immutable audit journal: use `journal.audit_trail.AuditTrail` for append-only security/ops events.
- Canary deployment automation for ingestion and execution services:
  - Local/CI script: `python scripts/railway_canary.py --service wolf_ingest --action deploy`
  - GitHub workflow: `.github/workflows/railway-canary.yml`
  - Configure command templates with secrets: `CANARY_DEPLOY_CMD`, `CANARY_SHIFT_CMD`, `CANARY_PROMOTE_CMD`, `CANARY_ROLLBACK_CMD`
- Incident runbook automation:
  - Local/CI script: `python scripts/incident_runbook.py --incident ingest_down --service wolf_ingest`
  - GitHub workflow: `.github/workflows/incident-runbook.yml`
  - Reports are written to `storage/incidents/` and incident events are audit-logged to `storage/audit/incident_audit.jsonl`.
