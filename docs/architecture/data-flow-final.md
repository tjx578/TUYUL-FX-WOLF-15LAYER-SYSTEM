---
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-19
tags:
  - architecture
  - data-flow
  - realtime
  - freshness
  - recovery
  - governance
  - redis
  - dashboard
---

# TUYUL-FX Final Data Flow Architecture

**Status:** Official Architecture Reference
**Scope:** Realtime data flow, freshness governance, recovery safety, and anti-stale enforcement
**Applies to:** Ingest, Redis durability, engine runtime context, Wolf analysis pipeline, backend transports, dashboard consumers

---

## 1. Purpose per Layer

### 1.1 External Market / Event Sources

This layer supplies raw upstream inputs required by the system.

It includes:

- Finnhub WebSocket for live ticks
- Finnhub REST Candles for higher-timeframe refresh and fallback
- Calendar / Market News providers for macro and event context

Its purpose is to provide market observations and event context. It is not a decision layer and has no authority over trading actions.

### 1.2 Ingest Authority Layer

This layer is responsible for acquiring, validating, normalizing, and publishing market and event data into the system.

It includes:

- `FinnhubWebSocketFeed`
- Tick validation and spike filtering
- Candle builder chain
- REST fallback scheduler
- H1 refresh scheduler
- News / macro ingest
- Producer heartbeat

Its purpose is to:

- maintain live data acquisition
- reject invalid or dangerous payloads
- construct runtime candle authority from tick flow
- activate fallback collection when primary feeds degrade
- publish freshness and producer health signals

This layer has authority over data production, but no authority over trading decisions.

### 1.3 Redis Durability + Fanout Layer

This layer is the low-latency operational substrate for the realtime system.

It includes:

- latest hashes for ticks, candles, and heartbeats
- historical candle lists by symbol and timeframe
- pub/sub channels for tick, candle, news, and system state events

Its purpose is to:

- preserve current low-latency state
- provide cross-container fanout
- support warmup and hydration of runtime consumers
- retain stale-but-available state instead of deleting it aggressively

Redis is not the final analytical authority, but it is a first-class runtime durability and distribution layer.

### 1.4 Engine Context / Recovery Layer

This layer turns Redis-backed runtime data into analysis-ready state.

It includes:

- `RedisConsumer`
- `LiveContextBus`
- startup hydration and recovery rules

Its purpose is to:

- load history into engine memory during warmup
- consume realtime pub/sub updates
- maintain runtime feed timestamps and inference state
- distinguish fresh live state from stale-preserved recovery state
- restore from PostgreSQL snapshots when Redis is empty or incomplete

`LiveContextBus` is a runtime state hub only. It is not a durable source of truth.

### 1.5 Freshness / Quality / Governance Layer

This layer decides whether the system is epistemically safe to continue normal operation.

It includes:

- `SystemStateManager`
- feed freshness guards
- `DataQualityGate`
- producer health gate
- kill-switch / no-trade guard

Its purpose is to:

- monitor freshness and heartbeat status
- unify degraded, stale, and no-producer detection
- penalize or reject poor data conditions
- block unsafe decision flow when system legitimacy is compromised

This layer is not the final trading authority, but it controls whether the decision pipeline is allowed to operate normally.

### 1.6 Wolf Analysis Constitutional DAG

This is the analytical and constitutional decision pipeline.

It includes:

- warmup gate
- perception layers
- psychology and confluence
- validation layers
- execution logic
- constitutional authority layer
- meta and sovereignty layers

Its purpose is to:

- transform validated market context into structured analysis
- estimate signal quality and execution suitability
- enforce constitutional gates before any verdict is produced

Absolute rule:

- Layer 12 remains sole authority for trade verdicts
- degraded or stale conditions may reduce confidence or force `HOLD`

### 1.7 Output / Consumer Layer

This layer distributes system outputs to consumers and persistence targets.

It includes:

- backend APIs
- realtime transport endpoints
- persistent journals and metrics
- health endpoints and alerting

Its purpose is to:

- expose state safely to dashboards and automation
- publish live and fallback transport data
- persist system records for audit and diagnosis
- support operations visibility and alerts

This layer consumes decisions and system state. It does not decide trades.

### 1.8 Dashboard Layer

This layer provides operator-facing visibility and transport fallback.

It includes:

- `useLivePipeline` transport ladder
- UI freshness states
- operator diagnostics

Its purpose is to:

- keep the frontend connected using the best available transport
- distinguish live, degraded, stale, and no-producer conditions
- show why data is degraded rather than merely showing that it is degraded

The dashboard is an observer and control-surface consumer. It has no trading authority.

