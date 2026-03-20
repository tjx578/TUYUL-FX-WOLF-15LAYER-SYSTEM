# TUYUL-FX Migration Backlog P0

**Document path:** `docs/architecture/migration-backlog-p0.md`
**Status:** Official Execution Backlog
**Scope:** Stop-the-bleeding implementation work required before trusting live operation again
**Applies to:** ingest, engine, API health/readiness, dashboard freshness UX, Redis freshness semantics

---

## 1. Purpose per Layer

### 1.1 Goal of P0

P0 exists to remove the highest-risk operational ambiguity first.

The objective is to stop zombie mode, stale-data masquerading, invalid startup/retry behavior, and misleading readiness/health signals.

### 1.2 P0 Architectural Focus

P0 implements the minimum safe baseline from the architecture package:

* producer heartbeat must exist
* freshness must be classifiable
* stale must not silently become no-data
* readiness must depend on freshness legitimacy
* dashboard must stop lying by omission
* hold behavior must remain conservative under ambiguity

### 1.3 P0 Exit Condition

P0 is complete only when the system can clearly distinguish:

* fresh live operation
* degraded but refreshing
* stale preserved
* no producer
* no transport

and when new-trade flow is safely blocked under hard unsafe conditions.

---

## 2. Source of Truth per Komponen

### 2.1 P0 Truth Sources

* producer heartbeat truth -> `wolf15-ingest`
* runtime freshness truth -> `wolf15-engine`
* shared last-seen state -> Redis
* durable recovery truth -> PostgreSQL
* published readiness/freshness truth -> `wolf15-api`
* operator-visible status truth -> dashboard consuming backend truth

### 2.2 P0 Non-Goals

P0 does not yet fully implement:

* take-signal operational flow
* full firewall legality chain
* full execution reconciliation loop
* settings governance and rollback stack

Those are P1 and beyond.

---

## 3. Failure Modes Being Eliminated

* ingest crash-loop due to invalid state enum / retry logic
* producer death hidden behind stale cached data
* latest tick disappearance caused by short TTL rather than true absence
* inconsistent stale thresholds across ingest/engine/quality layers
* readiness marked healthy while data is stale or producer is dead
* dashboard treating transport state as equivalent to backend freshness truth

---

## 4. Recovery Behavior

### 4.1 P0 Recovery Principle

P0 recovery must preserve evidence and prevent false confidence.

That means:

* stale data remains visible long enough for diagnosis
* recovered state is explicitly classified
* frontend recovery does not imply backend freshness recovery
* restart safety comes before new feature rollout

### 4.2 P0 Rollout Guidance

Deploy P0 incrementally on existing services. Do not delete current Railway/Vercel services first.

Use config flags or staged rollout when possible for:

* new readiness behavior
* dashboard fallback ladder
* hard stale/no-producer hold enforcement

---

## 5. Enforcement / Hold Rules

* if producer heartbeat is absent beyond tolerance, system must not behave as fully live
* if freshness cannot be proven, new-trade flow must remain conservative
* stale-preserved state may support visibility and diagnosis, not silent normal-mode trading
* readiness must not pass on process liveness alone
* dashboard must publish backend freshness truth, not improvise it from WS status alone

---

## 6. Backlog Items

## P0-1 Fix ingest state machine crash loop

**Priority:** P0
**Owner domain:** ingest
**Why:** invalid enum/transitions can kill the producer and cause stale-zombie mode.

**Tasks:**

* replace unsupported `SystemState.LIVE` usage with approved state model
* make same-state transitions no-op safe
* ensure retry path calls `reset()` before re-entering warmup when appropriate
* add explicit tests for startup, retry, same-state transition, and invalid transition handling

**Likely file targets:**

* `services/ingest/ingest_service.py`
* `services/ingest/*state*`
* tests covering state transitions

**Dependencies:** none

**Definition of done:**

* ingest no longer crash-loops on startup/retry
* retry path is idempotent
* state transitions are test-covered

---

## P0-2 Add producer heartbeat and expose heartbeat age

**Priority:** P0
**Owner domain:** ingest + engine + API
**Why:** system must distinguish no-producer from stale-preserved or quiet market.

**Tasks:**

* write `wolf15:heartbeat:ingest` from active producer path
* include heartbeat timestamp/age in backend system-state output
* make engine consume and classify heartbeat state
* add metrics/logging for heartbeat age and missing heartbeat conditions

**Likely file targets:**

* ingest producer loop(s)
* `context/redis_context_bridge.py` or equivalent
* `context/live_context_bus.py`
* `api/routes/system*` or health routes

**Dependencies:** P0-1 recommended

**Definition of done:**

* heartbeat key is written continuously in normal operation
* backend exposes heartbeat age
* no-producer can be detected independently of transport status

---

## P0-3 Replace short TTL freshness semantics with `last_seen_ts`

**Priority:** P0
**Owner domain:** ingest + Redis state
**Why:** stale must not disappear and pretend to be no-data.

**Tasks:**

