---
title: TUYUL-FX Repo Migration Plan
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - migration
  - refactor
  - implementation-plan
  - priorities
path: docs/architecture/repo-migration-plan.md
---

# TUYUL-FX Repo Migration Plan

**Document path:** `docs/architecture/repo-migration-plan.md`  
**Status:** Official Implementation Plan  
**Scope:** Incremental migration of the existing TUYUL-FX repository toward the target architecture package without creating a new repository  
**Applies to:** Existing codebase, service boundaries, runtime contracts, stale-data hardening, execution-path closure, API/control-plane alignment

---

## 1. Purpose per Layer

### 1.1 Why This Migration Plan Exists
The architecture package is now defined. This migration plan translates that architecture into a practical refactor sequence for the existing repository.

Its purpose is to:
- avoid a destructive rewrite
- keep the current repository as the primary codebase
- prioritize the highest-risk operational defects first
- convert architecture documents into concrete service/file changes
- stage rollout so the system remains observable and testable while improving

This plan assumes **in-place migration**, not a greenfield rebuild.

### 1.2 Migration Philosophy
All migration work must preserve five principles:
- no new authority may appear accidentally
- stale-data ambiguity must be reduced before adding sophistication
- execution truth must remain more important than optimistic UI or intent state
- append-only journal and audit history must be preserved
- each phase must leave the repository in a deployable and diagnosable condition

### 1.3 Priority Model
This plan uses three priorities:

- **P0** -- stop-the-bleeding changes  
  Mandatory before trusting live operation again.

- **P1** -- architecture hardening changes  
  Required to align runtime behavior with the new target architecture.

- **P2** -- structural optimization and expansion  
  Improves scale, clarity, and maintainability after safety-critical work is done.

---

## 2. Source of Truth per Komponen

### 2.1 Architecture Truth
The target architectural truth is defined by:
- `docs/architecture/overview.md`
- `docs/architecture/data-flow-final.md`
- `docs/architecture/authority-boundaries.md`
- `docs/architecture/stale-data-guardrails.md`
- `docs/architecture/execution-feedback-loop.md`
- `docs/architecture/deployment-topology-final.md`
- `docs/architecture/service-contracts.md`

### 2.2 Migration Truth
This document is the source of truth for implementation sequencing.

If existing code conflicts with the architecture package, the migration plan determines the order in which those conflicts are corrected.

### 2.3 Repository Truth
The existing repository remains the production codebase and migration target.

No parallel "replacement repo" should be treated as a competing source of truth.

---

## 3. Failure Modes This Plan Must Eliminate

### 3.1 Freshness / Stale Failure Modes
- ingest producer crashes while engine continues consuming stale-preserved state
- short TTL makes stale data disappear and look like no-data
- readiness reflects process liveness instead of producer freshness
- dashboard shows degraded transport without distinguishing backend freshness truth

### 3.2 Authority Failure Modes
- orchestration or allocation logic mutates or replaces verdict authority
- API or dashboard behavior implies decision authority it does not own
- background workers become hidden state mutation channels

### 3.3 Execution Failure Modes
- order intent is sent without complete legality and provenance chain
- ambiguous execution states are retried blindly
- fill/reject truth does not flow back into risk/journal state cleanly

### 3.4 Governance Failure Modes
- settings changes lack immutable audit and rollback discipline
- compliance mode changes are not evented or enforced consistently
- firewall checks are partial, unordered, or bypassable

### 3.5 Structural Failure Modes
- service roles remain mixed in a way that makes RCA difficult
- Redis/PostgreSQL ownership stays ambiguous
- old code paths continue to produce drift after new endpoints are added

---

## 4. Migration Phases and Recovery Behavior

### 4.1 Phase Ordering
Migration proceeds in this order:
1. P0 -- freshness, state machine, hold safety
2. P1 -- contracts, execution loop, control plane, audit-safe APIs
3. P2 -- service separation, optimization, and long-horizon topology cleanup

The system should remain deployable after each major phase.

### 4.2 Rollback Behavior
If a phase must be rolled back:
- code rollback must not delete append-only journal or audit history
- Redis destructive cleanup must be avoided unless state ownership is confirmed safe
- new event types may be disabled by feature flags if consumers lag behind
- analysis-only or shadow modes should be used before enforcing new blocking logic where possible