---

## 2. Source of Truth per Component

### 2.1 External Sources

**Source of truth:** upstream providers

- Finnhub WebSocket is authoritative for incoming live tick stream availability
- Finnhub REST is authoritative for fallback and higher-timeframe refresh responses
- calendar and news providers are authoritative for event payloads at ingestion time

### 2.2 Ingest Authority Layer

**Source of truth:** validated incoming payloads after schema and spike filtering

- authoritative for accepted live ticks before runtime candle construction
- authoritative for constructed runtime candles before write-through to Redis
- authoritative for producer heartbeat timestamps written by ingest components

### 2.3 Redis Durability + Fanout Layer

**Source of truth:** operational latest state and recent working history

- `wolf15:latest_tick:{symbol}` = latest known tick snapshot, including `last_seen_ts`
- `wolf15:latest_candle:{symbol}:{tf}` = latest known candle snapshot for each timeframe
- `wolf15:candle_history:{symbol}:{tf}` = recent working candle history used for warmup and recovery
- `wolf15:heartbeat:*` = current operational heartbeat state for producers and engine

Redis is the operational source of truth for low-latency runtime recovery, but not the final archival source.

### 2.4 PostgreSQL

**Source of truth:** durable persistence and longer-horizon recovery

- authoritative for recovery snapshots when Redis is empty or corrupted
- authoritative for journals, historical diagnostics, and persistent audit records

PostgreSQL is the durable source of truth for recovery and historical persistence.

### 2.5 Engine Context / Recovery Layer

**Source of truth:** synchronized runtime state hydrated from Redis and, if needed, PostgreSQL

- `LiveContextBus` is authoritative only for current in-memory analysis session state
- feed timestamps in memory are authoritative for immediate runtime freshness checks inside the engine process

### 2.6 Freshness / Quality / Governance Layer

**Source of truth:** latest synchronized timestamps, heartbeats, warmup completeness, and quality metrics

- freshness decisions must be derived from `last_seen_ts` and heartbeat age, not from key disappearance alone
- system state decisions must come from `SystemStateManager`, not ad hoc flags scattered across modules

### 2.7 Wolf Analysis Constitutional DAG

**Source of truth:** validated, gated runtime context passed into the DAG after warmup and governance checks

- Layer 12 is the sole source of truth for the final trade verdict
- upstream layers may advise, score, penalize, or veto, but they do not replace Layer 12 authority

### 2.8 Output / Dashboard Layer

**Source of truth:** backend API and transport outputs published from engine and runtime state

- UI status must reflect backend-provided freshness and producer diagnostics, not infer them independently from transport state alone

---

## 3. Failure Modes

### 3.1 External Source Failures

- WebSocket disconnects or stalls
- REST provider timeouts, rate limits, or partial responses
- news and calendar provider outages or malformed event payloads
- upstream timestamp drift or incomplete candles

### 3.2 Ingest Authority Failures

- invalid state enumeration or startup state mismatch
- non-idempotent retry transitions causing repeated crash loops
- malformed tick acceptance or over-aggressive spike rejection
- producer heartbeat not written or not refreshed
- fallback scheduler not activating after primary feed failure
- refresh scheduler drift or missed runs

### 3.3 Redis Layer Failures

- missing keys due to short TTL policy
- pub/sub delivery gaps
- write failures or lag under load
- destructive overwrite of good state with partial seed
- stale state being mistaken for missing state

### 3.4 PostgreSQL / Recovery Failures

- missing recovery snapshots
- snapshot restore failures
- incomplete historical recovery
- delayed persistence causing recovery from outdated snapshots

### 3.5 Engine Context Failures

- warmup history absent or incomplete
- runtime bus populated with stale-preserved state but treated as fresh
- feed timestamps not updated on consume path
- Redis consumer subscribing successfully but hydrating incompletely

### 3.6 Freshness / Governance Failures

- inconsistent stale thresholds across modules
- key expiry treated as no-data even when stale-preserved state should remain visible
- heartbeat absence not distinguished from transport loss
- readiness reporting true while all symbols are stale
- no-trade hold rules not enforced under unsafe data quality

### 3.7 Analysis Pipeline Failures

- warmup gate bypassed with insufficient bars
- stale or degraded data still entering scoring layers without penalty or hold
- risk sizing and verdict logic operating on invalid market context
- constitutional authority receiving inconsistent upstream quality state

### 3.8 Output / Dashboard Failures

- WebSocket disconnect with no fallback transport
- UI showing stale data as live due to missing freshness metadata
- lack of separation between `NO_PRODUCER`, `NO_TRANSPORT`, and `STALE_PRESERVED`
- operators unable to diagnose cause of data degradation from frontend state alone

