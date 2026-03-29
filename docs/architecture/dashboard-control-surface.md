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
- manage transport/session/websocket coordination for the owner interface
- invoke operational APIs that remain within constitutional and execution boundaries

The dashboard may NOT:

- synthesize market verdicts
- override Layer 12 constitutional decisions
- bypass execution, governance, or compliance boundaries
- act as an alternate strategy engine
- mutate risk or execution state through undocumented side channels

## Position in the System

The dashboard is not a constitutional trading authority.

System role boundaries remain:

- `analysis/` thinks
- `constitution/` decides
- `execution/` executes
- `dashboard/` operates and observes
- `journal/` records

The dashboard is therefore an operational control surface, not a verdict authority.

## Owner-Only Model

This dashboard is private and owner-only.

Therefore:

- public-user login semantics are NOT the primary architecture
- browser-facing API key fallback is NOT allowed
- service/machine API keys must remain machine-only
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

## Proxy Boundary

The dashboard must not rely on overlapping backend access strategies.

One backend access path must be canonical.
Any temporary overlap must be documented as architecture debt and scheduled for removal.

## Health Boundary

Infrastructure health and dashboard status must not share ambiguous semantics.

- infra probes: `/healthz`, `/readyz`
- owner/operator status: separate dashboard-facing status surface

The dashboard may relay status, but must not blur the meaning of infra probe routes.

## Runtime Safety Rule

The dashboard may initiate owner-approved actions, but every such action must still pass through the proper backend authority chain.

The dashboard is allowed to control.
It is not allowed to decide constitutionally.

## Implementation Debt Policy

If implementation temporarily diverges from this document:

- the divergence must be explicitly documented
- the affected boundary must be named
- the cleanup path must be tracked as architecture debt
