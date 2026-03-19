---
title: TUYUL-FX Migration Backlog P2
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - migration
  - backlog
  - p2
  - topology
  - hardening
  - observability
path: docs/architecture/migration-backlog-p2.md
---

 TUYUL-FX Migration Backlog P2

**Document path:** `docs/architecture/migration-backlog-p2.md`  
**Status:** Official Execution Backlog  
**Scope:** Structural cleanup, topology alignment, event/schema hardening, observability upgrades, and operator UX improvement  
**Applies to:** deployment topology, service separation, event contracts, observability stack, advanced dashboard/read-model improvements

---

## 1. Purpose per Layer

### 1.1 Goal of P2

P2 turns a safer and contract-driven system into a cleaner, more scalable, and more diagnosable one.

The objective is to reduce long-term coupling and make the deployment/runtime topology more closely match the documented architecture planes.

### 1.2 P2 Architectural Focus

P2 is where the system becomes easier to reason about under load, during incidents, and across team boundaries.

The focus is on:

- service separation where roles are still overly mixed
- event schema enforcement and ownership clarity
- observability hardening
- deployment/runtime cleanup
- richer operator-facing truth surfaces
- replay/forensic readiness where feasible

### 1.3 P2 Exit Condition

P2 is complete only when:

- service planes are cleaner and easier to reason about
- event ownership and schemas are machine-checkable
- dashboard/operator views expose backend truth without ambiguity
- observability can distinguish freshness, legality, and execution ambiguity clearly

---

## 2. Source of Truth per Komponen

### 2.1 P2 Truth Sources

- deployment/runtime topology truth -> deployment manifests + `deployment-topology-final.md`
- event ownership truth -> `service-contracts.md` + canonical event schemas
- backend read-model truth -> `wolf15-api` aggregating owned sources
- operator/system observability truth -> metrics/logs/health endpoints with explicit freshness semantics

### 2.2 P2 Non-Goals

P2 is not the place to postpone P0/P1 safety work.

No P2 optimization may weaken:

- freshness governance
- constitutional authority
- firewall legality ordering
- execution reconciliation discipline
- append-only journal/audit guarantees

---

## 3. Failure Modes Being Eliminated

- API and engine remain too tightly coupled to scale or debug cleanly
- orchestrator exists logically but remains operationally invisible in deployment/runtime layout
- event payloads drift because producers are not schema-validated
- metrics exist but cannot distinguish process health from operational legitimacy
- dashboard surfaces remain too thin for operator-grade trade/risk diagnosis
- RCA still depends on tribal knowledge rather than explicit runtime truth

---

## 4. Recovery Behavior

### 4.1 P2 Recovery Principle

P2 recovery must improve clarity, not just uptime.

A system that restarts cleanly but remains hard to diagnose is still operationally weak.

### 4.2 P2 Rollout Guidance

P2 changes should be staged in a way that avoids unnecessary disruption:

- deploy service separation only after contract boundaries are already stable
- introduce schema validation in monitor/warn mode if necessary before hard enforcement
- enrich operator UI after backend truth surfaces are already reliable

---

## 5. Enforcement / Hold Rules

- service separation must not create new hidden authority
- observability improvements must preserve existing security boundaries
- operator UX enhancements must remain read-model consumers, not alternate decision paths
- schema validation must preserve event ownership semantics rather than flatten them

---

## 6. Backlog Items

## P2-1 Separate API and engine runtime more cleanly where needed

**Priority:** P2  
**Owner domain:** deployment / backend architecture  
**Why:** mixed-role runtime becomes a scaling and incident-debug bottleneck.

**Tasks:**

- review current co-location of API + engine responsibilities
- split service entrypoints if still overly combined
- make per-service readiness and health explicit
- ensure shared dependencies are not confused with shared authority

**Likely file targets:**

- service entrypoints
- startup scripts / Procfiles / deployment manifests
- environment documentation

**Dependencies:** P0 and core P1 contracts stable

**Definition of done:**

- API and engine can be reasoned about as distinct runtime roles even if still sharing some infrastructure
- health/readiness can be checked per service role

---

## P2-2 Make orchestrator an explicit first-class deployed service

**Priority:** P2  
**Owner domain:** deployment + orchestrator  
**Why:** hidden-but-critical coordination logic is dangerous during incidents.

**Tasks:**

- ensure orchestrator has explicit deployment/runtime identity
- expose orchestrator heartbeat/health/readiness separately
- document Redis channels/keys and orchestration metrics clearly
- align deployment docs with actual service separation

**Likely file targets:**

- `services/orchestrator/*`
- deployment manifests/config
- observability and environment docs

**Dependencies:** P1-4 complete enough

**Definition of done:**

- orchestrator is visible as its own runtime concern
- operators can tell whether a problem is engine, API, or orchestrator related

---

## P2-3 Finalize canonical event schemas and validate emit paths

**Priority:** P2  
**Owner domain:** cross-cutting contracts  
**Why:** event drift erodes integration safety.

**Tasks:**

- finalize JSON schemas under `schemas/`
- include canonical envelope and core event payloads
- add schema validation tests for main producers
- optionally run emit-path validation in warn mode before hard-fail mode
- ensure event IDs and producer attribution are stable

**Likely file targets:**

- `schemas/*.json`
- event emission helpers
- contract tests

**Dependencies:** P1 event-producing flows stable

**Definition of done:**

- core events are schema-validated
- ownership attribution is preserved and test-covered

---

## P2-4 Harden metrics, health, and machine auth boundaries

**Priority:** P2  
**Owner domain:** observability + security  
**Why:** metrics visibility without proper separation can become noisy or unsafe.

**Tasks:**

