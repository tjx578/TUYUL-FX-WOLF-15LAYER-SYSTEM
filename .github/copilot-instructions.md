# Copilot Coding Agent Instructions — TUYUL FX / Wolf-15 Layer System

## Mission
You are assisting development of a trading analysis + governance system ("Wolf-15") with strict authority separation:
- Analysis produces candidates and metrics.
- **Constitution (Layer-12) is the sole decision authority.**
- Execution is dumb: no thinking, no overrides.
- Dashboard is an account/risk governor + ledger (interactive UI allowed).
- Journal is an immutable audit trail (including rejected setups).

Your job: implement features while preserving these boundaries.

---

## Non-Negotiable Rules (Constitutional)
1. **Never add execution authority to analysis or reflective modules.**
2. **Never allow dashboard or EA (Expert Advisor) to override Layer-12 verdict.**
3. **Never compute market direction in execution/dashboard.**
4. **Journal is write-only / append-only (immutable).**
5. EA (Expert Advisor) is an executor only. All state/risk comes from dashboard.

If a request conflicts with these, propose an alternative design that preserves authority boundaries.

---

## Repository Architecture (High Level)
- `analysis/` : L1–L11 only. No execution side-effects.
- `constitution/` : gatekeeper + verdict engine (Layer-12). **Single authority.**
- `execution/` : pending/cancel/expiry/state-machine. No strategy logic.
- `dashboard/` : interactive UI + backend API. **Account, risk, ledger, monitoring.**
- `journal/` : decision audit system (J1–J4). Append-only. No decision power.
- `risk/` : prop firm profiles + guards (see `risk/prop_firm.py`). **Rule authority for account limits.**
- `storage/` : snapshots, archives, exports.
- `schemas/` : JSON schemas for L12/L14 and alerts.

---

## Core Data Contracts
### Layer-12 Verdict / Signal (Core → Dashboard)
- **Current minimal schema** (see `schemas/l12_schema.json`):
  - Required: `symbol`, `verdict`, `confidence`.
- **Current enriched fields** (produced by `constitution/verdict_engine.py`, not yet enforced by `l12_schema.json`):
  - Examples: `execution.lot_size`, `risk_percent`, `risk_amount`, `entry_price`, `stop_loss`, `take_profit_1`.
- **Design constraint (now and future)**:
  - Must NOT depend on: account balance, equity, or external account state.
- **Target / aspirational L12 "Signal" contract** (for future schema alignment):
  - Should include: pair/symbol, direction, entry_price, stop_loss, take_profit_1, RR, verdict, scores (wolf/tii/frpc), signal_id, timestamp.
  - Should avoid embedding account-level risk state (balance, equity) and let dashboard/propfirm logic handle position sizing.

### Risk Recommendation (Dashboard → EA/User)
- Must include: trade_allowed, recommended_lot, max_safe_lot, reason, expiry.
- Must be derived from account state + propfirm guard + risk profile.

### Trade Reporting (EA/User → Dashboard)
- Required events: ORDER_PLACED, ORDER_FILLED, ORDER_CANCELLED, ORDER_EXPIRED, SYSTEM_VIOLATION.
- Manual and EA must use the same endpoints and ledger tables.
- Event schemas are defined in `schemas/alert_schema.json`.

---

## Prop Firm Enforcement
- All enforcement happens in `risk/prop_firm.py` (current prop-firm guard module) with a standard interface:
  - `check(account_state: dict, trade_risk: dict) -> {allowed, code, severity, details?}`
- Dashboard must treat guard result as binding for risk legality (but still not a market decision).

---

## Trade State Machine (Dashboard Authority – Conceptual)

This is a **dashboard-level conceptual state machine**, not a direct mirror of
`execution/state_machine.py`. Names like `SIGNAL_CREATED` and `TRADE_OPEN` are
**semantic labels for the UI/governance layer**, not required code identifiers.

States (dashboard conceptual model):
- SIGNAL_CREATED → (SIGNAL_EXPIRED | PENDING_PLACED)
- PENDING_PLACED → (PENDING_FILLED → TRADE_OPEN) | PENDING_CANCELLED
- TRADE_OPEN → [optionally: TRADE_PARTIAL_CLOSED] → TRADE_CLOSED
- TRADE_ABORTED (violation/bypass)

Mapping to `execution/state_machine.py` (implementation states such as `IDLE`,
`PENDING_ACTIVE`, `CANCELLED`, `FILLED`):
- SIGNAL_CREATED ≈ `IDLE` with an attached decision signal but no live order yet.
- PENDING_PLACED ≈ `PENDING_ACTIVE` (order placed, waiting to fill or cancel).
- PENDING_FILLED / TRADE_OPEN ≈ `FILLED` (position live).
- PENDING_CANCELLED / SIGNAL_EXPIRED / TRADE_ABORTED / TRADE_CLOSED → terminal
  conditions that should correspond to `CANCELLED` or a finalized `FILLED`
  position depending on whether the order ever filled.

Dashboard owns conceptual state transitions; EA/user only reports execution
events which then update both the execution state machine and this dashboard
model consistently.

---

## Journal (J1–J4)
- J1: context snapshots (may exist with no trade)
- J2: decision (must log EXECUTE/HOLD/NO_TRADE/ABORT)
- J3: execution details (only if executed)
- J4: reflection (post-trade or post-reject outcome)
All rejected setups must be journaled.

---

## How to Work
When implementing:
1. Identify which zone the change belongs to (analysis/constitution/execution/dashboard/journal/risk).
2. Confirm it does not violate authority boundaries.
3. Add/adjust schemas if contracts change.
4. Add tests for critical logic:
   - prop firm guard failures
   - pending cancellation
   - Layer-12 gate behavior
   - dashboard risk clamp

---

## Coding Style
- Python: type hints, dataclasses where appropriate, small pure functions.
- No hidden side effects in analysis.
- Explicit error codes; avoid silent fallbacks in production paths.
- Keep configs in `config/` and prop firm profiles under the appropriate config/profile directory (for example, under `config/` as used by `risk/prop_firm.py`).
- Log important state transitions and violations (but do not log secrets).

---

## Security & Secrets
- Never commit `.env`.
- Use `.env.example` as template.
- Never print API keys, JWT secrets, Redis passwords.

---

## Definition of Done
A change is done when:
- It respects the constitutional boundaries above.
- It includes tests (or clear reason why not).
- It updates any relevant schema/docs.
- It does not break existing commands.
