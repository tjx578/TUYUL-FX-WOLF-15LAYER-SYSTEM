---
title: TUYUL-FX Stale Data Guardrails
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - stale-data
  - freshness
  - guardrails
  - recovery
path: docs/architecture/stale-data-guardrails.md
---

# TUYUL-FX Stale Data Guardrails

**Document path:** `docs/architecture/stale-data-guardrails.md`  
**Status:** Official Architecture Reference  
**Scope:** Freshness classification, stale-state handling, anti-zombie safeguards, and no-trade enforcement under degraded data conditions  
**Applies to:** Ingest producers, Redis state, engine runtime context, governance gates, analysis pipeline, backend APIs, dashboard consumers

---

## 1. Purpose per Layer

### 1.1 Why Stale Data Guardrails Exist
A realtime trading system fails dangerously when stale data is allowed to look legitimate.

The purpose of this document is to define how TUYUL-FX:
- detects stale conditions
- distinguishes stale from missing data
- distinguishes missing data from missing producers
- preserves degraded context without lying about its freshness
- forces `HOLD` when freshness legitimacy is lost

This is an anti-zombie document. It exists to stop the system from appearing alive while reasoning on dead or invalid context.

### 1.2 Ingest Layer Purpose
The ingest layer exists to produce fresh data and freshness metadata.

Its purpose is to:
- accept valid incoming ticks and candles
- stamp accepted updates with reliable timing metadata
- publish producer heartbeat
- activate fallback collection when primary feeds degrade

It is the first layer that can prove whether new data is still entering the system.

### 1.3 Redis Purpose
Redis exists to preserve latest known state and recent history without confusing stale with absent.

Its purpose is to:
- store `last_seen_ts`
- retain latest tick and candle objects beyond short transport outages
- expose current producer heartbeat status
- support warmup and degraded recovery

Redis must preserve observability even when freshness is lost.

### 1.4 Engine Context Purpose
The engine context layer exists to classify and propagate runtime freshness meaningfully.

Its purpose is to:
- hydrate runtime state from Redis and PostgreSQL
- track feed timestamps per symbol and timeframe
- mark stale-preserved state explicitly
- prevent runtime consumers from mistaking old state for fresh live flow

### 1.5 Governance Purpose
The governance layer exists to convert freshness facts into operational consequences.

Its purpose is to:
- classify freshness conditions
- assign degraded or hard-stop meaning to those conditions
- decide whether analysis may continue normally, continue in constrained mode, or must `HOLD`

### 1.6 Analysis Purpose
The analysis pipeline exists to reason over valid context only.

Its purpose in stale scenarios is not to "cope heroically" with invalid inputs. Its purpose is to obey freshness legitimacy rules.

### 1.7 Output and Dashboard Purpose
The output and dashboard layers exist to make stale conditions visible and correctly interpreted.

Their purpose is to:
- show the freshness class explicitly
- show heartbeat age and transport mode
- make `STALE_PRESERVED`, `NO_PRODUCER`, and `NO_TRANSPORT` visibly different

---

## 2. Source of Truth per Komponen

### 2.1 Freshness Timestamp Truth
- `last_seen_ts` attached to accepted ticks and candles is the source of truth for freshness
- key disappearance alone is not the source of truth for freshness classification

### 2.2 Producer Presence Truth
- `wolf15:heartbeat:ingest` and related producer heartbeats are the source of truth for whether producers are alive
- transport connection status alone does not prove producer health

### 2.3 Runtime Freshness Truth
- per-symbol and per-timeframe feed timestamps maintained by the engine are the source of truth for immediate in-process freshness evaluation
- this runtime truth must be synchronized with persisted `last_seen_ts` and heartbeat state

### 2.4 Recovery Truth
- Redis latest state and history are the source of truth for stale-preserved operational recovery
- PostgreSQL snapshots are the source of truth for deeper recovery when Redis is absent or incomplete

### 2.5 Governance Classification Truth
- freshness classes must be produced by governance components, not inferred ad hoc by every consumer
- dashboard displays must reflect backend freshness classification rather than invent their own interpretation

### 2.6 Hold Legitimacy Truth
- the authority to force `HOLD` due to stale or unsafe conditions belongs to governance and constitutional decision logic
- UI warnings are not sufficient substitutes for backend hold enforcement

---

## 3. Failure Modes

### 3.1 Silent Stale Mode
- producers stop, but old data remains visible
- engine continues using stale context as though it were fresh
- dashboard still appears operational because data objects are present

### 3.2 Stale Equals Deleted Error
- short TTL removes latest state too quickly
- system interprets missing key as no data instead of stale-preserved state
- operators lose the ability to inspect the last known valid context

