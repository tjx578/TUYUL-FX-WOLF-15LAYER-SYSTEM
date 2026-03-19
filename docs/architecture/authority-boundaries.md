---
title: TUYUL-FX Authority Boundaries
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - authority
  - governance
  - decision-boundaries
path: docs/architecture/authority-boundaries.md
---

# TUYUL-FX Authority Boundaries

**Document path:** `docs/architecture/authority-boundaries.md`  
**Status:** Official Architecture Reference  
**Scope:** Authority separation, decision legitimacy, veto hierarchy, and execution gating  
**Applies to:** Ingest, runtime context, governance layer, Wolf constitutional DAG, execution bridge, dashboard and operator surfaces

---

## 1. Purpose per Layer

### 1.1 Why Authority Boundaries Exist
TUYUL-FX is a realtime trading system. In such systems, the most dangerous failures rarely come from missing calculations alone. They come from components acting outside their legitimate authority.

This document defines which components may:
- observe data
- validate data
- publish state
- score or advise
- veto or constrain
- issue a final trading verdict
- transmit execution intent

Its purpose is to prevent silent authority creep, where a supporting component begins to behave like a decision authority without explicit architectural approval.

### 1.2 External Source Boundary
External providers may supply information, but they have no internal authority.

Their purpose is limited to:
- delivering ticks
- delivering candles
- delivering macro/news context

They may influence internal reasoning only after validation and normalization.

### 1.3 Ingest Authority Boundary
The ingest layer has authority over **data admission**, not over **trade decisions**.

Its purpose is to:
- connect to upstream data providers
- accept or reject payloads
- normalize symbols, timestamps, and schema
- build runtime candles
- publish heartbeat and freshness metadata

It may decide whether incoming data is usable. It may not decide whether a trade should happen.

### 1.4 Redis / Persistence Boundary
Redis and PostgreSQL have authority over persistence and recovery state only.

Their purpose is to:
- preserve operational state
- support warmup and hydration
- persist journals and recovery snapshots
- distribute current state across containers

They do not own trading logic and may not infer decision legitimacy from stored data alone.

### 1.5 Runtime Context Boundary
`LiveContextBus` and related runtime context holders have authority over **session-local state assembly**.

Their purpose is to:
- keep runtime candles, ticks, timestamps, and inference inputs available
- expose synchronized in-memory context to the pipeline
- preserve distinctions between fresh and stale-preserved state

Runtime context may prepare information for reasoning. It may not independently authorize execution.

### 1.6 Governance Boundary
The governance layer has authority to constrain, penalize, degrade, or block downstream operation when the system is not epistemically safe.

Its purpose is to:
- enforce warmup sufficiency
- assess freshness and producer health
- evaluate data quality and recovery legitimacy
- force `HOLD` or block unsafe operation

Governance may deny permission to continue. Governance does not itself issue a trade verdict.

### 1.7 Analysis Boundary
The Wolf constitutional DAG has authority to interpret validated context and produce structured decision candidates.

Its purpose is to:
- analyze market context
- score and validate signals
- apply constitutional checks
- produce a verdict through the proper authority path

Within this DAG, authority is not evenly distributed. Advisory layers are not equivalent to verdict authority.

### 1.8 Layer 12 Verdict Boundary
Layer 12 is the **sole authority** for final trade verdicts.

Its purpose is to:
- determine whether the system issues `BUY`, `SELL`, `HOLD`, or equivalent verdict classes
- ensure that all prior constitutional gates have been satisfied
- refuse to act when governance conditions invalidate the reasoning context

No upstream layer, no UI, no transport, and no scheduler may replace Layer 12 as final verdict authority.

### 1.9 Execution Bridge Boundary
The execution bridge has authority to transmit **order intent**, but only after a valid verdict exists.

Its purpose is to:
- receive authority-gated trade intent
- transmit the intent to EA / broker infrastructure
- receive acknowledgements, rejects, or fill feedback
- return execution outcomes to journals and monitoring

The execution bridge may not create trade ideas, rewrite verdicts, or bypass governance locks.

### 1.10 Dashboard / Operator Boundary
The dashboard and operator tooling have authority for visibility, diagnosis, and approved control actions only.

Their purpose is to:
- present current system state
- show freshness and heartbeat status
- surface locks, holds, and degraded conditions
- allow explicit operational actions that are already supported by the control plane

They may not infer or fabricate a trading verdict outside the backend authority chain.

---

## 2. Source of Truth per Komponen

### 2.1 Data Admission Truth
- ingest validators are the source of truth for whether a payload is accepted into the system
- schema guards and spike filters define admissibility, not the dashboard or downstream pipeline

