# Operational Flow Spec — API, Event Schema, Acceptance Checklist (Ready to Execute)

## 1) Scope and Constitutional Boundaries

This specification implements operational flow where:

1. Engine/Constitution emits global signal (no account binding).
2. Dashboard operator takes signal for a chosen account + EA instance.
3. Operational Risk Firewall validates execution legality.
4. Executor (EA) only executes approved intent.
5. Journal remains append-only for all outcomes (including reject).

### Hard boundaries (must stay true)

- Analysis/Constitution is the sole market decision authority.
- Dashboard/EA cannot override constitutional verdict.
- Dashboard/EA cannot compute market direction.
- Journal is immutable append-only.
- Account/risk legality is enforced in risk/prop guard layer.

---

## 2) API Implementation Spec

Base path: `/api/v1`

### 2.1 Signal Read (existing)

- `GET /signals`
- `GET /signals/{signal_id}`

Rules:

- Signal payload is global and account-agnostic.
- Signal MUST NOT include account fields (`account_id`, `balance`, `equity`, account sizing).

### 2.2 Take Signal (new)

- `POST /execution/take-signal`

Purpose:

- Operator binds one global signal to one account and one EA instance.

Request body schema:

- See [schemas/take_signal_request_schema.json](../schemas/take_signal_request_schema.json)

Success response:

- `202 Accepted`
- Body:
  - `take_id` (UUID)
  - `status` = `RISK_FIREWALL_CHECKING`
  - `signal_id`
  - `account_id`
  - `ea_instance_id`
  - `request_id`
  - `created_at`

Idempotency:

- `request_id` is required and unique per operator action.
- Same `request_id` returns same `take_id` and current status.

### 2.3 Take Signal Status (new)

- `GET /execution/take-signal/{take_id}`

Response body:

- `take_id`
- `status` enum:
  - `TAKEN_BY_OPERATOR`
  - `RISK_FIREWALL_CHECKING`
  - `RISK_REJECTED`
  - `RISK_APPROVED`
  - `ORDER_PLACED`
  - `ORDER_FILLED`
  - `ORDER_CANCELLED`
  - `ORDER_EXPIRED`
  - `TRADE_CLOSED`
  - `TRADE_ABORTED`
- `rejection_code` (nullable)
- `rejection_reason` (nullable)
- `updated_at`

### 2.4 Risk Firewall Decision Endpoint (internal / service-to-service)

- `POST /execution/firewall/decision`

Purpose:

- Called by risk module to persist final legality decision and emit event.

Body:

- `take_id`
- `allowed` (bool)
- `checks` array (ordered check results)
- `final_code`
- `final_reason`
- `snapshot_ref` (reference key for stored risk snapshot)

### 2.5 Portfolio Views (new read endpoints)

#### Level 1 — Global Portfolio

- `GET /portfolio/global`

Response minimum:

- `total_equity_all_accounts`
- `total_open_exposure`
- `risk_per_currency`
- `daily_drawdown_total`
- `systemic_risk_status` (`SAFE|WARN|CRITICAL`)

#### Level 2 — Per Account

- `GET /portfolio/accounts/{account_id}`

Response minimum:

- `equity_curve`
- `daily_dd_gauge`
- `remaining_daily_buffer`
- `max_dd_buffer`
- `consistency_meter`
- `open_trades`
- `active_ea_instances`

#### Level 3 — Per Trade Detail

- `GET /portfolio/trades/{trade_id}`

Response minimum:

- `gate_breakdown` (9 gates)
- `execution_plan_snapshot`
- `slippage_expected`
- `slippage_actual`
- `rr_planned`
- `rr_actual`
- `journal_timeline` (J1/J2/J3/J4)

### 2.6 Settings Command Center APIs (new)

Root: `/settings`