### 3.3 No Producer Hidden by Cached Data
- producer crashes or feed loops fail
- Redis still contains last state
- consumers believe the market is merely quiet instead of recognizing that no producer is alive

### 3.4 Threshold Fragmentation
- ingest uses one stale threshold
- runtime bus uses another
- data quality gate uses another
- UI uses another heuristic entirely

This creates contradictory system truth and makes incident response unreliable.

### 3.5 Recovery Misclassification
- Redis rehydration succeeds, but recovered context is treated as live
- stale-preserved state silently re-enters normal trading mode
- warmup completion is confused with freshness restoration

### 3.6 Transport Confusion
- WebSocket to UI fails, but backend is healthy
- frontend incorrectly displays `NO_PRODUCER`
- operators diagnose the wrong subsystem

### 3.7 Zombie Readiness
- `/readyz` returns healthy because processes are alive
- all symbols are stale or no producer exists
- downstream systems continue trusting an untrustworthy system

---

## 4. Recovery Behavior

### 4.1 Preservation Rule
When fresh data stops arriving, the system must preserve the last known valid state long enough to support diagnosis, continuity, and controlled recovery.

The correct recovery principle is:
- stale should remain visible
- stale should not pretend to be fresh
- stale should not silently disappear too early

### 4.2 Freshness Restoration Rule
Freshness is restored only when:
- producer heartbeat is present and current
- accepted new payloads are arriving
- `last_seen_ts` advances within the approved threshold
- required timeframes regain legitimacy

Warm state restoration alone is not freshness restoration.

### 4.3 Redis Recovery Rule
- retain latest tick and candle objects with `last_seen_ts`
- use long housekeeping TTLs if needed, not freshness-defining TTLs
- preserve candle history for runtime warmup and inspection
- avoid destructive overwrites during seed or reseed

### 4.4 Engine Recovery Rule
- hydrate from Redis first
- restore from PostgreSQL if Redis is empty or incomplete
- classify hydrated state as `STALE_PRESERVED` until fresh flow is re-established
- keep track of feed timestamp age continuously after recovery

### 4.5 Frontend Recovery Rule
- attempt transport ladder: WebSocket -> SSE -> REST polling
- preserve backend freshness classification through all fallback modes
- transport recovery does not imply data freshness recovery

### 4.6 Readiness Recovery Rule
- readiness becomes true only when minimum freshness and producer-health conditions are satisfied
- process liveness alone is never sufficient

---

## 5. Enforcement / Hold Rules

### 5.1 Freshness Classification Rules
Every symbol/timeframe path must be classifiable into one of the approved freshness states. At minimum:
- `LIVE`
- `DEGRADED_BUT_REFRESHING`
- `STALE_PRESERVED`
- `NO_PRODUCER`
- `NO_TRANSPORT`

These classes must have operational meaning, not just cosmetic meaning.

### 5.2 Freshness Threshold Rules
- thresholds must come from a single authoritative configuration model or tightly coordinated policy set
- hard thresholds and degraded thresholds must be explicit
- all major modules must interpret these thresholds consistently

### 5.3 Stale-Preserved Rules
- `STALE_PRESERVED` is permitted for visibility, audit, and controlled recovery
- `STALE_PRESERVED` is not equivalent to live trading context
- stale-preserved state must not silently re-enter normal scoring and execution flow

### 5.4 No-Producer Rules
- absence of producer heartbeat must elevate to a first-class system condition
- `NO_PRODUCER` must be distinguishable from market inactivity and UI transport failure
- no new trading action may be issued when there is no valid producer and no acceptable recovery policy permits continuation

### 5.5 Data Presence Rules
- data existence does not imply freshness
- data recency, provenance, and heartbeat corroboration are required before a context is treated as legitimate

### 5.6 Readiness and Hold Rules
System must force `HOLD` when any of the following apply:
- freshness exceeds hard stale threshold
- producer heartbeat is absent beyond tolerance
- warmup is incomplete and recovery state is insufficient
- freshness classification cannot be determined reliably
- governance detects contradictory freshness signals across layers

### 5.7 UI Rules
- UI must display freshness class explicitly
- UI must show last update timestamp and heartbeat age
- UI must not label stale-preserved state as live
- UI must visually separate transport failure from producer failure

### 5.8 Incident Rule
If the system cannot prove that it is fresh, it must behave as though it is not safe.

That means:
- degrade visibly
- preserve evidence
- stop pretending
- force `HOLD` when required

---

## Closing Principle

A stale system that admits it is stale can still be recovered safely.

A stale system that pretends to be live becomes a decision hazard.

TUYUL-FX must always preserve the distinction.
