# Operational Acceptance Checklist (Signal → Take → Risk Firewall → Execution)

Reference spec:

- [docs/OPERATIONAL_API_EVENT_ACCEPTANCE_SPEC.md](../../docs/OPERATIONAL_API_EVENT_ACCEPTANCE_SPEC.md)

## A. Signal Authority

- [ ] Signal is global (no `account_id` in signal contract).
- [ ] Dashboard cannot alter constitutional verdict.
- [ ] Executor does not infer market direction.

## B. API Contract

- [ ] `POST /api/v1/execution/take-signal` validates request schema.
- [ ] Idempotency via `request_id` is enforced.
- [ ] `GET /api/v1/execution/take-signal/{take_id}` returns lifecycle status.

## C. Risk Firewall

- [ ] Kill switch check
- [ ] Prop firm limits check
- [ ] Exposure check
- [ ] Concurrent trades check
- [ ] News lock check
- [ ] Daily DD check
- [ ] Fail-fast on first hard fail

## D. Eventing

- [ ] All events conform to `schemas/operational_event_schema.json`.
- [ ] Rejection emits `RISK_FIREWALL_REJECTED` with stable `code`.
- [ ] Approval emits `RISK_FIREWALL_APPROVED` before order placement.

## E. Portfolio Views

- [ ] Global endpoint returns aggregate equity/exposure/risk/DD.
- [ ] Per-account endpoint returns DD buffers + EA list.
- [ ] Per-trade endpoint returns gate breakdown + slippage + RR + journal timeline.

## F. Journal & Audit

- [ ] Rejected setup still produces J2 record.
- [ ] Executed setup produces J1→J2→J3→J4.
- [ ] Settings change requires reason + immutable audit record.
- [ ] Rollback creates new audit record (append-only).

## G. Forbidden Behavior Regression

- [ ] Cannot execute when kill switch is active.
- [ ] Cannot trade account without prop template binding.
- [ ] Cannot mutate lot/risk without audit trail.
- [ ] Dashboard cannot force `EXECUTE` against non-executable verdict.
