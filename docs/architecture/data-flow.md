# Data Flow

**Status:** Canonical
**Purpose:** Define the production data path from upstream providers to operator-facing outputs.

## Source document

The detailed official reference remains `docs/architecture/data-flow-final.md`.
This file exists to make the architecture taxonomy explicit and stable.

## Production flow

```text
External providers
  -> ingest authority
  -> Redis durability and fanout
  -> engine context and recovery
  -> freshness and quality governance
  -> Wolf analysis and constitutional DAG
  -> output distribution
  -> dashboard and operator consumers
```

## Non-negotiable rules

- Upstream feeds provide observations, not trade authority.
- Ingest validates and normalizes data, but does not decide trades.
- Redis is the operational runtime substrate, not constitutional trading authority.
- Layer 12 remains the sole trade verdict authority.
- Dashboard surfaces state and diagnostics only; it must never become a shadow execution path.

## Promotion rule

Any future changes to flow semantics must first be reflected in `data-flow-final.md`, then summarized here only after the change is accepted as system truth.
