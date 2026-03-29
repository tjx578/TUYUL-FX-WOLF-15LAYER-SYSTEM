# System Overview

**Status:** Canonical overview
**Scope:** End-to-end understanding of the TUYUL FX Wolf 15-layer system.

## Purpose

This document explains how the full system is separated into authorities so that analysis, governance, execution, and operator visibility do not collapse into one unsafe surface.

This system separates analysis, governance, execution, and owner operations so they do not collapse into one unsafe surface.
The dashboard is part of owner operations, not part of constitutional decision authority.

## End-to-end model

```text
Market data and macro events
  -> ingest and normalization
  -> context hydration and freshness checks
  -> Wolf analytical pipeline
  -> Layer 12 constitutional verdict
  -> execution services and EA bridge
  -> broker interaction
  -> journals, metrics, APIs, dashboard
```

## Authority boundaries

### 1. Market and ingest

Ingest owns data acquisition, validation, candle construction, and producer heartbeat publication.

### 2. Runtime context

Context services hydrate live state from Redis and recovery storage so the engine can reason from synchronized state.

### 3. Analysis

The Wolf pipeline can score, infer, and enrich, but it does not directly place orders.

### 4. Constitution

Layer 12 is the only component that may issue an executable verdict.

### 5. Execution

Execution services are blind executors. They honor approved commands and enforce expiry, cancel, and state-machine safety.

### 6. Operations and control surfaces

APIs, dashboards, and alerts consume system state, but they do not share the same authority level.

- Alerts are downstream notification consumers.
- Read APIs expose state and diagnostics.
- The dashboard is a private owner-operated control surface for diagnostics, transport coordination, and explicitly allowed operational actions.

The dashboard is NOT a constitutional trading authority and must never become a shadow strategy engine or verdict source.

Operational control is allowed only through documented backend paths that preserve governance, firewall, and execution boundaries.

## Relationship to existing references

For implementation-level detail, pair this overview with:

- `data-flow-final.md`
- `core/engine-dag-architecture.md`
- `infrastructure/deployment-baseline.md`
