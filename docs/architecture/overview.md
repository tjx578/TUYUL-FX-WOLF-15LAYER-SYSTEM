---
title: TUYUL-FX Architecture Overview
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - overview
  - onboarding
  - rca
  - documentation-map
path: docs/architecture/overview.md
---

# TUYUL-FX Architecture Overview

**Document path:** `docs/architecture/overview.md`  
**Status:** Official Architecture Reference  
**Scope:** Documentation map, system topology overview, onboarding entrypoint, and RCA navigation  
**Applies to:** All TUYUL-FX services, architecture documents, and incident-review workflows

---

## 1. Purpose per Layer

### 1.1 Why This Overview Exists
This document is the entrypoint for understanding the TUYUL-FX architecture package.

Its purpose is to:
- explain how the major services fit together
- map the architecture documents to their intended use
- give new engineers a reliable starting point
- help incident reviews locate the right architectural reference quickly

This document does not replace the deeper architecture files. It connects them.

### 1.2 High-Level Service Topology
The current service topology can be read as:

`Finnhub / ForexFactory -> wolf15-ingest -> Redis / PostgreSQL -> wolf15-engine -> wolf15-orchestrator -> execution / allocation / worker -> wolf15-api`

At a high level:
- market and event data enter through ingest
- Redis and PostgreSQL preserve and distribute operational state
- the engine builds runtime context and runs the analytical pipeline
- the orchestrator coordinates downstream actions and fanout
- execution, allocation, and worker services handle domain-specific post-verdict responsibilities
- the API/dashboard layer exposes system state and operational visibility

### 1.3 Document Map Purpose
Each architecture file exists for a different reason:

- `data-flow-final.md`
  - defines end-to-end realtime data flow
  - explains how ingest, durability, freshness, governance, and dashboard transport fit together
  - use this first when asking: **How does data move through the system?**

- `authority-boundaries.md`
  - defines which layer may observe, validate, constrain, decide, or execute
  - use this when asking: **Who is allowed to do what?**

- `stale-data-guardrails.md`
  - defines freshness classes, stale-preserved handling, no-producer conditions, and hold rules
  - use this when asking: **How do we stop zombie mode or stale decisions?**

- `execution-feedback-loop.md`
  - defines the closed loop from verdict to intent to broker response to exposure truth
  - use this when asking: **What happened after we decided to trade?**

### 1.4 Onboarding Purpose
For onboarding, this overview provides the recommended reading order:
1. `overview.md`
2. `data-flow-final.md`
3. `authority-boundaries.md`
4. `stale-data-guardrails.md`
5. `execution-feedback-loop.md`

That order moves from broad system understanding to stricter operational and execution detail.

### 1.5 RCA Purpose
For incident review, this overview provides a quick routing model:
- data stopped flowing -> start with `data-flow-final.md`
- stale or zombie behavior -> go to `stale-data-guardrails.md`
- unclear ownership or bypassed rules -> go to `authority-boundaries.md`
- verdict/execution mismatch -> go to `execution-feedback-loop.md`

---

## 2. Source of Truth per Komponen

### 2.1 Documentation Truth
- `overview.md` is the source of truth for documentation navigation and reading order
- deeper architecture files remain the source of truth for their specific domains

### 2.2 Service Topology Truth
- `wolf15-ingest` is the source of truth for accepted upstream payload flow into the realtime system
- Redis is the source of truth for low-latency operational state distribution
- PostgreSQL is the source of truth for durable recovery, journals, and longer-horizon persistence
- `wolf15-engine` is the source of truth for in-process runtime context and analytical evaluation
- Layer 12 inside the engine remains the source of truth for final trade verdicts
- `wolf15-orchestrator` is the source of truth for downstream coordination after engine output enters operational routing
- `wolf15-execution` is the source of truth for execution intent transmission and broker-facing execution tracking
- `wolf15-allocation` is the source of truth for account balance and allocation-aware distribution logic
- `wolf15-worker` is the source of truth for derived operational/risk workloads assigned to asynchronous processing
- `wolf15-api` is the source of truth for published backend-facing dashboard state and operator-visible system surfaces

### 2.3 Architecture Package Truth
- `data-flow-final.md` is authoritative for realtime data movement and freshness-aware topology
- `authority-boundaries.md` is authoritative for role separation and decision legitimacy
- `stale-data-guardrails.md` is authoritative for stale-state classification and hold rules
- `execution-feedback-loop.md` is authoritative for post-verdict execution-state truth