### 4.3 Feature Flag Guidance
Where practical, new behavior should be gated by feature flags or explicit config toggles for staged rollout, especially for:
- V11 veto enforcement
- frontend transport fallback ladder
- new readiness logic
- compliance auto-mode enforcement
- take-signal and firewall execution flow

---

## 5. P0 -- Stop-the-Bleeding Changes

### 5.1 Objective
Restore operational legitimacy by fixing the conditions that create zombie mode, stale ambiguity, and invalid startup/retry behavior.

### 5.2 Service-Level Changes

#### `wolf15-ingest`
**Goals:**
- fix startup/retry state machine
- ensure producer heartbeat exists and is reliable
- preserve stale state instead of deleting it too early
- strengthen fallback behavior

**Target changes:**
- replace invalid `SystemState.LIVE` usage with supported state model
- make same-state transitions no-op safe
- ensure retry paths call `reset()` where appropriate
- publish `wolf15:heartbeat:ingest`
- write `last_seen_ts` into latest tick/candle structures
- remove short freshness-defining TTL logic from latest tick semantics
- keep housekeeping TTL separate from freshness semantics

**Likely file targets:**
- `services/ingest/ingest_service.py`
- `services/ingest/*state*`
- `analysis/data_feed.py`
- `context/redis_context_bridge.py` or equivalent latest tick writer
- fallback scheduler files such as REST polling services

#### `wolf15-engine`
**Goals:**
- unify freshness classification
- stop treating hydrated stale data as fresh
- align hold behavior with freshness truth

**Target changes:**
- standardize freshness thresholds across engine/runtime/data-quality gates
- classify runtime state into approved freshness classes
- fail readiness when producer freshness is not sufficient
- distinguish `STALE_PRESERVED` vs `NO_PRODUCER` vs `NO_TRANSPORT`
- prevent normal-mode analysis when warmup/freshness minimums fail

**Likely file targets:**
- `context/live_context_bus.py`
- `analysis/data_quality_gate.py`
- `analysis/data_feed.py`
- engine readiness/health endpoints
- any warmup or runtime status modules

#### `wolf15-api`
**Goals:**
- expose backend freshness truth cleanly
- prepare dashboard to stop lying about stale state

**Target changes:**
- add/extend freshness-aware health/readiness endpoints
- expose producer heartbeat age and freshness status in system-state responses
- ensure dashboard read APIs do not infer freshness only from transport state

**Likely file targets:**
- `api_server.py`
- `app_factory.py`
- `api/routes/health*`
- `api/routes/system*`

#### Dashboard
**Goals:**
- stop equating WS disconnect with total backend failure
- surface freshness truth clearly

**Target changes:**
- implement transport ladder: WS -> SSE -> REST polling
- show explicit states: `LIVE`, `DEGRADED_BUT_REFRESHING`, `STALE_PRESERVED`, `NO_PRODUCER`, `NO_TRANSPORT`
- display last update timestamp and heartbeat age if exposed by backend

**Likely file targets:**
- `dashboard/nextjs/lib/websocket.ts`
- `dashboard/nextjs/hooks/useLivePipeline.ts`
- system status UI components

### 5.3 P0 Acceptance Criteria
- ingest no longer crash-loops due to invalid state transitions
- producer heartbeat is visible and queryable
- stale state remains inspectable after feed interruption
- readiness fails when producer freshness is invalid
- UI distinguishes transport failure from backend stale/no-producer conditions
- new-trade flow is blocked under hard stale/no-producer conditions

---

## 6. P1 -- Architecture Hardening Changes

### 6.1 Objective
Implement the missing operational contracts that make the system auditable, legality-gated, and execution-safe.

### 6.2 Service-Level Changes

#### `wolf15-api`
**Goals:**
- implement operational flow APIs and immutable governance surfaces
- provide account binding without violating constitutional boundaries

**Target changes:**
- add `POST /api/v1/execution/take-signal`
- add `GET /api/v1/execution/take-signal/{take_id}`
- add portfolio read endpoints (`global`, `account`, `trade detail`)
- add settings governance endpoints and rollback path
- add idempotency handling for take-signal and settings writes
- enforce immutable audit creation on settings mutations

**Likely file targets:**
- `api/routes/execution*`
- `api/routes/portfolio*`
- `api/routes/settings*`
- auth/authorization middleware for write controls
- API schemas / pydantic models / validators

#### Risk / Firewall Service or Module
**Goals:**
- create strict legality gate before execution
- encode ordered short-circuit firewall logic

