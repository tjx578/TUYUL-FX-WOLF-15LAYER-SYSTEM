# System Overview

**Status:** Canonical overview
**Scope:** End-to-end understanding of the TUYUL FX Wolf 15-layer system.

## Purpose

This document explains how the full system is separated into authorities so that analysis, governance, execution, and owner operations do not collapse into one unsafe surface.

The dashboard is part of owner operations.
It is not part of constitutional decision authority.

## End-to-end model

```text
Market data and macro events
  -> ingest and normalization
  -> context hydration and freshness checks
  -> Wolf analytical pipeline
  -> Layer 12 constitutional verdict
  -> governance and orchestration gates
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

### 5. Governance and orchestration

Governance and orchestration determine whether downstream operational flow may continue.

They may:

- veto
- pause
- degrade
- hold
- coordinate downstream actions

They may NOT:

- synthesize market direction
- replace Layer 12 as trade verdict authority

### 6. Execution

Execution services are blind executors. They honor approved commands and enforce expiry, cancel, and state-machine safety.

### 7. Operations and control surfaces

APIs, dashboards, and alerts consume system state, but they do not share the same authority level.

- Alerts are downstream notification consumers.
- Read APIs expose state and diagnostics.
- The dashboard is a private owner-operated control surface for diagnostics, transport coordination, and explicitly allowed operational actions.

The dashboard is NOT a constitutional trading authority and must never become a shadow strategy engine or verdict source.

Operational control is allowed only through documented backend paths that preserve governance, firewall, and execution boundaries.

## Canonical rules

- Layer 12 remains the sole trade verdict authority.
- Governance may veto or pause flow, but may not invent verdicts.
- Execution may execute, cancel, and expire, but may not decide direction.
- The dashboard may operate and observe, but may not become an undocumented execution path.
- Machine auth, owner dashboard auth, and internal service auth must remain distinct.
- Deprecated shims (dashboard/price_feed, dashboard/trade_ledger) have been retired. All read-model imports use the canonical `storage.*` namespace.
- API key rotation requires an explicit grace policy; keys in `ROTATING` status are rejected after the grace window or if no `rotated_at` timestamp exists.
- State snapshots must read all fields within a single critical section to prevent torn reads.

## Relationship to existing references

For implementation-level detail, pair this overview with:

- `data-flow-final.md`
- `runtime-topology-current.md`
- `dashboard-control-surface.md`
- `engine-lineage-zones.md`
- `deployment-railway.md`
- `core/engine-dag-architecture.md`