---

## 3. Failure Modes

### 3.1 Documentation Failure Modes
- engineers read one file in isolation and assume it defines the whole system
- incident reviews discuss symptoms without identifying the correct architecture domain
- authority, freshness, and execution issues get mixed together

### 3.2 Topology Failure Modes
- ingest produces data but durability/fanout is incomplete
- engine keeps running on stale-preserved state without clear classification
- orchestrator routes outputs without clear authority provenance
- execution, allocation, and worker services drift apart in their understanding of current system truth
- API/dashboard shows transport health but not underlying producer or freshness truth

### 3.3 Ownership Failure Modes
- orchestrator is mistaken for final decision authority
- allocation logic mutates execution legitimacy instead of constraining it explicitly
- worker jobs become hidden side channels for state mutation
- API/dashboard infers truths that should come from backend governance or execution state

### 3.4 RCA Failure Modes
- stale-data incidents are treated as UI problems
- execution incidents are treated as signal-quality problems
- orchestration incidents are treated as strategy incidents
- recovery incidents are discussed without referencing freshness class or authority boundaries

---

## 4. Recovery Behavior

### 4.1 Documentation Recovery
When incidents occur, the architecture package should be used as a routing mechanism:
- restore the symptom to the correct domain
- identify the authoritative architecture file
- compare actual behavior against documented authority and recovery rules

### 4.2 Service Recovery Mapping
- ingest failures -> validate producer heartbeat, fallback scheduling, and Redis writes using `data-flow-final.md` and `stale-data-guardrails.md`
- runtime freshness failures -> validate classification and hold behavior using `stale-data-guardrails.md`
- decision-legitimacy failures -> validate constraints and final authority path using `authority-boundaries.md`
- execution ambiguity -> validate intent persistence, acknowledgement, and reconciliation using `execution-feedback-loop.md`

### 4.3 Operational Recovery Principle
A system component may recover transport before it recovers legitimacy.

Examples:
- the dashboard may reconnect while the backend remains stale
- the engine may restart while warmup remains incomplete
- the execution bridge may reconnect while broker reconciliation remains unresolved

Therefore, recovery must always be evaluated against the correct domain truth, not just process liveness.

---

## 5. Enforcement / Hold Rules

### 5.1 Reading Order Rule
- onboarding must begin with `overview.md`
- no engineer should modify downstream execution or stale-data rules without understanding the main data-flow document first

### 5.2 RCA Routing Rule
- every incident review must identify which architecture domain failed first:
  - data flow
  - authority
  - freshness
  - execution feedback

### 5.3 Service Legitimacy Rule
- `wolf15-orchestrator` is not a replacement for Layer 12 authority
- `wolf15-allocation` may constrain distribution or sizing policy, but must not fabricate verdict authority
- `wolf15-worker` may compute metrics or asynchronous tasks, but must not become an invisible decision side-channel
- `wolf15-api` must publish backend truth, not invent it

### 5.4 Hold Rule
If the system cannot identify which architecture domain owns the problem, it must assume the problem is not yet safely understood.

In practice, that means:
- stop claiming normal operation
- classify the incident explicitly
- escalate through the proper architecture reference
- force `HOLD` where legitimacy is in doubt

---

## 6. Recommended Use Cases

### 6.1 Use This Overview For
- onboarding new engineers
- preparing architecture reviews
- routing incident investigations
- explaining the relationship between services and architecture documents

### 6.2 Do Not Use This Overview As
- the only source for stale-data rules
- the only source for decision authority
- the only source for execution reconciliation
- the only source for transport or recovery implementation details

Always drop down into the domain-specific document once the incident or design topic is identified.

---

## 7. Cross-Reference Index

- See `docs/architecture/data-flow-final.md` for end-to-end data movement and recovery-safe freshness architecture
- See `docs/architecture/authority-boundaries.md` for decision legitimacy and veto ownership
- See `docs/architecture/stale-data-guardrails.md` for anti-zombie rules, freshness classes, and stale enforcement
- See `docs/architecture/execution-feedback-loop.md` for verdict-to-intent-to-fill closed-loop execution truth

---

## Closing Principle

A strong architecture package does more than document the system.

It tells engineers where truth lives, where failure begins, and which document to trust when the system stops behaving the way it should.
