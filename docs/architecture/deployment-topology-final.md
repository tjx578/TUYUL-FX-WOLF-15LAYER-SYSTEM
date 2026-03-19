---
title: TUYUL-FX Deployment Topology Final
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - deployment
  - topology
  - production
  - observability
  - governance
path: docs/architecture/deployment-topology-final.md
---

**Document path:** `docs/architecture/deployment-topology-final.md`  
**Status:** Official Architecture Reference  
**Scope:** Production deployment topology, platform boundaries, runtime service roles, freshness/readiness behavior, and execution-path deployment rules  
**Applies to:** Vercel dashboard, Railway services, Redis, PostgreSQL, orchestrator, execution bridge, EA connectivity, observability stack

---

## 1. Purpose per Layer

### 1.1 Why This Deployment Topology Exists

This document defines how TUYUL-FX is deployed in production and how deployed services map onto the architecture package.

Its purpose is to:

- describe where each service runs
- define which deployment component owns which operational role
- keep topology aligned with authority boundaries and stale-data governance
- ensure that runtime deployment choices do not violate constitutional constraints

This document complements, but does not replace:

- `docs/architecture/overview.md`
- `docs/architecture/data-flow-final.md`
- `docs/architecture/authority-boundaries.md`
- `docs/architecture/stale-data-guardrails.md`
- `docs/architecture/execution-feedback-loop.md`

### 1.2 Topology Overview

The production topology is organized into the following planes:

- edge / operator plane
- API / control plane
- analysis plane
- coordination / execution plane
- state / persistence plane
- observability / governance plane

These planes may share infrastructure platforms in the early deployment phase, but their architectural responsibilities remain distinct.

### 1.3 Edge / Operator Plane

This plane provides operator-facing access and frontend delivery.

Primary components:

- Vercel-hosted Next.js dashboard
- authenticated browser clients
- approved WebSocket / SSE / REST fallback transport consumers

Its purpose is to:

- present backend truth to operators
- expose dashboard views for signals, portfolio, settings, and system health
- consume live or fallback transport channels without becoming a decision authority

### 1.4 API / Control Plane

This plane exposes authenticated backend interfaces.

Primary components:

- `wolf15-api`
- FastAPI app server
- auth middleware
- rate limiting middleware
- portfolio/settings/read-model endpoints
- operational flow APIs such as take-signal and status endpoints

Its purpose is to:

- authenticate users and machine clients
- expose controlled read/write APIs
- publish current backend state to the dashboard
- broker control-plane requests without becoming market-decision authority

### 1.5 Analysis Plane

This plane hosts the market reasoning stack.

Primary components:

- `wolf15-engine`
- runtime context assembly
- freshness and governance gates
- Wolf constitutional DAG
- Layer 12 final verdict authority
- optional post-verdict veto overlays that remain subordinate to Layer 12 authority

Its purpose is to:

- transform market context into validated decision outputs
- enforce constitutional and freshness legitimacy before verdict publication
- remain the sole source of trade verdict truth

### 1.6 Coordination / Execution Plane

This plane coordinates post-verdict operational flow and execution.

Primary components:

- `wolf15-orchestrator`
- `wolf15-execution`
- `wolf15-allocation`
- EA bridge connectivity
- execution intent routing and reconciliation

Its purpose is to:

- coordinate downstream actions after verdict publication
- enforce operational legality and compliance mode interaction
- transmit order intent only after proper approval paths
- reconcile execution feedback into journal and risk truth

### 1.7 State / Persistence Plane

This plane stores operational and durable system state.

Primary components:

- Railway Redis
- Railway PostgreSQL

Its purpose is to:

- distribute low-latency state
- preserve candle history, latest state, and heartbeats
- store durable journals, settings versions, audit records, and recovery snapshots
- support runtime recovery without changing authority ownership

### 1.8 Observability / Governance Plane

This plane provides health, metrics, diagnostics, and operational truth about whether the system is safe to operate.

Primary components:

- Prometheus-compatible metrics
- readiness and health endpoints
- freshness and heartbeat diagnostics
- compliance mode status
- logs and incident diagnostics

Its purpose is to:

- surface whether the system is alive, fresh, degraded, or unsafe
- distinguish process liveness from decision legitimacy
- support operators and automation without fabricating business truth

---

## 2. Source of Truth per Komponen

### 2.1 Dashboard / Edge Truth

- the dashboard is the source of truth only for current frontend presentation state
- it is not the source of truth for market direction, execution success, or governance legitimacy
- backend APIs remain authoritative for data shown in the UI

### 2.2 API / Control Truth