**Target changes:**
- implement ordered checks: kill switch -> prop limits -> exposure -> concurrent trades -> news lock -> daily DD -> cooldown/session if enabled
- emit canonical firewall events and rejection codes
- persist immutable firewall result snapshots
- prevent executor call when any hard fail occurs

**Likely file targets:**
- risk module / compliance module / orchestrator command handlers
- event emission utilities
- persistence layer for firewall result records

#### `wolf15-orchestrator`
**Goals:**
- formalize orchestrator as coordinator only
- centralize downstream dispatch without mutating verdict authority

**Target changes:**
- make orchestrator consume verdict + legality + provenance, then dispatch approved actions
- enforce no action when hold or firewall reject is present
- use explicit command/state channels in Redis with documented semantics
- emit orchestration status events with preserved provenance

**Likely file targets:**
- `services/orchestrator/*`
- Redis channel consumers/producers
- orchestration state key handlers

#### `wolf15-execution`
**Goals:**
- close the loop from intent to ack/reject/fill/cancel
- remove ambiguity from retries

**Target changes:**
- create canonical execution intent record with correlation/idempotency key
- persist lifecycle states: intent created, placed, ack, reject, partial fill, fill, cancel, expiry, unresolved
- reconcile ambiguous states on restart or timeout
- feed execution truth back into journal/risk/read models

**Likely file targets:**
- execution service modules
- EA bridge adapter code
- persistence models for execution lifecycle
- journal append logic

#### `wolf15-allocation`
**Goals:**
- keep allocation as constraint layer, not verdict mutator

**Target changes:**
- make input/output contracts explicit
- ensure allocation publishes constraints or account-aware routing artifacts only
- prevent silent change of direction or constitutional state

**Likely file targets:**
- allocation service modules
- account state / exposure calculators

#### `wolf15-worker`
**Goals:**
- stop hidden mutation paths
- make async jobs contract-driven

**Target changes:**
- classify worker jobs as idempotent / deduplicated / non-retryable
- prevent worker tasks from mutating primary truth without explicit contract
- add job identifiers and retry semantics where absent

**Likely file targets:**
- worker job queue consumers
- background task handlers

#### PostgreSQL / Persistence Layer
**Goals:**
- support append-only journal, audit, rollback-safe settings, and execution lifecycle persistence

**Target changes:**
- add or normalize tables/models for:
  - take-signal binding
  - firewall result snapshots
  - execution intent lifecycle
  - settings version snapshots
  - immutable settings audit entries
  - compliance mode change events
- preserve append-only semantics where required

**Likely file targets:**
- ORM models / migrations
- repository layer modules

### 6.3 P1 Acceptance Criteria
- take-signal flow works with idempotency and immutable status history
- ordered risk firewall blocks illegal execution reliably
- executor never receives intent after reject
- execution lifecycle is queryable and reconciled
- settings writes are audited and rollback-safe
- orchestrator acts as coordinator, not pseudo-authority
- dashboard/API can explain whether non-execution came from verdict hold, firewall reject, or execution ambiguity

---

## 7. P2 -- Structural Optimization and Topology Cleanup

### 7.1 Objective
Reduce long-term coupling, clarify service deployment boundaries, and prepare for scale without changing constitutional truth.

### 7.2 Service-Level Changes

#### Deployment / Service Separation
**Goals:**
- reduce mixed-role runtime pressure
- align deploy topology with architecture planes

**Target changes:**
- separate `wolf15-api` from `wolf15-engine` if currently co-located beyond acceptable initial production constraints
- make `wolf15-orchestrator` a visibly independent service in deployment/runtime configs
- formalize observability and readiness per service, not only per monolith

**Likely file targets:**
- service entrypoints
- Railway service manifests / Procfiles / startup configs
- deployment scripts and environment docs

#### Dashboard / Operator UX
**Goals:**
- move from raw status surfaces to operator-grade truth surfaces

**Target changes:**
- enrich portfolio/trade detail views with gate breakdown, slippage, RR planned vs actual, journal timeline
- show compliance mode transitions and risk buffers clearly
- expose freshness class and execution ambiguity states in operator workflows

**Likely file targets:**
- Next.js pages/components for portfolio, trade detail, settings, system status

#### Event Contracts / Schemas
**Goals:**
- make event ownership machine-verifiable

**Target changes:**
- finalize canonical event schemas in `schemas/`
- validate event emission paths against schemas
- add producer ownership metadata and stable event IDs

**Likely file targets:**
- `schemas/*.json`
- event emission helpers
- contract tests

