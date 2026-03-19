# Deployment on Railway

**Status:** Canonical deployment summary

## Purpose

This document makes Railway deployment part of the architecture surface instead of burying it in infra notes. Production safety depends on topology being explicit.

## Core services

- API service for read-only aggregation and operator interfaces
- entrypoint: deploy/railway/start_api.sh
- health probe: /healthz (liveness), /readyz (readiness)
- ingest worker for live market and event production
- entrypoint: deploy/railway/start_ingest.sh
- health probe: /healthz
- engine worker for analysis and constitutional decisions
- entrypoint: deploy/railway/start_engine.sh
- health probe: /healthz on ENGINE_HEALTH_PORT/PORT
- orchestrator worker for compliance mode and coordination state publication
- entrypoint: deploy/railway/start_orchestrator.sh
- health probe: /healthz on ORCHESTRATOR_HEALTH_PORT/PORT
- execution or allocation workers for bounded operational roles
- supporting Redis and persistence services

## Deployment rule

The engine must never be assumed to imply live ingest. Running analysis without an active producer creates stale-state failure modes.

API, engine, ingest, and orchestrator are independent runtime concerns even when deployed on the same platform.

## Operational references

- `infrastructure/railway/service-map.md`
- `infrastructure/deployment-baseline.md`
- `ops/railway/README.md`
- `incidents/rca_20260317_stale_feed.md`