- separate machine scraping auth from normal dashboard-user auth where needed
- refine `/metrics`, `/healthz`, `/readyz` exposure and protections
- add metrics/labels for freshness classes, heartbeat age, firewall outcomes, execution ambiguity, orchestrator state
- review cardinality risk in metrics dimensions

**Likely file targets:**

- metrics middleware
- health/readiness route modules
- observability config
- auth middleware for machine endpoints

**Dependencies:** P0/P1 health and flow signals exist

**Definition of done:**

- observability is more useful without weakening security
- metrics can distinguish process, freshness, legality, and execution ambiguity layers

---

## P2-5 Enrich portfolio and trade-detail read models for operator truth

**Priority:** P2  
**Owner domain:** API + dashboard  
**Why:** operator UX should expose backend truth clearly enough for action and RCA.

**Tasks:**

- enrich trade detail views with:
  - gate breakdown
  - execution plan snapshot
  - slippage expected vs actual
  - RR planned vs actual
  - journal timeline
- enrich account/global portfolio views with:
  - compliance mode state
  - active EA instances
  - exposure and drawdown buffers
  - systemic risk indicators
- ensure these remain aggregated read models, not new authority sources

**Likely file targets:**

- API portfolio/trade detail read-model builders
- dashboard pages/components for portfolio and trade detail

**Dependencies:** P1 read models and execution truth available

**Definition of done:**

- operator can understand outcome and risk state without jumping across multiple internal tools

---

## P2-6 Add replay/forensic support for RCA where feasible

**Priority:** P2  
**Owner domain:** observability / data engineering / backend  
**Why:** incidents should be reconstructable from preserved truth.

**Tasks:**

- define minimum replay artifacts:
  - event history
  - verdict provenance
  - firewall results
  - execution lifecycle
  - freshness classification snapshots
- expose tooling or scripts for RCA reconstruction
- ensure append-only records are sufficient for forensic replay

**Likely file targets:**

- replay tools/scripts
- persistence/query utilities
- RCA support docs

**Dependencies:** P1 persistence and eventing mature enough

**Definition of done:**

- at least core incidents can be reconstructed without relying only on memory or ad hoc logs

---

## P2-7 Make rate limiting more actor-aware where needed

**Priority:** P2  
**Owner domain:** API/security  
**Why:** per-IP alone may be too coarse for real operational patterns.

**Tasks:**

- review rate limit buckets by IP, actor, account, EA instance, and endpoint class
- refine limit keys where current behavior is too blunt or too weak
- preserve Redis-backed distributed semantics
- test against legitimate operator and EA usage patterns

**Likely file targets:**

- rate limit middleware/config
- API auth context mapping

**Dependencies:** P1 command endpoints in use

**Definition of done:**

- rate limits better reflect real actor boundaries without undermining protection

---

## P2-8 Harden V11 and execution-path observability at p95/p99

**Priority:** P2  
**Owner domain:** engine + execution + observability  
**Why:** typical latency alone is not enough for serious live operations.

**Tasks:**

- instrument p95/p99 for V11 overlay path if enabled
- instrument p95/p99 for execution path stages
- add alerts for latency budget breaches and excessive veto/reject/ambiguity rates
- correlate latency metrics with freshness and reconnect storms where possible

**Likely file targets:**

- engine/V11 timing instrumentation
- execution timing instrumentation
- observability dashboards/alerts

**Dependencies:** P1 execution flow stable, V11 path available if used

**Definition of done:**

- latency budgets and anomaly rates are operationally visible beyond averages

---

## P2-9 Improve dashboard/operator command center ergonomics

**Priority:** P2  
**Owner domain:** dashboard  
**Why:** once backend truth is stronger, operator UX should become clearer and safer.

**Tasks:**

- make settings changes visibly require reason and show audit feedback
- make take-signal/reject/hold/execution states clearly attributable
- show compliance mode, system locks, heartbeat age, and freshness class in operator surfaces
- highlight unresolved execution ambiguity and blocked actions with reasons

**Likely file targets:**

- dashboard settings pages/components
- command center/status UI
- trade detail / portfolio UI

**Dependencies:** P1 command and read-model flows available

**Definition of done:**

- operator UI communicates truth and constraints clearly instead of only exposing controls

---

## P2-10 Add P2 contract, load, and rollout validation

**Priority:** P2  
**Owner domain:** cross-cutting  
**Why:** topology cleanup and richer contracts need realistic validation.

**Tasks:**

- add contract tests for event schemas and service ownership assumptions
- extend load tests for API/WS/orchestrator under realistic deployment topology
- verify fallback ladder, readiness, and execution reconciliation under restart/failure scenarios
- validate staged rollout and rollback procedures

**Likely file targets:**

- integration/load test suites
- deployment runbooks
- rollout checklists

**Dependencies:** P2-1 through P2-9 in usable form

**Definition of done:**

- topology and contract changes are validated under realistic conditions, not only unit tests

---

## 7. Execution Order

Recommended order:

1. P2-1
2. P2-2
3. P2-3
4. P2-4
5. P2-5
6. P2-6
7. P2-7
8. P2-8
9. P2-9
10. P2-10

---

## 8. Acceptance Checklist

- [ ] API/engine/orchestrator runtime roles are clearer in deployment and health surfaces
- [ ] core event schemas are finalized and validated
- [ ] observability separates liveness, freshness, legality, and execution ambiguity better
- [ ] portfolio/trade-detail views are materially more useful for operators and RCA
- [ ] replay/forensic support exists at least for core incidents
- [ ] rate limiting reflects actor boundaries more accurately where needed
- [ ] latency and anomaly budgets are visible at p95/p99 where it matters
- [ ] dashboard command center surfaces constraints and truth clearly
- [ ] contract/load/rollout validations pass

---

## Closing Principle

P2 is complete only when the system becomes not just safer, but easier to trust, operate, and investigate under pressure.