---

## 4. Recovery Behavior

### 4.1 Ingest Recovery

- WebSocket feed must reconnect using bounded backoff and jitter
- leader election must ensure only the correct producer becomes active
- REST fallback scheduler must activate after primary transport failure and grace timeout
- scheduled refresh jobs must continue to backfill higher-timeframe state even when tick flow is degraded

### 4.2 Redis Recovery Safety

- seeding must use `temp_key + atomic rename`
- existing valid history must never be destructively deleted before replacement is confirmed
- latest tick and candle objects must retain `last_seen_ts`
- stale state must remain observable even when no new updates arrive

### 4.3 Engine Startup Hydration

- engine starts by hydrating from Redis lists and latest hashes
- if Redis is empty or incomplete, system restores from PostgreSQL recovery snapshots
- hydrated stale state must be marked explicitly as `STALE_PRESERVED` where applicable
- warmup must not be considered complete until required bars and minimum runtime context are present

### 4.4 State Machine Recovery

- retry paths must call `reset()` before re-entering warmup flow when needed
- same-state transitions must be treated as no-op rather than exception conditions
- unsupported states must fail fast during development and be disallowed in production paths

### 4.5 Frontend Recovery

- transport ladder must follow: WebSocket -> SSE -> REST polling
- fallback must preserve visibility into backend freshness, producer heartbeat age, and transport mode
- degraded mode must still attempt recovery rather than merely display a red status indicator

### 4.6 Recovery Classification Rules

- if producer is alive and feed timestamps are within freshness threshold: mark live and fresh operation
- if producer is absent but valid historical state exists: mark `STALE_PRESERVED`
- if transport to UI fails but backend remains healthy: mark `NO_TRANSPORT` on frontend only
- if producer heartbeat is absent and recovery state is insufficient: mark `NO_PRODUCER` and force hold behavior

---

## 5. Enforcement / Hold Rules

### 5.1 Absolute Authority Rules

- Layer 12 is the sole trade verdict authority
- no transport, dashboard, or ingest component may create an execution verdict independently
- upstream advisory layers may penalize, veto, or constrain, but may not replace constitutional authority

### 5.2 Warmup Enforcement

- full analysis is not permitted until required bar counts are satisfied
- incomplete warmup must force either reduced capability mode or `HOLD`
- no new trade verdict may be issued while warmup is insufficient for required timeframes

### 5.3 Freshness Enforcement

- stale detection must be based on `last_seen_ts` and heartbeat age
- stale data must never be silently upgraded to fresh
- if freshness crosses hard thresholds, system must force `HOLD`
- degraded-but-refreshing data may permit reduced-confidence operation only if governance explicitly allows it

### 5.4 Producer Health Enforcement

- absent or stale producer heartbeat must be treated as a first-class risk condition
- if no producer is present and no valid recovery state exists, pipeline must enter `HOLD` only
- readiness must fail when producer presence or minimum freshness requirements are not met

### 5.5 Data Quality Enforcement

- poor gap ratio, low-tick candles, invalid payload density, or stale penalties must reduce trust in downstream analysis
- where configured hard thresholds are breached, system must block new trading decisions rather than merely score them lower

### 5.6 Recovery-State Enforcement

- `STALE_PRESERVED` is valid for observability and controlled recovery, not for silent normal-mode trading
- recovery state may support context continuity, dashboards, and diagnosis
- recovery state must not be treated as equivalent to live production state unless freshness has been re-established

### 5.7 Kill-Switch / No-Trade Enforcement

System must force `HOLD` when any of the following conditions apply:

- stale condition exceeds hard threshold
- no producer and no acceptable recovery state
- warmup incomplete beyond minimum safe boundary
- severe Redis lag or recovery inconsistency
- operator or governance kill-switch is active

### 5.8 UI Enforcement Rules

- UI must display explicit freshness class, transport mode, and heartbeat age
- UI must visually distinguish:
  - `LIVE`
  - `DEGRADED_BUT_REFRESHING`
  - `STALE_PRESERVED`
  - `NO_PRODUCER`
  - `NO_TRANSPORT`
- UI must show hard lock or warning banner when data is not safe for normal trading interpretation

---

## Closing Principle

TUYUL-FX must never treat data presence as equivalent to data legitimacy.

The system is considered operationally trustworthy only when:

- producers are alive
- freshness is within allowed thresholds
- warmup is sufficient
- recovery state is clearly classified
- Layer 12 is making decisions under valid governance constraints

Anything less must degrade gracefully, surface the truth clearly, and force `HOLD` where required.
