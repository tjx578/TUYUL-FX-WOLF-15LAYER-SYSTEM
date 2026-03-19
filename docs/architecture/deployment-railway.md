# Deployment on Railway

**Status:** Canonical deployment summary

## Purpose

This document makes Railway deployment part of the architecture surface instead of burying it in infra notes. Production safety depends on topology being explicit.

## Core services

- API service for read-only aggregation and operator interfaces
- entrypoint: deploy/railway/start_api.sh
- probes: /healthz (liveness), /readyz (readiness)
- readiness scope: feed freshness + producer heartbeat gates
- ingest worker for live market and event production
- entrypoint: deploy/railway/start_ingest.sh
- probes: /healthz on INGEST_HEALTH_PORT/PORT
- readiness scope: producer heartbeat and transport continuity
- engine worker for analysis and constitutional decisions
- entrypoint: deploy/railway/start_engine.sh
- probes: /healthz on ENGINE_HEALTH_PORT/PORT
- readiness scope: at least one completed analysis cycle
- orchestrator worker for compliance mode and coordination state publication
- entrypoint: deploy/railway/start_orchestrator.sh
- probes: /healthz on ORCHESTRATOR_HEALTH_PORT/PORT
- readiness scope: orchestrator loop started + heartbeat publishing
- execution or allocation workers for bounded operational roles
- supporting Redis and persistence services

## Role-Scoped Readiness Contract

- API readiness endpoint: /readyz
- must fail when freshness class is no_producer/no_transport/config_error/stale_preserved
- must fail when producer heartbeat is stale or missing
- Ingest readiness surface: /healthz + startup stage details
- service is healthy only after bootstrap probe binds and ingest loop starts
- Engine readiness surface: /healthz on ENGINE_HEALTH_PORT/PORT
- must stay not-ready until analysis path reports healthy cycle
- Orchestrator readiness surface: /healthz on ORCHESTRATOR_HEALTH_PORT/PORT
- must stay not-ready until listener boot completes
- readiness should be interpreted with heartbeat age from state key

## Service Environment Baseline

Required role-scoped env vars for deployment manifests and startup scripts:

- API
- WOLF15_SERVICE_ROLE=api
- Engine
- WOLF15_SERVICE_ROLE=engine
- ENGINE_HEALTH_PORT=${PORT}
- Ingest
- WOLF15_SERVICE_ROLE=ingest
- INGEST_HEALTH_PORT=${PORT}
- Orchestrator
- WOLF15_SERVICE_ROLE=orchestrator
- ORCHESTRATOR_HEALTH_PORT=${PORT}
- ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC (default 30)

## Deployment rule

The engine must never be assumed to imply live ingest. Running analysis without an active producer creates stale-state failure modes.

API, engine, ingest, and orchestrator are independent runtime concerns even when deployed on the same platform.

## Operational references

- `infrastructure/railway/service-map.md`
- `infrastructure/deployment-baseline.md`
- `ops/railway/README.md`
- `incidents/rca_20260317_stale_feed.md`
