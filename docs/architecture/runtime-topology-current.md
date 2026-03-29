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

## Current Known Architecture Debt

The following debt is acknowledged until removed:

- owner dashboard auth model is not yet fully simplified
- browser-facing auth fallback must be reduced to a single clean contract
- overlapping proxy paths must be removed
- dashboard status routing and infrastructure probe routing must be clearly separated
- orchestrator entry flow must visibly enforce compliance before downstream action where required

## Health and Status Semantics

- `/healthz` and `/readyz` are infrastructure/service health surfaces
- dashboard/operator status must be presented on a separate surface
- frontend relay endpoints must not redefine infra semantics

## Runtime Truth vs Historical Truth

Use this file for:

- current deployment reasoning
- current service boundary review
- current auth/proxy/health cleanup decisions

Use historical lineage files for:

- engine evolution
- zone-based learning
- pipeline ancestry