- `wolf15-api` is the source of truth for published backend-facing read models and authenticated control responses
- it may aggregate state from engine, orchestrator, execution, Redis, and PostgreSQL
- it must not invent or override analytical truth from the engine

### 2.3 Analysis Truth

- `wolf15-engine` is the source of truth for runtime analytical state
- Layer 12 is the sole source of truth for final trade verdicts
- freshness and governance inside the analysis path determine whether a verdict is legitimate for downstream use

### 2.4 Coordination Truth

- `wolf15-orchestrator` is the source of truth for downstream workflow coordination after verdict publication
- it is not the source of truth for the verdict itself
- it must preserve provenance and hold status coming from upstream authority

### 2.5 Execution Truth

- `wolf15-execution` and downstream broker/EA acknowledgements are the source of truth for execution status transitions
- actual fill/reject/cancel outcomes come from execution feedback, not from UI assumptions or intent transmission alone

### 2.6 Allocation Truth

- `wolf15-allocation` is the source of truth for allocation/distribution constraints and account-aware sizing coordination
- it must not become an alternative strategy or verdict authority

### 2.7 Redis Truth

- Redis is the source of truth for low-latency operational state distribution
- it stores latest tick/candle state, heartbeat keys, recent history, and transient coordination state
- Redis is not the final source of truth for durable audit history

### 2.8 PostgreSQL Truth

- PostgreSQL is the source of truth for durable persistence: audit, journal, ledger, versioned settings, and recovery snapshots
- it is authoritative for post-restart durable reconstruction where Redis is missing or insufficient

### 2.9 Observability Truth

- metrics and health endpoints are the source of truth for monitored service health, latency, and freshness signals as published by backend services
- metrics consumers must not reinterpret process liveness as decision legitimacy without freshness and governance corroboration

---

## 3. Failure Modes

### 3.1 Edge / Dashboard Failure Modes

- frontend remains reachable while backend freshness is degraded
- WebSocket disconnect causes stale UI if fallback transport is absent or misconfigured
- token storage or frontend security issues expose operator credentials
- UI displays transport health without exposing producer or freshness truth

### 3.2 API / Control Plane Failure Modes

- API service restart disrupts dashboard access while engine state still exists
- rate limiting protects endpoints but hides coordination bottlenecks if buckets are too coarse
- control-plane endpoints are reachable while backend dependencies are stale or unhealthy
- write endpoints succeed without sufficient audit/governance enforcement

### 3.3 Analysis Plane Failure Modes

- engine continues using stale-preserved state as if it were fresh
- verdicts are emitted while producer heartbeat is absent
- warmup is incomplete but analysis still proceeds
- post-verdict overlays behave as though they are independent authorities

### 3.4 Coordination / Execution Failure Modes

- orchestrator mutates or reinterprets verdict intent
- execution attempts occur without proper legality approval
- duplicate intent transmission occurs under retry ambiguity
- EA bridge connectivity exists but acknowledgement/fill truth is not synchronized back

### 3.5 State Plane Failure Modes

- Redis key expiry causes stale to look like absent
- PostgreSQL recovery snapshots lag reality too far
- Redis and PostgreSQL disagree about current operational state
- rate-limit or orchestration state in Redis becomes inconsistent during failover or restart

### 3.6 Observability Failure Modes

- `/healthz` returns healthy while all symbols are stale
- `/readyz` is based on process liveness rather than producer freshness and warmup sufficiency
- `/metrics` is reachable but not scoped safely for machine access
- incident diagnostics omit whether the problem is transport, producer, freshness, or execution ambiguity

### 3.7 EA Bridge Failure Modes

- EA receives ambiguous or duplicate command state
- local MT5 host path becomes less observable than central backend services
- bridge reconnects but old execution ambiguity is not reconciled
- execution path exists while governance or compliance mode should block it

---

## 4. Recovery Behavior

### 4.1 Platform Recovery Principle

Recovery of a deployed process does not automatically restore operational legitimacy.

A service may recover transport, restart successfully, or become reachable while still being unfit for normal trading flow.

### 4.2 Dashboard Recovery

- the dashboard may reconnect through transport ladder order: WebSocket -> SSE -> REST polling
- frontend recovery must preserve backend freshness class and heartbeat age
- UI reconnection must not be treated as proof that engine freshness has recovered

### 4.3 API Recovery

- API restarts must restore authenticated control and read-model access without changing authority ownership
- readiness must depend on backend freshness/governance dependencies where appropriate, not solely on process startup success
- write paths must remain audit-safe after restart

### 4.4 Analysis Recovery

