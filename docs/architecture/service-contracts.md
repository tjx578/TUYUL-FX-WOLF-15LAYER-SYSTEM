---
title: TUYUL-FX Service Contracts
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - service-contracts
  - integration
  - ownership
  - idempotency
path: docs/architecture/service-contracts.md
---

# TUYUL-FX Service Contracts

**Document path:** `docs/architecture/service-contracts.md`  
**Status:** Official Architecture Reference  
**Scope:** Cross-service contracts, ownership boundaries, input/output expectations, event/state truth, retry rules, and forbidden service behavior  
**Applies to:** `wolf15-ingest`, `wolf15-engine`, `wolf15-orchestrator`, `wolf15-execution`, `wolf15-allocation`, `wolf15-worker`, `wolf15-api`, Redis, PostgreSQL, EA bridge

---

## 1. Purpose per Layer

### 1.1 Why Service Contracts Exist
TUYUL-FX is no longer a single-process mental model. It is a multi-service architecture with multiple truth domains.

This document exists to prevent integration drift.

Its purpose is to define:
- what each service may accept as input
- what each service may publish as output
- which service owns which event or state
- how retries and idempotency must behave
- which cross-service behaviors are explicitly allowed or forbidden

This document should be used when implementing new endpoints, event handlers, orchestrator flows, execution routing, worker jobs, or dashboard features.

### 1.2 Contract Philosophy
Every service contract in TUYUL-FX must preserve five architectural truths:
- authority stays where it belongs
- state ownership is explicit
- events are attributable
- retries do not silently duplicate meaning
- recovery does not create new authority

### 1.3 Relationship to Other Architecture Documents
This document is implementation-facing and must remain aligned with:
- `docs/architecture/overview.md`
- `docs/architecture/data-flow-final.md`
- `docs/architecture/authority-boundaries.md`
- `docs/architecture/stale-data-guardrails.md`
- `docs/architecture/execution-feedback-loop.md`
- `docs/architecture/deployment-topology-final.md`

---

## 2. Source of Truth per Komponen

### 2.1 `wolf15-ingest`
**Primary role:** data admission and runtime market/event production  
**Owns truth for:**
- accepted upstream payload validity
- canonical normalized incoming tick/news payloads
- runtime candle production from live feed logic
- producer heartbeat publication
- last-seen timing on accepted ingest flow

**Does not own truth for:**
- final trade verdicts
- execution legality
- execution status
- portfolio/account legality

### 2.2 `wolf15-engine`
**Primary role:** runtime analysis and constitutional reasoning  
**Owns truth for:**
- in-process runtime analytical context
- freshness/governance gating inside analysis path
- Wolf constitutional layer outputs
- Layer 12 final trade verdict
- any approved post-verdict veto overlay result, if architecturally subordinate to Layer 12

**Does not own truth for:**
- actual broker fill state
- operator intent binding
- account allocation truth

### 2.3 `wolf15-orchestrator`
**Primary role:** workflow coordination after verdict publication  
**Owns truth for:**
- downstream coordination status
- command dispatch state
- operational sequencing state
- compliance tick orchestration state where explicitly assigned

**Does not own truth for:**
- creating or mutating constitutional verdicts
- inventing market direction
- fabricating execution outcomes

### 2.4 `wolf15-execution`
**Primary role:** execution intent transmission and downstream execution-state reconciliation  
**Owns truth for:**
- canonical internal execution intent record
- transmission attempt state
- execution acknowledgement/reject/fill/cancel lifecycle state
- reconciliation status for ambiguous execution outcomes

**Does not own truth for:**
- whether the strategy wanted a trade in the first place
- account policy authority beyond enforced input constraints

### 2.5 `wolf15-allocation`
**Primary role:** allocation/distribution and account-aware routing constraints  
**Owns truth for:**
- account-aware sizing distribution policy
- allocation constraints and routing eligibility
- account-level balance/exposure coordination where explicitly modeled

**Does not own truth for:**
- changing trade direction
- creating strategy verdicts
- faking execution success

### 2.6 `wolf15-worker`
**Primary role:** asynchronous support workloads  
**Owns truth for:**
- async job execution state
- derived metrics or background compute outputs assigned to it
- maintenance or support task lifecycle where explicitly delegated

**Does not own truth for:**
- invisible decision side channels
- final trade authority
- modifying primary truth without approved contract

### 2.7 `wolf15-api`
**Primary role:** authenticated read/write control surface and published backend view  
**Owns truth for:**
- published API response shape
- control-plane validation outcomes for its own endpoint layer
- aggregation of backend truth into dashboard-facing read models

**Does not own truth for:**
- inventing market verdicts
- fabricating execution state beyond what backend truth providers publish
- redefining freshness independently from authoritative backend classification

