---
title: TUYUL-FX Execution Feedback Loop
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - architecture
  - execution
  - feedback-loop
  - broker-bridge
  - risk
path: docs/architecture/execution-feedback-loop.md
---

# TUYUL-FX Execution Feedback Loop

**Document path:** `docs/architecture/execution-feedback-loop.md`  
**Status:** Official Architecture Reference  
**Scope:** Order intent flow, broker/EA acknowledgements, execution-state feedback, idempotency, and post-verdict risk synchronization  
**Applies to:** Layer 12 verdicts, execution bridge, broker/EA connectors, journals, risk state, observability, dashboard consumers

---

## 1. Purpose per Layer

### 1.1 Why the Execution Feedback Loop Exists
A trading architecture is incomplete if it can produce verdicts but cannot reliably understand what happened after transmission.

This document defines how TUYUL-FX moves from:
- verdict
- to order intent
- to broker acknowledgement
- to fill / reject / cancel state
- to synchronized risk and journal updates

Its purpose is to make execution a closed loop rather than a fire-and-forget action.

### 1.2 Constitutional Verdict Purpose
Layer 12 exists to produce the final trade verdict.

Its purpose in the execution loop is to:
- authorize whether a trade may be attempted
- provide traceable verdict provenance
- define the intended direction and decision class

Layer 12 does not prove that execution occurred. It only authorizes intent.

### 1.3 Execution Bridge Purpose
The execution bridge exists to translate an approved verdict into a controlled order intent.

Its purpose is to:
- accept only authority-gated intents
- attach required identifiers and metadata
- send the intent to EA / broker infrastructure
- track acknowledgement and outcome events
- prevent duplicate or ambiguous execution attempts

### 1.4 Broker / EA Connector Purpose
The connector exists to communicate with the downstream execution venue.

Its purpose is to:
- submit order requests
- receive acknowledgement, rejection, partial fill, fill, cancel, or modification events
- surface downstream errors and timeouts

It does not create strategy decisions.

### 1.5 Execution State Store Purpose
Execution state persistence exists to maintain a durable and queryable account of what happened after an order intent was issued.

Its purpose is to:
- store order intent records
- store execution status transitions
- preserve broker identifiers and correlation IDs
- support restart recovery and replay-safe reconciliation

### 1.6 Risk Synchronization Purpose
Risk synchronization exists to ensure that actual execution outcomes feed back into position, exposure, and governance state.

Its purpose is to:
- update open position state
- reflect partial fills and rejects correctly
- prevent stale assumptions about whether exposure exists
- support downstream kill-switch and risk cap enforcement

### 1.7 Journal and Observability Purpose
Journals and observability exist to keep execution transparent, auditable, and diagnosable.

Their purpose is to:
- record intent, acknowledgement, execution outcome, and downstream anomalies
- expose metrics for latency, reject rates, duplicate suppression, and reconciliation health
- support incident diagnosis when verdict and execution diverge

---

## 2. Source of Truth per Komponen

### 2.1 Verdict Truth
- Layer 12 is the source of truth for whether the system intended to trade
- a verdict is not the source of truth for whether the order reached the broker or filled

### 2.2 Order Intent Truth
- the execution bridge is the source of truth for the canonical internal order intent object after a verdict has been accepted for execution
- this object must include traceable correlation identifiers

### 2.3 Broker Outcome Truth
- broker/EA acknowledgement and status callbacks are the source of truth for downstream execution outcome
- actual fill, reject, partial fill, or cancel states come from downstream execution feedback, not from assumptions in the strategy layer

### 2.4 Position and Exposure Truth
- synchronized execution state plus confirmed fills are the source of truth for actual position/exposure changes
- unacknowledged intents must not be treated as confirmed exposure

### 2.5 Journal Truth
- persistent journal records are the source of truth for auditability and historical incident review
- journals must preserve verdict provenance, transmission metadata, and execution outcome chain

### 2.6 Dashboard Truth
- the dashboard is a presentation surface for backend execution truth
- UI may display pending, acknowledged, rejected, or filled status only as published from the backend execution model

---

## 3. Failure Modes

### 3.1 Fire-and-Forget Failure
- verdict is issued
- order intent is transmitted
- no feedback path records whether the broker accepted or rejected it
- system falsely assumes execution completed

### 3.2 Duplicate Intent Failure
- retries resend an order because acknowledgement state is unclear
- network timeout is mistaken for submission failure
- duplicate orders are created downstream

