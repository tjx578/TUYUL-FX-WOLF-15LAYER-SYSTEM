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
- owner identity must be explicit and bounded
- websocket/browser auth must follow a dedicated dashboard contract

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

The dashboard must not rely on overlapping backend access strategies.

One backend access path must be canonical.
Any temporary overlap must be documented as architecture debt and scheduled for removal.

## Health Rule

Infrastructure health and dashboard status must not share ambiguous semantics.

- infra probes: `/healthz`, `/readyz`
- owner/operator status: separate dashboard-facing status surface

The dashboard may relay status, but must not blur the meaning of infra probe routes.

## Constitutional Rule

The dashboard is allowed to control.
It is not allowed to decide constitutionally.

Layer 12 remains the sole trade verdict authority.
