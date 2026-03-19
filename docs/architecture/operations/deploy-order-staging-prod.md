# Deploy Order Checklist (Staging and Production)

Status: operational runbook
Scope: Railway deployment for topology with one-shot migrator

## Topology Assumption

This checklist assumes:

- wolf15-migrator is the only migration actor
- API and engine do not run Alembic at startup
- Runtime services stay long-running
- Scheduled research jobs run one-shot

Service scripts:

- API: deploy/railway/start_api.sh
- Engine: deploy/railway/start_engine.sh
- Ingest: deploy/railway/start_ingest.sh
- Allocation: deploy/railway/start_allocation.sh
- Execution: deploy/railway/start_execution.sh
- Orchestrator: deploy/railway/start_orchestrator.sh
- Migrator: deploy/railway/start_migrator.sh
- Worker generic: deploy/railway/start_worker.sh

## A. Pre-Deploy Checklist (All Environments)

1. Config and secrets

- [ ] DATABASE_URL is set on services that require DB access
- [ ] REDIS_URL is set for ingest, engine, allocation, execution, orchestrator, and workers that need Redis
- [ ] JWT_SECRET is set for API
- [ ] FINNHUB_API_KEY is set for ingest
- [ ] EA_BRIDGE_URL is set for execution

1. Deployment manifests

- [ ] railway-migrator.toml exists and points to deploy/railway/start_migrator.sh
- [ ] Runtime services use their start scripts in railway *.toml
- [ ] Worker services use explicit entries (montecarlo, backtest, regime)

1. Safety and visibility

- [ ] Health endpoints are role-scoped and defined for API, ingest, engine, and orchestrator
- [ ] API /readyz passes freshness and producer heartbeat gates
- [ ] Engine /healthz responds on ENGINE_HEALTH_PORT/PORT
- [ ] Ingest /healthz responds on INGEST_HEALTH_PORT/PORT
- [ ] Orchestrator /healthz responds on ORCHESTRATOR_HEALTH_PORT/PORT
- [ ] Logging/alerts are enabled for startup failures and restart loops
- [ ] Change window and rollback owner are assigned

## B. Staging Deploy Order (Practical Sequence)

Goal: validate release behavior before production cutover.

1. Freeze and snapshot

- [ ] Stop auto redeploy for staging services during rollout window
- [ ] Record current release version for every service
- [ ] Confirm Postgres and Redis are healthy

1. Deploy one-shot migrator first

- [ ] Deploy wolf15-migrator with new image
- [ ] Run one-shot command and wait until completed
- [ ] Confirm Alembic reached head revision

1. Deploy runtime core in order

- [ ] Deploy wolf15-ingest
- [ ] Deploy wolf15-engine
- [ ] Deploy wolf15-orchestrator
- [ ] Deploy wolf15-allocation
- [ ] Deploy wolf15-execution
- [ ] Deploy wolf15-api

1. Validate runtime after each group

- [ ] API /healthz responds 200
- [ ] API /readyz responds 200 (no freshness/heartbeat block reason)
- [ ] Ingest publishes fresh ticks/candles
- [ ] Ingest /healthz responds 200 on service port
- [ ] Engine preflight passes and /healthz responds 200 on service port
- [ ] Orchestrator /healthz responds 200 on service port
- [ ] Orchestrator heartbeat age and readiness are visible in observability surfaces
- [ ] Allocation and execution consume expected events

1. Validate one-shot workers

- [ ] Run wolf15-worker-montecarlo once and verify completion
- [ ] Run wolf15-worker-backtest once and verify completion
- [ ] Run wolf15-worker-regime once and verify completion

1. Staging sign-off gates

- [ ] No schema errors in engine or API logs
- [ ] No migration race or duplicate migration attempts
- [ ] No critical alert in first 30 minutes after rollout
- [ ] Functional smoke tests pass

## C. Production Deploy Order (Practical Sequence)

Goal: controlled rollout with fail-fast schema readiness and clear rollback.

1. Pre-cutover controls

- [ ] Declare change freeze window
- [ ] Confirm on-call owner and incident bridge
- [ ] Ensure latest staging release is approved
- [ ] Confirm backup/restore point for Postgres exists

1. Run migrator as single actor

- [ ] Deploy wolf15-migrator with production release image
- [ ] Execute one-shot migration
- [ ] Confirm migration completed successfully
- [ ] Abort production rollout if migration fails

1. Roll out long-running services

- [ ] Deploy wolf15-ingest
- [ ] Deploy wolf15-engine
- [ ] Deploy wolf15-orchestrator
- [ ] Deploy wolf15-allocation
- [ ] Deploy wolf15-execution
- [ ] Deploy wolf15-api

1. Immediate production checks

- [ ] API /healthz healthy
- [ ] API /readyz healthy
- [ ] Engine is running with RUN_MODE=engine-only
- [ ] Fresh market data is flowing from ingest to engine
- [ ] Orchestrator compliance/mode state is valid
- [ ] Orchestrator heartbeat age remains below readiness threshold
- [ ] No elevated 5xx and no restart loops

1. Post-cutover checks (first 60 minutes)

- [ ] Error rate remains within baseline
- [ ] Signal pipeline latency within normal range
- [ ] No outbox schema errors
- [ ] No constitutional boundary violations

## D. Rollback Playbook (Staging and Production)

1. If migrator fails

- [ ] Stop rollout immediately
- [ ] Keep runtime services on previous working release
- [ ] Investigate migration failure and fix forward

1. If runtime fails after successful migration

- [ ] Roll back affected runtime services to previous image
- [ ] Keep schema at newer revision unless explicit down-migration plan exists
- [ ] Validate compatibility of old runtime with current schema

1. If data flow breaks

- [ ] Prioritize ingest and Redis connectivity checks
- [ ] Validate engine consumer groups and stream lag
- [ ] Validate orchestrator and execution heartbeats

## E. Environment-Specific Notes

Staging:

- Use shorter observation window if traffic is low, but keep all gates
- Workers can be triggered manually for release validation

Production:

- Prefer serial deploy over parallel for core runtime
- Keep worker jobs scheduled, not continuously running
- Do not reintroduce auto-migration in API or engine

## F. Quick Command Reference

Migrator one-shot:

- python -m alembic upgrade head

Worker examples:

- bash deploy/railway/start_worker.sh services.worker.montecarlo_job
- bash deploy/railway/start_worker.sh services.worker.nightly_backtest
- bash deploy/railway/start_worker.sh services.worker.regime_recalibration
