# Dashboard Control Surface

**Status:** Canonical
**Scope:** Owner-operated dashboard authority, auth boundary, and runtime limitations.

## Purpose

This document defines the dashboard as a private owner control surface.

The dashboard is NOT a public multi-user product.
It is an owner-operated operational interface for visibility, diagnostics, controlled actions, transport orchestration, and explicit owner-scoped system interaction.

## Core Rule

The dashboard may:

- consume system state
- display health, diagnostics, and runtime context
- initiate owner-scoped control actions that are explicitly exposed by backend services
- manage transport, session, and websocket coordination for the owner interface
- invoke operational APIs that remain within constitutional and execution boundaries

The dashboard may NOT:

- synthesize market verdicts
- override Layer 12 constitutional decisions
- bypass execution, governance, or compliance boundaries
- act as an alternate strategy engine
- mutate risk or execution state through undocumented side channels

## Auth Model

This dashboard is private and owner-only.

Therefore:

- public-user login semantics are NOT the primary architecture
- browser-facing API key fallback is NOT allowed
- machine/service API keys must remain machine-only
- owner identity must be explicit and bounded (`DASHBOARD_MODE=owner`)
- websocket/browser auth must follow a dedicated dashboard contract

## Key Rotation Policy

API keys managed through `APIKeyManager` follow an explicit rotation protocol:

- `ACTIVE` keys validate normally.
- `ROTATING` keys are only valid during a bounded grace window (default 300 s) measured from the `rotated_at` timestamp.
- `ROTATING` keys with no `rotated_at` timestamp are rejected immediately.
- `REVOKED` keys are rejected unconditionally.
- Key material is persisted atomically (write-then-rename) to prevent corruption.

## Auth Boundary

The following auth concerns must remain separated:

### 1. Owner dashboard auth

Used only for the private operator interface.

### 2. Machine / observability auth

Used for `/metrics`, `/healthz`, `/readyz`, and machine-to-machine probes.

### 3. Internal service auth

Used between backend services where required.

These surfaces must not be conflated.

## Proxy Rule

The dashboard uses a single canonical backend access path.

All browser-side REST traffic flows through the runtime proxy at
`/api/proxy/[...path]` (Next.js route handler). Build-time rewrites have
been removed (P4) — the proxy reads `INTERNAL_API_URL` at request time,
eliminating stale-env bugs.

Edge middleware injects the session cookie as an `Authorization` header
only for `/api/proxy/` requests.

Internal Next.js routes (`/api/set-session`, `/api/auth/ws-ticket`) are
NOT proxied — they handle their own auth.

## Health Rule

Infrastructure health and dashboard operator status are **semantically separate**.

| Surface | Path | Auth | Purpose |
|---------|------|------|---------|

| Liveness | `/healthz`, `/health` | none | Process alive? Infra probes. |
| Readiness | `/readyz` | machine-key | Safe to serve traffic? |
| Operator status | `/api/v1/status` | JWT | Dashboard rich diagnostics (16+ fields). |
| Deep diagnostics | `/api/v1/status/full` | JWT | Redis, Postgres, config, engine, lockdown. |

The dashboard calls `/api/v1/status` for operator diagnostics.
Heartbeat / liveness pings (multiplexer, DataStreamDiagnostic) use `/healthz`.
Docker / Railway / k8s probes use `/healthz` (liveness) and `/readyz` (readiness).

The dashboard must not blur the meaning of infra probe routes.

## Constitutional Rule

The dashboard is allowed to control.
It is not allowed to decide constitutionally.

Layer 12 remains the sole trade verdict authority.
