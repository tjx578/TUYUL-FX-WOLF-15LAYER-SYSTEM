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
  -> orchestration and execution gating
  -> output distribution
  -> dashboard and operator surfaces
```

## Non-negotiable rules

- Upstream feeds provide observations, not trade authority.
- Ingest validates and normalizes data, but does not decide trades.
- Redis is the operational runtime substrate, not constitutional trading authority.
- Layer 12 remains the sole trade verdict authority.
- Governance and firewall layers may block or pause downstream execution, but may not invent market verdicts.
- The dashboard is a private owner control surface that consumes state, diagnostics, and transport outputs.
- The dashboard may initiate documented owner-scoped operational actions, but it must never become a shadow execution or verdict path.

## Dashboard boundary

The dashboard is not a public-user application surface.
It is a private owner-operated operational interface.

This means:

- browser/session behavior must follow an owner-scoped design
- machine/service credentials must not be reused as browser auth
- dashboard actions must remain downstream of backend authority boundaries
- health/status routes must not blur infrastructure probe semantics

## Promotion rule

Any future changes to flow semantics must first be reflected in `data-flow-final.md`, then summarized here only after the change is accepted as system truth.