### 3.3 Ghost Position Failure
- system assumes a fill occurred when no broker confirmation exists
- risk state drifts away from real account exposure
- later decisions compound the mismatch

### 3.4 Lost Reject Failure
- broker rejects the order, but rejection is not ingested or persisted
- strategy continues believing the intended position exists or is pending

### 3.5 Partial Fill Blindness
- system treats partial fill as either full success or full failure
- sizing, stops, and downstream risk logic become incorrect

### 3.6 Restart Ambiguity
- service restarts after sending intent but before persisting final broker response
- system cannot determine whether to retry, reconcile, or mark the order unknown

### 3.7 UI / Backend Divergence
- UI reports order sent or filled from optimistic transport assumptions
- backend execution state disagrees
- operators receive a false picture of what actually happened

### 3.8 Governance Disconnect
- execution occurs under degraded freshness or no-producer conditions because execution gating is weaker than verdict gating
- system sends orders despite the broader architecture being in a hold-worthy condition

---

## 4. Recovery Behavior

### 4.1 Intent Persistence Rule
Before or atomically with transmission, the system must persist a canonical order intent record sufficient to support reconciliation.

This record should include:
- verdict provenance
- symbol
- side
- sizing reference
- correlation ID / idempotency key
- timestamp
- execution mode

### 4.2 Acknowledgement Recovery Rule
If downstream acknowledgement is delayed or ambiguous:
- the system must not assume success
- the system must attempt reconciliation using correlation identifiers and broker-side status queries where supported
- ambiguous intents must enter a recoverable intermediate state rather than being silently retried

### 4.3 Restart Recovery Rule
After restart:
- reload pending and recently ambiguous intents from persistence
- reconcile them against broker/EA state
- update each to acknowledged, rejected, partially filled, filled, canceled, or unresolved
- unresolved states must remain operationally visible until cleared

### 4.4 Partial Fill Recovery Rule
- partial fills must update exposure incrementally
- downstream stops, RR, and management logic must operate on confirmed partial position state
- the system must not wait for a hypothetical full fill before updating risk truth

### 4.5 Reject Recovery Rule
- rejects must feed back into journal, metrics, and decision diagnostics
- a rejected order does not become exposure
- strategy state must remain aligned with actual execution state after reject

### 4.6 Transport Recovery Rule
- transport recovery to the dashboard must not replay execution events blindly
- UI must fetch canonical backend execution state after reconnect
- frontend optimism must yield to backend reconciliation truth

---

## 5. Enforcement / Hold Rules

### 5.1 Verdict-to-Execution Rule
- no execution attempt may occur without a valid Layer 12 verdict
- verdict provenance must be attached to every order intent
- missing provenance must force rejection before transmission

### 5.2 Governance Compatibility Rule
- execution is prohibited when governance has forced `HOLD`
- degraded data conditions that cross hard safety thresholds must block new order intent creation
- execution bridge must respect system hold state even if a local component attempts to proceed

### 5.3 Idempotency Rule
- every order intent must carry an idempotency-safe correlation identifier
- retries must reconcile before resending where possible
- duplicate send without reconciliation is forbidden

### 5.4 Exposure Truth Rule
- confirmed fills, not verdicts, define exposure
- pending or ambiguous intents must not be counted as confirmed exposure unless policy explicitly distinguishes reserved risk from actual exposure

### 5.5 Reconciliation Rule
- ambiguous execution states must remain visible and actionable
- no silent downgrade from unknown to success is allowed
- reconciliation must be part of normal restart and degraded-mode behavior

### 5.6 Journal Rule
- every execution-stage event must be journaled: verdict accepted, intent created, sent, acknowledged, rejected, partial fill, full fill, cancel, reconciliation result
- missing journalability is a system defect, not a cosmetic omission

### 5.7 UI Rule
- UI must separate `INTENT_SENT`, `ACKNOWLEDGED`, `REJECTED`, `PARTIALLY_FILLED`, `FILLED`, and `UNKNOWN_RECONCILIATION`
- UI may not collapse these states into a single generic "executed" badge

### 5.8 Hold-on-Ambiguity Rule
If the system cannot prove execution outcome safely enough to protect downstream risk assumptions, it must degrade conservatively.

That may include:
- blocking follow-up orders on the same symbol
- preventing pyramiding
- freezing automated management changes
- escalating operator visibility

---

## Closing Principle

A verdict is not a trade.

A transmitted intent is not a fill.

A resilient TUYUL-FX architecture must keep asking what actually happened until risk, execution, and truth all agree.