### 2.2 Runtime State Truth
- Redis is the source of truth for current operational state distribution
- PostgreSQL is the source of truth for durable recovery and historical record
- `LiveContextBus` is the source of truth only for the in-process runtime session

### 2.3 Governance Truth
- heartbeat age, `last_seen_ts`, warmup completeness, and quality metrics are the source of truth for governance decisions
- governance decisions must come from dedicated governance components, not from scattered heuristics inside unrelated modules

### 2.4 Analytical Truth
- validated runtime context entering the Wolf DAG is the source of truth for analysis inputs
- upstream features become analytically legitimate only after governance allows them through

### 2.5 Verdict Truth
- Layer 12 is the sole source of truth for the final trade verdict
- any pre-L12 signal is provisional, advisory, or veto-capable, but not final

### 2.6 Execution Truth
- execution status is determined by execution acknowledgements, reject messages, and fill events returned by the broker/EA bridge
- UI assumptions do not override actual execution feedback

### 2.7 Operator Truth
- the dashboard is a presentation surface for backend truth
- frontend transport state is not the source of truth for system legitimacy
- backend freshness, heartbeat, and governance status remain authoritative

---

## 3. Failure Modes

### 3.1 Authority Creep
- ingest components infer trade action from feed conditions
- dashboards or alerts imply final verdict status without backend confirmation
- execution components mutate or reinterpret verdicts in transit

### 3.2 Boundary Collapse
- stale runtime context treated as equivalent to live context
- persistence state treated as decision legitimacy
- advisory layers treated as verdict authorities

### 3.3 Governance Bypass
- pipeline proceeds despite failed warmup
- verdict issued despite absent producer heartbeat
- degraded or stale-preserved context allowed into normal-mode execution without hold rules

### 3.4 Ambiguous State Ownership
- multiple modules defining freshness independently
- transport status confused with producer status
- UI state confused with global system state

### 3.5 Execution Boundary Violation
- execution bridge sends orders without a valid Layer 12 verdict
- duplicate intents emitted due to retry ambiguity
- fill or reject feedback not returned to risk/journal state

### 3.6 Operator Boundary Violation
- manual intervention bypasses governance locks
- dashboard actions are interpreted as decision authority rather than operational controls

---

## 4. Recovery Behavior

### 4.1 Boundary Recovery Principle
Recovery must restore state without changing authority ownership.

A recovered system may regain observability before it regains decision legitimacy.

### 4.2 Ingest Recovery
- reconnecting producers recover data flow authority only after heartbeat and valid payload flow resume
- fallback schedulers may temporarily recover data continuity, but do not become trading authorities

### 4.3 Context Recovery
- Redis and PostgreSQL may rehydrate context
- hydrated context must remain classified until governance revalidates freshness and completeness
- recovered context may enable monitoring before it enables normal trading

### 4.4 Governance Recovery
- governance must explicitly clear degraded or no-producer states before normal operation resumes
- recovery cannot silently re-enable decision flow merely because state objects exist again

### 4.5 Verdict Recovery
- there is no cached final verdict authority across invalid operating conditions
- new verdicts require a fresh, legitimate pass through the current constitutional path

### 4.6 Execution Recovery
- execution retries must be tied to explicit idempotency rules and order-intent tracking
- recovery of transport or UI must not replay trades without execution-state confirmation

---

## 5. Enforcement / Hold Rules

### 5.1 Absolute Rules
- Layer 12 is the sole trade verdict authority
- no other layer may independently authorize a trade
- no transport or UI component may imply execution authority

### 5.2 Governance First Rule
- if governance says the system is unsafe, the pipeline must `HOLD`
- advisory confidence reductions are insufficient when hard governance thresholds are violated

### 5.3 Freshness Legitimacy Rule
- data presence does not equal decision legitimacy
- stale-preserved context may support monitoring and recovery only
- stale or no-producer conditions must block normal-mode trading unless explicitly approved under controlled policy

### 5.4 Execution Gate Rule
- the execution bridge may transmit order intent only after a valid Layer 12 verdict and passing governance status
- missing verdict provenance must force rejection

### 5.5 Operator Constraint Rule
- operator surfaces may expose controls such as kill-switches or maintenance mode only through approved backend control paths
- operators must not gain hidden alternate authority through UI shortcuts

### 5.6 Auditability Rule
- every veto, hold, verdict, and execution intent must remain attributable to its proper layer
- the system must preserve who decided, who constrained, and who executed

---

## Closing Principle

In TUYUL-FX, information may flow through many layers, but authority must not.

A healthy architecture is one in which each layer does its own job completely, while refusing to impersonate the authority of any other layer.