- `GET /settings/global-profiles`
- `GET /settings/strategy-profiles`
- `GET /settings/risk-presets`
- `GET /settings/prop-templates`
- `GET /settings/account-overrides`
- `GET /settings/pair-overrides`
- `GET /settings/news-lock-rules`
- `GET /settings/security`

Write endpoints:

- `POST /settings/{domain}` update
- MUST require:
  - `reason`
  - `changed_by`
  - `change_ticket` (optional but recommended)

Each write must:

- append immutable audit entry,
- store versioned snapshot,
- support rollback endpoint:
  - `POST /settings/{domain}/rollback`

---

## 3) Operational Risk Firewall — Required Validation Order

Order is strict (short-circuit on first hard fail):

1. Kill Switch
2. Prop Firm Limits
3. Exposure Limits
4. Concurrent Trades Limit
5. News Lock
6. Daily Drawdown
7. Pair Cooldown (recommended)
8. Session/Trading Window (recommended)

If any check fails:

- set status `RISK_REJECTED`,
- emit event `RISK_FIREWALL_REJECTED`,
- journal J2 decision (`NO_TRADE` or `ABORT` with reason),
- never call executor.

If all pass:

- set status `RISK_APPROVED`,
- emit event `RISK_FIREWALL_APPROVED`,
- create execution intent,
- forward to EA manager.

---

## 4) Event Schema Spec

Canonical event envelope:

- See [schemas/operational_event_schema.json](../schemas/operational_event_schema.json)

Minimum event types:

- `SIGNAL_CREATED`
- `SIGNAL_TAKEN`
- `RISK_FIREWALL_CHECK_STARTED`
- `RISK_FIREWALL_CHECK_RESULT`
- `RISK_FIREWALL_REJECTED`
- `RISK_FIREWALL_APPROVED`
- `ORDER_PLACED`
- `ORDER_FILLED`
- `ORDER_CANCELLED`
- `ORDER_EXPIRED`
- `TRADE_CLOSED`
- `TRADE_ABORTED`
- `SYSTEM_VIOLATION`
- `SETTINGS_CHANGED`
- `SETTINGS_ROLLED_BACK`
- `COMPLIANCE_MODE_CHANGED`

Required envelope fields:

- `event_id`
- `event_type`
- `event_time`
- `source`
- `severity`
- `signal_id` (nullable on settings/system events)
- `account_id` (nullable before account binding)
- `take_id` (nullable if not related)
- `trade_id` (nullable pre-fill)
- `payload` object

---

## 5) Error Code Contract (for rejection and violations)

Recommended stable codes:

- `KILL_SWITCH_ACTIVE`
- `PROP_DAILY_LIMIT_EXCEEDED`
- `PROP_MAX_LOSS_EXCEEDED`
- `PROP_CONSISTENCY_BREACH`
- `EXPOSURE_LIMIT_EXCEEDED`
- `CONCURRENT_TRADES_LIMIT_EXCEEDED`
- `NEWS_LOCK_ACTIVE`
- `DAILY_DD_LIMIT_EXCEEDED`
- `PAIR_COOLDOWN_ACTIVE`
- `SESSION_LOCK_ACTIVE`
- `INVALID_SIGNAL_STATE`
- `CONSTITUTION_VERDICT_NOT_EXECUTABLE`

All rejection responses must include:

- `code`
- `reason`
- `failed_check`
- `observed_value` (if numeric)
- `threshold_value` (if numeric)

---

## 6) Compliance and Auto Risk Mode

Risk Monitor must expose:

- active prop template (example: `FTMO_100K`)
- daily loss used/remaining
- max loss used/remaining
- consistency used/status
- compliance engine status

Auto mode trigger:

- if usage >= 80% of daily/max limit: `REDUCE_RISK_MODE` enabled.
- if breached: hard block all new execution intents.

Event required on mode changes:

- `COMPLIANCE_MODE_CHANGED` with old/new mode and reason.

---

## 7) Data Ownership and Storage