### 2.8 Redis
**Primary role:** low-latency shared operational state and fanout  
**Owns truth for:**
- latest operational shared state
- heartbeat keys
- recent working candle history
- transient coordination keys, rate-limit counters, and pub/sub fanout state

**Does not own truth for:**
- durable audit truth
- final verdict authority

### 2.9 PostgreSQL
**Primary role:** durable persistence and recovery-safe history  
**Owns truth for:**
- append-only journal records
- audit trails
- versioned settings history
- account ledger / persistent portfolio state where modeled
- recovery snapshots and durable incident history

**Does not own truth for:**
- immediate live feed freshness by itself
- final trade verdict generation

### 2.10 EA Bridge
**Primary role:** execution edge transport between backend and MT5/EA environment  
**Owns truth for:**
- bridge-local transmission status
- bridge-reported execution acknowledgements and downstream execution edge status

**Does not own truth for:**
- strategy direction
- operator account policy
- constitutional legitimacy

---

## 3. Input / Output per Service

### 3.1 `wolf15-ingest`
**Inputs:**
- upstream WebSocket ticks
- upstream REST candles
- upstream macro/news/calendar payloads
- ingest configuration

**Outputs:**
- normalized accepted ticks/candles/news
- runtime candle history updates
- producer heartbeat updates
- Redis writes and pub/sub emissions
- ingestion diagnostics and metrics

### 3.2 `wolf15-engine`
**Inputs:**
- Redis latest state and candle history
- PostgreSQL recovery snapshot if needed
- runtime freshness/governance inputs
- normalized context from ingest-backed state

**Outputs:**
- constitutional analysis result
- Layer 12 verdict
- gate/score breakdowns where applicable
- freshness/governance classification for downstream consumers
- analysis metrics and diagnostic outputs

### 3.3 `wolf15-orchestrator`
**Inputs:**
- engine verdict + provenance
- compliance state snapshots
- account/risk state snapshots where contractually assigned
- command messages and control-plane triggers

**Outputs:**
- coordination commands
- downstream workflow state updates
- approved routing to execution/allocation/worker services
- orchestration metrics, heartbeat, and diagnostics

### 3.4 `wolf15-execution`
**Inputs:**
- approved execution intent with provenance
- legality and compliance approval state
- allocation constraints
- EA/broker acknowledgement and fill events

**Outputs:**
- execution lifecycle events
- order intent persistence
- reconciliation results
- execution metrics and diagnostics
- updates consumable by API/read-model builders

### 3.5 `wolf15-allocation`
**Inputs:**
- approved trade intent
- account state
- risk policy inputs
- portfolio/exposure state

**Outputs:**
- allocation decision artifacts
- account-aware routing/sizing constraints
- portfolio distribution metrics
- account exposure updates where contractually assigned

### 3.6 `wolf15-worker`
**Inputs:**
- explicitly assigned jobs or events
- background processing requests
- metrics or report-generation triggers

**Outputs:**
- derived reports, metrics, or support artifacts
- background processing completion status
- async task diagnostics

### 3.7 `wolf15-api`
**Inputs:**
- authenticated user requests
- internal service data for read models
- settings change commands
- take-signal commands
- health/metrics and portfolio state data

**Outputs:**
- REST responses
- WebSocket/SSE payloads
- API-side validation errors
- immutable audit-triggering command writes where applicable

### 3.8 Redis
**Inputs:**
- latest tick/candle/heartbeat writes
- orchestration state writes
- rate-limit increments
- pub/sub emissions from authorized services

**Outputs:**
- shared low-latency reads
- pub/sub fanout
- transient state visibility for recovery and coordination

### 3.9 PostgreSQL
**Inputs:**
- journals
- audit entries
- settings snapshots
- ledger/trade lifecycle persistence
- recovery snapshots

**Outputs:**
- durable reads for recovery, reporting, RCA, and audit
- source data for aggregated portfolio and journal timelines

### 3.10 EA Bridge
**Inputs:**
- approved execution commands
- identity/authentication material appropriate to bridge model

**Outputs:**
- execution acknowledgements
- fills/rejects/cancels
- bridge health and reconnect state

---

## 4. Event Ownership

### 4.1 Ownership Principle
An event must be emitted by the service that owns the truth of the state transition it describes.

A service may forward, aggregate, or display an event it does not own, but it must not claim authorship of a transition it did not determine.