- engine startup must hydrate from Redis first and PostgreSQL recovery snapshots if necessary
- recovered state must remain classified until freshness is re-established
- no normal decision flow may resume until warmup sufficiency and freshness legitimacy are satisfied

### 4.5 Coordination Recovery

- orchestrator recovery must restore coordination state from authoritative backend records or Redis keys as designed
- it must not regenerate or reinterpret verdicts independently
- command/state channels must resume without creating duplicate post-verdict actions

### 4.6 Execution Recovery

- execution services must reload ambiguous pending intents and reconcile them against downstream broker/EA truth
- recovery must distinguish intent sent, acknowledged, rejected, partially filled, filled, cancelled, and unresolved states
- unresolved execution ambiguity must remain visible and conservative hold behavior may be required

### 4.7 State Recovery

- Redis may recover low-latency operational state and fanout first
- PostgreSQL must remain the durable fallback for journals, audit, and recovery snapshots
- stale-preserved state must remain visible rather than being destructively erased

### 4.8 Observability Recovery

- metrics and health visibility should return as early as possible after restart
- however, readiness must not report safe operation until freshness, warmup, and critical dependencies are restored
- operators must be able to distinguish `LIVE`, `DEGRADED_BUT_REFRESHING`, `STALE_PRESERVED`, `NO_PRODUCER`, and `NO_TRANSPORT`

---

## 5. Enforcement / Hold Rules

### 5.1 Constitutional Rule

- no deployment decision, platform choice, or operational shortcut may replace the constitutional authority of Layer 12
- dashboard, API, orchestrator, execution bridge, and EA components are forbidden from fabricating a trade verdict

### 5.2 Freshness Rule

- process liveness is insufficient for operational trust
- freshness classification and producer heartbeat must influence readiness and hold behavior
- stale-preserved state may support continuity and diagnosis, but not silent normal-mode trading

### 5.3 Orchestrator Rule

- `wolf15-orchestrator` coordinates flow only
- it may dispatch, sequence, and monitor post-verdict actions
- it may not mutate verdict authority or invent strategy direction

### 5.4 Execution Rule

- `wolf15-execution` and the EA bridge may transmit order intent only after valid upstream authority and legality checks
- acknowledged/fill truth must flow back into journal and risk truth
- duplicate or ambiguous execution must trigger reconciliation, not blind retry

### 5.5 Allocation Rule

- `wolf15-allocation` may constrain account-aware routing, sizing, and portfolio policy
- it must not silently transform a verdict into a different strategic action

### 5.6 API / Dashboard Rule

- `wolf15-api` publishes backend truth; the dashboard consumes it
- frontend transport recovery must not override backend freshness classification
- no UI shortcut may bypass audit, settings governance, or kill-switch/compliance constraints

### 5.7 Metrics and Health Rule

- `/healthz` may indicate process liveness
- `/readyz` and equivalent readiness logic must incorporate freshness, dependency health, and warmup sufficiency
- `/metrics` access must be protected with machine-appropriate auth or equivalent deployment safeguards

### 5.8 Deployment Security Rule

- production secrets must remain platform-managed and not hard-coded
- Redis must use authenticated TLS connections
- Postgres must use managed credentials and least-privilege access
- frontend token handling must be paired with strong CSP and dependency hygiene because local token storage increases XSS sensitivity

### 5.9 EA Bridge Rule

- the primary execution path must be explicitly chosen and documented
- if EA bridge is local-host based, observability and reconnect guarantees must be made explicit
- if EA bridge is centrally hosted, transport trust and execution proximity constraints must be documented explicitly

### 5.10 Hold Rule

The system must force or preserve `HOLD` behavior when any of the following conditions apply:

- producer heartbeat absent beyond tolerance
- freshness legitimacy lost
- warmup insufficient
- orchestrator/execution ambiguity unresolved
- compliance mode blocks new execution intents
- critical dependency recovery incomplete

---

## 6. Reference Production Topology

