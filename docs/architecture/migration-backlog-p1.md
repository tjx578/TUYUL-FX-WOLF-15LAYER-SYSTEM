---
title: TUYUL-FX Migration Backlog P1
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-18
tags:
  - migration
  - backlog
  - p1
  - execution
  - governance
  - contracts
---

## TUYUL-FX Migration Backlog P1

**Status:** Official Execution Backlog
**Scope:** Operational contract hardening, legality flow, execution lifecycle closure, and settings governance
**Applies to:** API/control plane, orchestrator, execution, allocation, worker, persistence, event contracts

---

## 1. Purpose per Layer

### 1.1 Goal of P1

P1 turns the safer baseline from P0 into a system that is legality-gated, auditable, and contract-driven.

The objective is to implement the missing operational pathways that make the architecture real:

* take-signal binding
* risk firewall sequencing
* immutable journal/audit behavior
* execution intent and lifecycle truth
* settings governance and rollback discipline
* orchestrator behavior as coordinator only

### 1.2 P1 Architectural Focus

P1 implements the most important service contracts from the architecture package:

* account binding must not violate constitutional authority
* legality checks must short-circuit before execution
* execution truth must not be confused with intent truth
* settings must be versioned, audited, and rollback-safe
* downstream services must stop behaving like shadow authorities

### 1.3 P1 Exit Condition

P1 is complete only when the system can explain, in a traceable way:

* what the engine decided
* what the operator bound
* what the firewall allowed or rejected
* what the executor actually did
* what the journal recorded
* who changed settings and why

---

## 2. Source of Truth per Komponen

### 2.1 P1 Truth Sources

* signal/verdict truth -> `wolf15-engine`
* account binding truth -> `take-signal` operational record
* legality truth -> risk/firewall service or module
* coordination truth -> `wolf15-orchestrator`
* execution lifecycle truth -> `wolf15-execution` + broker/EA feedback
* settings write truth -> settings governance service/API + PostgreSQL audit/version records
* journal truth -> append-only persistence layer

### 2.2 P1 Non-Goals

P1 does not yet primarily optimize:

* full service separation at deployment level
* advanced forensic replay
* p99 hardening and scale optimization
* deep event-schema enforcement across every producer

Those are mostly P2.

---

## 3. Failure Modes Being Eliminated

* dashboard/operator action bypasses constitutional boundaries
* execution begins without ordered legality checks
* repeated operator command causes duplicate meaning without idempotency protection
* execution ambiguity does not reconcile cleanly after timeout/restart
* settings changes occur without immutable audit and rollback support
* orchestrator acts as pseudo-authority instead of coordinator
* allocation or worker paths mutate primary truth invisibly

---

## 4. Recovery Behavior

### 4.1 P1 Recovery Principle

P1 recovery must preserve provenance.

After partial failure or restart, the system must still be able to answer:

* what command was issued
* whether it was legal
* whether execution was attempted
* whether execution outcome is known or ambiguous
* what configuration state was active at the time

### 4.2 P1 Rollout Guidance

Where possible, introduce new flows in:

* shadow mode
* analysis-only mode
* or behind explicit flags

Recommended candidates:

* take-signal path gated per endpoint
* firewall eventing and persistence behind feature flags
* execution reconciliation in parallel before fully relying on it
* settings rollback endpoints after audit trail is validated

---

## 5. Enforcement / Hold Rules

* no account binding may change constitutional verdict authority
* any hard firewall fail must stop execution before order intent is created
* execution ambiguity must remain visible and conservative
* settings changes without audit metadata are forbidden
* orchestrator may route flow, never synthesize verdicts
* allocation may constrain, never mutate direction

---

## 6. Backlog Items

### P1-1 Implement take-signal API and operational binding record

**Priority:** P1
**Owner domain:** API / control plane

### P1-2 Define take-signal state machine and terminal states

**Priority:** P1
**Owner domain:** API + execution/control contracts

### P1-3 Implement ordered risk firewall checks and immutable result persistence

**Priority:** P1
**Owner domain:** risk / compliance / orchestrator integration

### P1-4 Wire orchestrator as coordinator only

**Priority:** P1
**Owner domain:** orchestrator

### P1-5 Implement canonical execution intent and lifecycle persistence

**Priority:** P1
**Owner domain:** execution

### P1-6 Add execution reconciliation on timeout/restart

**Priority:** P1
**Owner domain:** execution + EA bridge integration

### P1-7 Feed execution truth back into journal and portfolio read models

**Priority:** P1
**Owner domain:** execution + API + persistence

### P1-8 Implement settings governance endpoints with immutable audit + rollback

**Priority:** P1
**Owner domain:** API + persistence + authz

### P1-9 Implement compliance auto-mode eventing and enforcement

**Priority:** P1
**Owner domain:** risk/compliance/orchestrator

### P1-10 Lock worker and allocation behavior to explicit contracts

**Priority:** P1
**Owner domain:** allocation + worker

### P1-11 Add P1 contract tests and acceptance matrix

**Priority:** P1
**Owner domain:** cross-cutting

---

## 7. Execution Order

1. P1-1
2. P1-2
3. P1-3
4. P1-4
5. P1-5
6. P1-6
7. P1-7
8. P1-8
9. P1-9
10. P1-10
11. P1-11

---

## 8. Acceptance Checklist

* [ ] take-signal API exists and is idempotent
* [ ] take-signal lifecycle has explicit transitions and terminal states
* [ ] risk firewall runs in strict order and persists immutable results
* [ ] orchestrator coordinates approved flow without mutating verdict authority
* [ ] execution intent and lifecycle are persisted with provenance
* [ ] restart/timeout reconciliation prevents blind duplicate semantics
* [ ] journal and portfolio read models reflect actual execution truth
* [ ] settings changes are audited and rollback-safe
* [ ] compliance auto-mode is evented and enforced
* [ ] allocation and worker paths obey explicit contracts
* [ ] P1 acceptance tests pass