### 4.2 Canonical Ownership Map
- `SIGNAL_CREATED` -> owned by the analysis source that creates the signal record
- `SIGNAL_TAKEN` -> owned by `wolf15-api` or designated operational service handling take-signal binding
- `RISK_FIREWALL_CHECK_STARTED` -> owned by the service performing legality evaluation
- `RISK_FIREWALL_CHECK_RESULT` -> owned by the legality/risk firewall service
- `RISK_FIREWALL_REJECTED` -> owned by the legality/risk firewall service
- `RISK_FIREWALL_APPROVED` -> owned by the legality/risk firewall service
- `VERDICT_PUBLISHED` -> owned by `wolf15-engine`
- `EXECUTION_INTENT_CREATED` -> owned by `wolf15-execution`
- `ORDER_PLACED` -> owned by `wolf15-execution` or execution edge service that confirms placement
- `ORDER_FILLED` -> owned by execution truth provider receiving broker/EA confirmation
- `ORDER_CANCELLED` -> owned by execution truth provider receiving cancel confirmation
- `ORDER_EXPIRED` -> owned by execution truth provider receiving expiry confirmation
- `TRADE_CLOSED` -> owned by execution/accounting truth provider that confirms closure state
- `TRADE_ABORTED` -> owned by the service determining abort condition under approved contract
- `SETTINGS_CHANGED` -> owned by the service that validates and persists the settings update
- `SETTINGS_ROLLED_BACK` -> owned by the service that validates and persists rollback
- `COMPLIANCE_MODE_CHANGED` -> owned by the service that determines compliance mode transition
- `SYSTEM_VIOLATION` -> owned by the service detecting and declaring the violation

### 4.3 Event Forwarding Rule
Services may republish events to downstream consumers only if:
- the original owner remains attributable
- the event is not semantically rewritten into a different truth claim
- duplication semantics are documented where fanout is intentional

---

## 5. State Ownership

### 5.1 Ownership Principle
Every mutable state object must have one primary owner, even if many services read it.

If ownership is unclear, mutation must be treated as forbidden until clarified.

### 5.2 Canonical Ownership Map
- producer heartbeat state -> `wolf15-ingest`
- runtime analytical context -> `wolf15-engine`
- final verdict state -> `wolf15-engine` Layer 12
- orchestration workflow state -> `wolf15-orchestrator`
- execution intent state -> `wolf15-execution`
- execution lifecycle state -> `wolf15-execution` plus downstream broker/EA truth inputs
- allocation state -> `wolf15-allocation`
- async support job state -> `wolf15-worker`
- dashboard read models -> `wolf15-api`
- rate-limit counters -> Redis-backed rate-limit owner
- durable journal/audit/settings snapshots -> PostgreSQL-backed persistence owner

### 5.3 Projection Rule
Read models, aggregated portfolio views, or dashboard summaries are projections.

They may combine truths from multiple services, but they do not become the primary owner of the underlying state components.

---

## 6. Retry / Idempotency Expectations

### 6.1 General Rule
Retries are allowed only when the contract preserves semantic idempotency or explicitly defines compensating behavior.

Retrying a request must never silently create duplicate authority or duplicate execution meaning.

### 6.2 API Command Idempotency
For write endpoints such as take-signal, settings changes, or operational commands:
- an idempotency key or request ID should be required where duplicate submission risk is material
- same key + same payload should return the same logical result or current status view
- same key + different payload must be rejected as a conflict

### 6.3 Execution Idempotency
Execution-related operations must use correlation identifiers or idempotency keys.

Rules:
- do not resend execution intent blindly on timeout
- reconcile first where downstream state may already have changed
- ambiguous transmission must become a visible state, not an invisible retry loop

### 6.4 Event Idempotency
Event consumers must tolerate duplicates unless delivery semantics explicitly guarantee otherwise.

Where deduplication is required:
- use stable `event_id`
- preserve original event ownership
- do not process duplicate terminal transitions as new meaning

### 6.5 Orchestrator Retry Rules
The orchestrator may retry dispatch or coordination actions only when:
- retry safety is explicitly documented
- downstream target semantics are idempotent or deduplicated
- retried action cannot create duplicate execution or contradictory state transitions

### 6.6 Worker Retry Rules
Worker jobs must declare one of the following behaviors:
- idempotent and safe to retry
- deduplicated by job key
- non-retryable and must surface failure explicitly

Invisible best-effort retries are forbidden for jobs that mutate primary truth.

### 6.7 Settings Retry Rules
Settings writes and rollbacks must never mutate prior audit history destructively.

A retry must either:
- produce the same committed result safely, or
- fail clearly with conflict/duplicate semantics

---

## 7. Allowed Cross-Service Behavior

### 7.1 Allowed Read Behavior
Services may read state from other services or shared stores when:
- the owner of the truth is known
- the read path does not imply write authority
- the consumer does not reinterpret stale projections as primary truth

### 7.2 Allowed Publish Behavior
Services may publish events or projections when:
- they publish only truths they own, or
- they republish with preserved attribution and documented semantics