#### Advanced Hardening
**Goals:**
- improve scale and operational confidence

**Target changes:**
- refine rate limits to be actor-aware as needed
- isolate metrics auth from dashboard user auth
- add replay/forensic support for incident reconstruction
- add p99 latency monitoring for V11 and execution path where applicable

### 7.3 P2 Acceptance Criteria
- deployment topology matches documented service planes more closely
- service roles are easier to reason about independently during incidents
- operator UI reflects backend truth without authority leakage
- event contracts are validated and attributable
- observability covers freshness, execution ambiguity, and control-plane actions more comprehensively

---

## 8. File-by-File Suggested Starting Points

### 8.1 Likely P0 First-Touch Files
- `services/ingest/ingest_service.py`
- `context/live_context_bus.py`
- `analysis/data_feed.py`
- `analysis/data_quality_gate.py`
- `context/redis_context_bridge.py` or equivalent Redis writer
- `api_server.py`
- `app_factory.py`
- `dashboard/nextjs/hooks/useLivePipeline.ts`
- `dashboard/nextjs/lib/websocket.ts`

### 8.2 Likely P1 First-Touch Files
- `api/routes/execution*.py`
- `api/routes/portfolio*.py`
- `api/routes/settings*.py`
- `services/orchestrator/*`
- `services/execution/*`
- `services/allocation/*`
- `services/worker/*`
- persistence models / migrations / repositories
- event schema definitions under `schemas/`

### 8.3 Likely P2 First-Touch Files
- deployment manifests / startup configs / environment docs
- advanced dashboard pages/components
- metrics/auth separation modules
- event validation and replay tooling

These are starting points, not an exhaustive inventory. Exact paths should be confirmed against the current repo structure during implementation.

---

## 9. Enforcement / Hold Rules

### 9.1 Migration Safety Rule
No migration phase may loosen constitutional boundaries in order to gain implementation speed.

### 9.2 Hold Rule
If a partial migration leaves freshness, legality, or execution truth ambiguous, the system must remain conservative and preserve `HOLD` behavior where appropriate.

### 9.3 Audit Rule
No migration is allowed to convert append-only journal/audit history into mutable state without a documented and reviewed exception.

### 9.4 Compatibility Rule
New services/endpoints may be introduced incrementally, but they must coexist with old paths only long enough to migrate safely.

Long-term duplicate ownership is forbidden.

### 9.5 Decommission Rule
When a new path replaces an old one:
- the owner of truth must be explicit
- old path behavior must be disabled or removed after validation
- dashboards and operators must no longer rely on the deprecated path

---

## 10. Suggested Execution Order by Sprint

### Sprint A -- Freshness and Startup Integrity
- fix ingest state machine
- add producer heartbeat
- replace short TTL freshness semantics with `last_seen_ts`
- align freshness classification and readiness
- add dashboard stale/no-producer distinction

### Sprint B -- Operational Flow and Firewall
- implement take-signal API and status path
- implement risk firewall ordered checks and eventing
- persist immutable firewall results
- wire orchestrator dispatch off approved flow only

### Sprint C -- Execution Lifecycle Closure
- add execution intent persistence and correlation IDs
- implement ack/reject/fill/cancel reconciliation
- feed execution truth back into API/journal/read models

### Sprint D -- Governance and Settings
- implement settings governance endpoints
- add immutable audit + rollback snapshots
- add compliance mode automation and eventing

### Sprint E -- Topology Cleanup and Hardening
- separate services where needed
- tighten metrics auth and observability
- validate event schemas and replay/forensic support
- improve operator UX around portfolio, trade detail, and system truth

---

## 11. Cross-Reference Index

- See `docs/architecture/overview.md` for documentation map and onboarding order
- See `docs/architecture/data-flow-final.md` for runtime data movement and freshness architecture
- See `docs/architecture/authority-boundaries.md` for decision legitimacy constraints
- See `docs/architecture/stale-data-guardrails.md` for stale classification and anti-zombie rules
- See `docs/architecture/execution-feedback-loop.md` for post-verdict execution truth
- See `docs/architecture/deployment-topology-final.md` for runtime plane and platform layout
- See `docs/architecture/service-contracts.md` for cross-service ownership and retry rules

---

## Closing Principle

The correct migration path is not the one that changes the most code fastest.

It is the one that removes ambiguity first, restores legitimate system truth second, and only then expands capability on top of a safer foundation.