```text
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 USERS / OPERATORS / EA                                   │
└───────────────────────┬──────────────────────────────────────────────┬────────────────────┘
                        │                                              │
                 HTTPS / WSS                                    MQL5 EA / MT5 Host
                        │                                              │
                        ▼                                              ▼
┌───────────────────────────────┐                  ┌───────────────────────────────────────┐
│ Edge / Operator Plane         │                  │ Execution Edge                        │
│ Vercel - Dashboard            │                  │ EA Bridge (Railway or local host)     │
│ • Next.js frontend            │                  │ • receives approved execution intent   │
│ • JWT-authenticated operator  │                  │ • reports ack / fill / reject         │
│ • WS / SSE / REST fallback    │                  │ • never creates strategy direction     │
└───────────────┬───────────────┘                  └──────────────────┬────────────────────┘
                │ REST / WS / SSE                                      │ execution feedback
                ▼                                                      │
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ API / Control Plane - Railway                                                             │
│ wolf15-api (FastAPI / Uvicorn)                                                            │
│ • auth, CORS, security headers, rate limiting, Prometheus middleware                      │
│ • published backend truth for dashboard and control-plane APIs                            │
│ • take-signal, status, settings, portfolio, health, metrics                               │
│ • NOT verdict authority                                                                    │
└───────────────────────┬──────────────────────────────────────────────┬────────────────────┘
                        │                                              │
                        ▼                                              ▼
┌──────────────────────────────────────────────┐     ┌─────────────────────────────────────┐
│ Analysis Plane - Railway                     │     │ Coordination / Execution Plane       │
│ wolf15-engine                               │     │ Railway services                      │
│ • RedisConsumer / LiveContextBus            │     │ • wolf15-orchestrator                │
│ • freshness / governance gates              │     │ • wolf15-execution                   │
│ • Wolf Constitutional DAG                   │     │ • wolf15-allocation                  │
│ • Layer 12 = SOLE verdict authority         │     │ • legality / dispatch / reconciliation│
└───────────────────────┬──────────────────────┘     └──────────────────┬──────────────────┘
                        │                                              │
                        └──────────────────┬───────────────────────────┘
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ State / Persistence Plane - Railway Managed                                               │
│ Redis                                                                                     │
│ • latest state / heartbeat / candle history / pub-sub / rate-limit / orchestration state │
│ PostgreSQL                                                                                │
│ • config / audit / journal / ledger / recovery snapshots                                 │
└───────────────────────┬──────────────────────────────────────────────┬────────────────────┘
                        │                                              │
                        ▼                                              ▼
┌──────────────────────────────────────────────┐     ┌─────────────────────────────────────┐
│ Observability / Governance Plane             │     │ Health / Freshness Outputs          │
│ • Prometheus metrics                         │     │ • /healthz process liveness         │
│ • logs / incident diagnostics                │     │ • /readyz freshness-aware readiness │
│ • compliance mode state                      │     │ • LIVE / DEGRADED / STALE states    │
└──────────────────────────────────────────────┘     └─────────────────────────────────────┘
```

---

## 7. Baseline Environment and Platform Notes

### 7.1 Backend Platform Notes

Recommended baseline environment variables include:

- auth secrets and token lifetime
- explicit CORS origin allowlist
- Redis TLS URL and distributed rate-limit backend
- PostgreSQL async connection URL
- API domain and forced HTTPS
- orchestrator channel/state keys and heartbeat intervals

These values must remain environment-managed and not be hard-coded in application logic.

### 7.2 Frontend Platform Notes

Frontend must set API and WebSocket base URLs explicitly.

Recommended baseline:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_WS_BASE_URL`
- explicit timezone
- refresh intervals for verdicts, context, and health where polling fallback applies

The frontend must not derive WebSocket URL implicitly from HTTP URL by string replacement.

### 7.3 Railway Operational Notes

- Railway cron schedules operate in UTC and must be documented accordingly
- shared Redis should be used for distributed rate limiting when multiple instances are deployed
- service restarts must be evaluated against freshness/readiness, not only container liveness

### 7.4 EA Connectivity Notes

The primary EA bridge pattern must be documented as one of:

- centrally hosted EA bridge with explicit execution connectivity assumptions
- local-host EA bridge with explicit observability and reconnect expectations

During rollout, mixed-mode support may exist, but the primary supported topology must be unambiguous to operators.

---

## 8. Cross-Reference Index

- See `docs/architecture/overview.md` for architecture package navigation and service-document mapping
- See `docs/architecture/data-flow-final.md` for end-to-end realtime data movement and freshness-aware runtime flow
- See `docs/architecture/authority-boundaries.md` for decision legitimacy and role separation
- See `docs/architecture/stale-data-guardrails.md` for freshness classes, stale-preserved handling, and hold rules
- See `docs/architecture/execution-feedback-loop.md` for verdict-to-intent-to-fill reconciliation and execution truth

---

## Closing Principle

A deployment topology is correct only when infrastructure placement does not blur authority, and service availability does not masquerade as trading legitimacy.

TUYUL-FX production deployment must therefore preserve four truths at all times:

- who decides,
- who coordinates,
- who executes,
- and whether the system is truly fresh enough to be trusted.