### 7.3 Allowed Constraint Behavior
Downstream services such as allocation or legality/firewall services may constrain execution eligibility, sizing, or routing under approved policy.

They may not convert a rejected verdict into an executable one, or convert one trade direction into another.

### 7.4 Allowed Recovery Behavior
Services may restore operational continuity from Redis/PostgreSQL state under the documented recovery rules.

Recovery is allowed to restore visibility and resume correct ownership.
Recovery is not allowed to invent missing authority.

### 7.5 Allowed Aggregation Behavior
`wolf15-api` may aggregate:
- signals
- portfolio views
- journal timelines
- execution status
- health/freshness summaries

It may do so only as a read-model publisher, not as an authority replacement layer.

---

## 8. Forbidden Cross-Service Behavior

### 8.1 Forbidden Authority Mutation
No service except `wolf15-engine` Layer 12 may create or mutate the final trade verdict.

Forbidden examples:
- orchestrator upgrading `HOLD` to executable intent
- allocation changing `BUY` into `SELL`
- dashboard forcing execution against constitutional state
- execution service synthesizing trade direction from account state

### 8.2 Forbidden Hidden State Mutation
No background worker or support path may mutate primary truth without an explicit ownership contract.

Forbidden examples:
- worker silently rewriting risk state
- API directly changing execution truth that belongs to execution service
- dashboard endpoint patching journal history retroactively

### 8.3 Forbidden Stale Truth Substitution
No service may treat stale-preserved or projected state as equivalent to fresh primary truth.

Forbidden examples:
- API reporting stale context as live
- orchestrator dispatching execution while producer freshness is invalid
- execution continuing new order flow while hold-worthy freshness ambiguity remains unresolved

### 8.4 Forbidden Destructive Audit Behavior
Append-only journal and audit records must never be rewritten destructively.

Forbidden examples:
- deleting prior settings change history
- editing past journal events in place
- removing rejection evidence because it is operationally inconvenient

### 8.5 Forbidden Retry Behavior
Retries are forbidden when they can create duplicate business meaning without idempotency protection.

Forbidden examples:
- blind order resend after timeout
- repeated take-signal binding without request-key semantics
- repeated compliance mode write that obscures the real transition history

### 8.6 Forbidden Ownership Ambiguity
If two services can both plausibly mutate the same truth but no owner is documented, the mutation path is forbidden until ownership is clarified.

---

## 9. Service-to-Service Contract Matrix

| Producer / Owner | Consumer | Contract Summary |
| --- | --- | --- |
| `wolf15-ingest` | Redis / `wolf15-engine` | Publishes normalized data, heartbeat, and runtime state updates |
| Redis | `wolf15-engine` / `wolf15-orchestrator` / `wolf15-api` | Provides shared low-latency operational state, not verdict authority |
| PostgreSQL | `wolf15-api` / recovery paths / RCA tooling | Provides durable journal, audit, ledger, and recovery snapshots |
| `wolf15-engine` | `wolf15-orchestrator` / `wolf15-api` | Publishes verdicts, analytical outputs, and freshness/governance truth |
| `wolf15-orchestrator` | `wolf15-execution` / `wolf15-allocation` / `wolf15-worker` | Dispatches post-verdict actions without mutating verdict authority |
| `wolf15-allocation` | `wolf15-execution` / `wolf15-api` | Publishes allocation constraints and account-aware routing outputs |
| `wolf15-execution` | EA Bridge / `wolf15-api` / journal persistence | Publishes execution intent and lifecycle truth |
| EA Bridge | `wolf15-execution` | Returns edge execution outcome events and bridge health |
| `wolf15-worker` | `wolf15-api` / observability consumers | Publishes async support outputs only within explicit job contracts |
| `wolf15-api` | Dashboard / operators | Publishes aggregated backend truth and control-plane responses |

---

## 10. Cross-Reference Index

- See `docs/architecture/overview.md` for package navigation and service-document mapping
- See `docs/architecture/data-flow-final.md` for end-to-end data movement and runtime freshness architecture
- See `docs/architecture/authority-boundaries.md` for authority ownership and constitutional constraints
- See `docs/architecture/stale-data-guardrails.md` for freshness legitimacy and anti-zombie rules
- See `docs/architecture/execution-feedback-loop.md` for verdict-to-intent-to-fill truth
- See `docs/architecture/deployment-topology-final.md` for deployed runtime planes and infrastructure placement

---

## Closing Principle

A stable multi-service trading system is not created by adding more services.

It is created by making every service smaller in authority, clearer in ownership, and safer in how it retries, publishes, and recovers.

That is the contract TUYUL-FX must preserve.
