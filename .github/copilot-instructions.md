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
2. **Never allow dashboard or EA to override Layer-12 verdict.**
3. **Never compute market direction in execution/dashboard.**
4. **Journal is write-only / append-only (immutable).**
5. EA is an executor only. All state/risk comes from dashboard.

If a request conflicts with these, propose an alternative design that preserves authority boundaries.

---

## Repository Architecture (High Level)
- `analysis/` : L1–L11 only. No execution side-effects.
- `constitution/` : gatekeeper + verdict engine (Layer-12). **Single authority.**
- `execution/` : pending/cancel/expiry/state-machine. No strategy logic.
- `dashboard/` : interactive UI + backend API. **Account, risk, ledger, monitoring.**
- `journal/` : decision audit system (J1–J4). Append-only. No decision power.
- `propfirm_manager/` : prop firm profiles + guards. **Rule authority for account limits.**
- `storage/` : snapshots, archives, exports.
- `schemas/` : JSON schemas for L12/L14/alerts/commands.

---

## Core Data Contracts
### Layer-12 Signal (Core → Dashboard)
- Must NOT include: balance, equity, lot, risk%.
- Must include: pair, direction, entry, SL, TP1, RR, verdict, scores (wolf/tii/frpc), signal_id, timestamp.

### Risk Recommendation (Dashboard → EA/User)
- Must include: trade_allowed, recommended_lot, max_safe_lot, reason, expiry.
- Must be derived from account state + propfirm guard + risk profile.

### Trade Reporting (EA/User → Dashboard)
- Required events: ORDER_PLACED, ORDER_FILLED, ORDER_CANCELLED, TRADE_CLOSED.
- Manual and EA must use the same endpoints and ledger tables.

---

## Prop Firm Enforcement
- All enforcement happens in `propfirm_manager/**/guard.py` with a standard interface:
  - `check(account_state: dict, trade_risk: dict) -> {allowed, code, severity, details?}`
- Dashboard must treat guard result as binding for risk legality (but still not a market decision).

---

## Trade State Machine (Dashboard Authority)
States:
- SIGNAL_CREATED → (SIGNAL_EXPIRED | PENDING_PLACED)
- PENDING_PLACED → (PENDING_FILLED → TRADE_OPEN) | PENDING_CANCELLED
- TRADE_OPEN → (TRADE_PARTIAL_CLOSED?) → TRADE_CLOSED
- TRADE_ABORTED (violation/bypass)

Dashboard owns state transitions; EA/user only reports events.

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
1. Identify which zone the change belongs to (analysis/constitution/execution/dashboard/journal/propfirm).
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
- Keep configs in `config/` and profiles in `propfirm_manager/profiles/`.
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
