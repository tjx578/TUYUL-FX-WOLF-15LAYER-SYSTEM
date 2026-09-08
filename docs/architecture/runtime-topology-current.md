# Runtime Topology — Current System

**Status:** Canonical
**Scope:** Current runtime service topology and operational boundaries.


> Dashboard revision 2026-09-09: the selected frontend is `https://wolf15-dashboard-frontend-production.up.railway.app` (port `8080`), with server-only direct core calls to `https://wolf15-api-production.up.railway.app`. Public `/login` still shows `VIEWER JWT`; repository password-login/direct-core changes are not a production deployment. Production acceptance remains HOLD. Other service sections retain their earlier evidence dates and do not authorize engine, broker, database or provider mutations.

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
- legacy standalone dashboard-bff (disconnected from selected frontend; non-authoritative)
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

The selected Railway frontend serves the owner as a read-only viewer on port 8080. Username/password login establishes a bounded HttpOnly session. Exactly three GET projections call core directly through server-only `INTERNAL_API_URL`; unrecognized paths and mutations are rejected. It does not control strategy, execution, risk, broker or engine state.

### Legacy standalone Dashboard-BFF

The Python service code remains for legacy deployments. It is disconnected from the selected frontend and is neither a dependency nor a fallback for login or reads. No existing provider service was stopped or deleted by this repository revision. See [direct API topology](dashboard-hybrid-topology.md), whose historical filename is retained for link compatibility.

## Current Known Architecture Debt

The following debt is acknowledged until removed:

- orchestrator entry flow must visibly enforce compliance before downstream action where required

The following items were previously listed as debt and have been resolved:

- Selected owner login uses `DASHBOARD_MODE=viewer`, a backend password verifier and a 15-minute viewer JWT; production acceptance remains HOLD.
- Selected browser session has no machine-key fallback and no WebSocket ticket route.
- ~~overlapping proxy paths must be removed~~ — resolved: single canonical proxy at `/api/proxy/[...path]`, dead `rewrites()` removed.
- Selected frontend status comes only through the three scoped projections; core `/healthz` and `/readyz` retain infrastructure semantics.

## Health and Status Semantics

- `/healthz` and `/readyz` are infrastructure/service health surfaces
- dashboard/operator status must be presented on a separate surface
- frontend relay endpoints must not redefine infra semantics
- if a dashboard-BFF is deployed, it must expose its own `/healthz` and
  `/readyz` endpoints; its health must not be conflated with core-api health

## Concurrency Model

Legacy Python dashboard state is protected by a write-preferring reader/writer lock (`RWLock`). This is separate from the selected Next.js viewer:

- Multiple readers may access state concurrently.
- When a writer is waiting, new readers queue behind it to prevent writer starvation.
- Both read and write acquisitions are bounded by a safety timeout (10 s default).
- State snapshots read all fields within a single critical section to prevent torn reads.

## Runtime Truth vs Historical Truth

Use this file for:

- current deployment reasoning
- current service boundary review
- current auth/proxy/health cleanup decisions
- selected Railway frontend direct-core topology decisions

Use historical lineage files for:

- engine evolution
- zone-based learning
- pipeline ancestry
