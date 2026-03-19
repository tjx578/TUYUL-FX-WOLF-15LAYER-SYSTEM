# Deployment on Railway

**Status:** Canonical deployment summary

## Purpose

This document makes Railway deployment part of the architecture surface instead of burying it in infra notes. Production safety depends on topology being explicit.

## Core services

- API service for read-only aggregation and operator interfaces
- ingest worker for live market and event production
- engine worker for analysis and constitutional decisions
- execution or orchestration workers for bounded operational roles
- supporting Redis and persistence services

## Deployment rule

The engine must never be assumed to imply live ingest. Running analysis without an active producer creates stale-state failure modes.

## Operational references

- `infrastructure/railway/service-map.md`
- `infrastructure/deployment-baseline.md`
- `ops/railway/README.md`
- `incidents/rca_20260317_stale_feed.md`