- Signals: read-only immutable records (global scope).
- TakeSignal: operational binding record.
- Firewall result: immutable check records per `take_id`.
- Trades: execution lifecycle records.
- Journal J1-J4: append-only timeline.
- Settings changes: append-only audit + version snapshot.

---

## 8) Acceptance Test Checklist (Executable)

Use this checklist as release gate for first implementation.

### A. Signal authority and scope

- [ ] A1: Signal payload has no `account_id`.
- [ ] A2: Signal payload has no account-state sizing fields.
- [ ] A3: Dashboard cannot alter constitutional verdict (`EXECUTE/HOLD/NO_TRADE/ABORT`).

### B. Take Signal flow

- [ ] B1: `POST /execution/take-signal` with valid payload returns `202` + `take_id`.
- [ ] B2: repeated request with same `request_id` is idempotent.
- [ ] B3: invalid `signal_id` returns `404`.
- [ ] B4: signal already expired returns `409` + `INVALID_SIGNAL_STATE`.

### C. Risk Firewall hard rejects

- [ ] C1: Kill switch active -> `RISK_REJECTED` + `KILL_SWITCH_ACTIVE`.
- [ ] C2: Prop daily limit exceed -> reject with correct code.
- [ ] C3: Exposure exceed -> reject with correct code.
- [ ] C4: Concurrent trades exceed -> reject with correct code.
- [ ] C5: News lock active -> reject with correct code.
- [ ] C6: Daily DD exceed -> reject with correct code.
- [ ] C7: Any reject does not emit `ORDER_PLACED`.

### D. Approved execution path

- [ ] D1: All checks pass -> status transitions to `RISK_APPROVED`.
- [ ] D2: `ORDER_PLACED` emitted once.
- [ ] D3: `ORDER_FILLED` updates trade lifecycle and portfolio metrics.

### E. Portfolio views

- [ ] E1: Global endpoint returns all mandatory aggregate fields.
- [ ] E2: Per-account endpoint returns risk buffers + active EA list.
- [ ] E3: Per-trade endpoint returns 9-gate breakdown + slippage + RR + journal timeline.

### F. Prop compliance automation

- [ ] F1: Near-limit usage activates `REDUCE_RISK_MODE`.
- [ ] F2: Mode activation emits `COMPLIANCE_MODE_CHANGED`.
- [ ] F3: Breach blocks new intents even if operator retries.

### G. Settings governance

- [ ] G1: Every settings update requires `reason`.
- [ ] G2: Every settings update creates immutable audit log.
- [ ] G3: Rollback creates new audit log entry (never destructive rewrite).
- [ ] G4: Unauthorized role cannot apply settings changes.

### H. Journal integrity

- [ ] H1: Rejected setup still writes J2 entry.
- [ ] H2: Executed trade writes J1->J2->J3->J4 in order.
- [ ] H3: No endpoint can edit or delete prior journal entries.

### I. Forbidden behavior regression checks

- [ ] I1: UI cannot force execute when verdict is not executable.
- [ ] I2: lot/risk parameter mutation without audit is impossible.
- [ ] I3: execution while kill switch active is impossible.
- [ ] I4: account cannot trade without prop template binding.

---

## 9) Suggested rollout sequence (2 sprints)

Sprint 1:

1. Add `take-signal` endpoints and persistence.
2. Add risk firewall check engine + status endpoint.
3. Add operational event schema validation in emit path.
4. Add acceptance tests sections A-B-C-D.

Sprint 2:

1. Add portfolio level endpoints.
2. Add settings governance endpoints + rollback.
3. Add compliance auto mode.
4. Add acceptance tests sections E-F-G-H-I.

---

## 10) Definition of Done

Implementation is done when:

- all acceptance checklist items pass,
- no constitutional boundary is violated,
- events conform to operational schema,
- rejected and executed flows are journaled immutably,
- no duplicate order placement from idempotency/key replay.