* store `last_seen_ts` in latest tick/candle structures
* stop using short TTL as freshness definition
* keep long housekeeping TTL only if needed
* verify stale/latest objects remain inspectable during short feed outages

**Likely file targets:**

* Redis latest tick writer
* candle latest-state writer
* any readers assuming key absence == no data

**Dependencies:** P0-2 recommended

**Definition of done:**

* latest tick/candle survives short outage window
* freshness is computed from timestamp, not key absence
* stale state remains diagnosable

---

## P0-4 Unify freshness thresholds and classification

**Priority:** P0
**Owner domain:** engine
**Why:** contradictory stale definitions create false truth across layers.

**Tasks:**

* define authoritative freshness thresholds and classes
* align `analysis/data_feed.py`, `context/live_context_bus.py`, and `analysis/data_quality_gate.py`
* implement approved classes:
  * `LIVE`
  * `DEGRADED_BUT_REFRESHING`
  * `STALE_PRESERVED`
  * `NO_PRODUCER`
  * `NO_TRANSPORT` (UI-facing only where relevant)
* add tests for threshold boundaries and class mapping

**Likely file targets:**

* `analysis/data_feed.py`
* `analysis/data_quality_gate.py`
* `context/live_context_bus.py`
* shared config/constants for thresholds

**Dependencies:** P0-2, P0-3

**Definition of done:**

* major modules agree on freshness classes
* threshold logic is centralized or tightly coordinated
* tests cover transitions between freshness classes

---

## P0-5 Make readiness freshness-aware

**Priority:** P0
**Owner domain:** API + engine
**Why:** process alive is not equal to system safe.

**Tasks:**

* separate liveness vs readiness semantics
* keep `/healthz` process-oriented
* make `/readyz` depend on freshness, heartbeat, and warmup sufficiency
* add explicit response fields that explain why readiness fails

**Likely file targets:**

* `api_server.py`
* `app_factory.py`
* health/readiness route modules
* engine warmup status helpers

**Dependencies:** P0-2, P0-4

**Definition of done:**

* `/healthz` and `/readyz` have different semantics
* readiness fails when producer is absent or freshness is invalid
* operators can see why readiness is failing

---

## P0-6 Block new-trade flow under hard stale/no-producer conditions

**Priority:** P0
**Owner domain:** engine / governance / execution gate
**Why:** ambiguity must degrade conservatively.

**Tasks:**

* introduce or tighten hold logic for hard stale/no-producer states
* ensure trade-creation path respects hold state
* log whether non-execution is due to stale/no-producer governance

**Likely file targets:**

* engine governance/hold modules
* execution entry guard or API-side execution creation gate

**Dependencies:** P0-4, P0-5

**Definition of done:**

* new trade cannot proceed under hard unsafe freshness conditions
* logs/API can explain this reason explicitly

---

## P0-7 Implement dashboard transport ladder and truthful status UX

**Priority:** P0
**Owner domain:** dashboard
**Why:** UI must stop conflating transport failure with backend truth.

**Tasks:**

* implement WS -> SSE -> REST polling fallback sequence
* display freshness class from backend
* display last update timestamp and heartbeat age if provided
* add operator-visible labels for `LIVE`, `DEGRADED_BUT_REFRESHING`, `STALE_PRESERVED`, `NO_PRODUCER`, `NO_TRANSPORT`

**Likely file targets:**

* `dashboard/nextjs/hooks/useLivePipeline.ts`
* `dashboard/nextjs/lib/websocket.ts`
* dashboard status components

**Dependencies:** P0-5 recommended

**Definition of done:**

* dashboard can continue via fallback transports where supported
* dashboard status labels reflect backend truth, not just WS state
* no-producer and no-transport are distinguishable

---

## P0-8 Add P0 regression tests and smoke checks

**Priority:** P0
**Owner domain:** cross-cutting
**Why:** P0 changes must stay stable under redeploy and incident conditions.

**Tasks:**

* add tests for ingest restart/retry behavior
* add tests for freshness class transitions
* add tests for readiness under stale/no-producer conditions
* add UI-level smoke test or integration test for status rendering/fallback path where feasible

**Likely file targets:**

* test suites near ingest, engine, API, and dashboard

**Dependencies:** P0-1 through P0-7

**Definition of done:**

* core P0 behaviors are test-covered
* deploy smoke checks can detect regression quickly

---

## 7. Execution Order

Recommended order:

1. P0-1
2. P0-2
3. P0-3
4. P0-4
5. P0-5
6. P0-6
7. P0-7
8. P0-8

---

## 8. Acceptance Checklist

* [ ] ingest starts cleanly and retries safely
* [ ] producer heartbeat is present and observable
* [ ] latest state uses `last_seen_ts` rather than short TTL semantics
* [ ] freshness classes are unified across core modules
* [ ] readiness is freshness-aware
* [ ] hard stale/no-producer conditions block new-trade flow
* [ ] dashboard distinguishes backend stale/no-producer from transport failure
* [ ] P0 regression tests pass

---

## Closing Principle

P0 is complete only when the system stops pretending uncertainty is acceptable and starts naming degraded truth accurately.
