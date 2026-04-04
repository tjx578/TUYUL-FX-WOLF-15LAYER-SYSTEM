# Runtime Topology — Current System

**Status:** Canonical
**Scope:** Current runtime service topology and operational boundaries.

## Purpose

This document describes the CURRENT runtime topology.

It is not a historical architecture summary and not a legacy engine-only diagram.
Its purpose is to define the live service boundaries that current code and deployment must obey.

## Current Runtime Concerns

The system is composed of distinct runtime concerns:

- ingest / market production
- engine / analysis pipeline
- orchestrator / governance mode control
- trade service / allocation + execution workers
- API surfaces
- dashboard frontend
- dashboard-bff / dashboard-realtime-gateway (optional, non-authoritative)
- Redis and persistence services

## Topology Rule

Current operational truth is service-oriented.

Historical engine-centric or monolithic diagrams may still be useful for lineage,
but they are not the primary source of truth for current runtime topology.

## Current Authority Map

### Ingest

Responsible for market/event acquisition, validation, normalization, and producer heartbeat publication.

### Engine

Responsible for analysis, constitutional flow, and verdict production under governance constraints.

### Orchestrator

Responsible for mode control, compliance state evaluation, and coordination of allowed downstream flow.

### Risk Firewall

Responsible for veto checks before execution.
It is a gating authority, not a strategy authority.

### Trade Service

Responsible for allocation and execution worker runtime behavior.

### Dashboard

Responsible for owner-operated control, diagnostics, and frontend transport orchestration.
It is not constitutional verdict authority.

### Dashboard-BFF (Optional)

When deployed, responsible for dashboard-specific data aggregation, caching,
and pre-processing. It is surface-scoped to the dashboard frontend only.
It is not constitutional verdict authority and must not produce risk decisions
or execution commands. The Next.js proxy routes a defined allowlist of paths
to the BFF upstream; all other paths resolve to core-api.
See `docs/architecture/dashboard-hybrid-topology.md` for the full contract.

## Current Known Architecture Debt

The following debt is acknowledged until removed:

- orchestrator entry flow must visibly enforce compliance before downstream action where required

The following items were previously listed as debt and have been resolved:

- ~~owner dashboard auth model is not yet fully simplified~~ — resolved: `DASHBOARD_MODE=owner` with `validateDashboardMode()` guard.
- ~~browser-facing auth fallback must be reduced to a single clean contract~~ — resolved: API key fallback removed from ws-ticket route.
- ~~overlapping proxy paths must be removed~~ — resolved: single canonical proxy at `/api/proxy/[...path]`, dead `rewrites()` removed.
- ~~dashboard status routing and infrastructure probe routing must be clearly separated~~ — resolved: `/api/status` (operator, session-authed) vs `/healthz` + `/readyz` (infra, no session).

## Health and Status Semantics

- `/healthz` and `/readyz` are infrastructure/service health surfaces
- dashboard/operator status must be presented on a separate surface
- frontend relay endpoints must not redefine infra semantics
- if a dashboard-BFF is deployed, it must expose its own `/healthz` and
  `/readyz` endpoints; its health must not be conflated with core-api health

## Concurrency Model

Dashboard state is protected by a write-preferring reader/writer lock (`RWLock`):

- Multiple readers may access state concurrently.
- When a writer is waiting, new readers queue behind it to prevent writer starvation.
- Both read and write acquisitions are bounded by a safety timeout (10 s default).
- State snapshots read all fields within a single critical section to prevent torn reads.

## Runtime Truth vs Historical Truth

Use this file for:

- current deployment reasoning
- current service boundary review
- current auth/proxy/health cleanup decisions
- optional hybrid dashboard topology decisions

Use historical lineage files for:

- engine evolution
- zone-based learning
- pipeline ancestry
