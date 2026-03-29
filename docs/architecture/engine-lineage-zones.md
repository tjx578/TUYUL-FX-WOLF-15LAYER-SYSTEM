# Engine Lineage — Zone Model

**Status:** Historical-technical reference
**Scope:** Zone-based lineage of the engine and constitutional pipeline evolution.

## Purpose

This document preserves the historical zone-based architecture model used to describe the end-to-end trading engine lineage.

It remains useful for understanding:

- ingest flow
- context formation
- analysis trigger flow
- constitutional pipeline staging
- execution handoff
- fan-out and observability lineage

## Historical Zone Model

- Zone A — ingest and filtering
- Zone B — tick buffering and candle construction
- Zone C — live context and event bus
- Zone D — analysis loop trigger
- Zone E — constitutional pipeline and overlays
- Zone F — output fan-out
- Zone G — execution path

## Important Boundary Rule

This zone model is valuable for engine reasoning and lineage understanding,
but it is NOT the single source of truth for current runtime service topology.

For current runtime truth, use:

- `runtime-topology-current.md`
- `deployment-railway.md`
- `dashboard-control-surface.md`

## Storage Namespace

Read-model modules previously located in the `dashboard.*` namespace have been migrated to `storage.*` as the canonical location.
The deprecated `dashboard/price_feed.py` and `dashboard/trade_ledger.py` shims have been deleted.
Boundary tests enforce that no production code imports from the retired namespace.

## Why this file exists

The historical zone model remains useful for:

- tracing engine ancestry
- onboarding contributors to the pipeline mental model
- understanding V11 and related overlays in context
- preserving architecture history without forcing legacy assumptions onto current topology

## Canonical Boundary Reminder

Historical lineage does not override current constitutional rules:

- Layer 12 remains the sole verdict authority
- execution remains execution-only
- dashboard remains a private owner control surface, not a constitutional authority
