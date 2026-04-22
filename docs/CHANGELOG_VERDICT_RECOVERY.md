# Verdict Recovery Changelog

This changelog tracks verdict-recovery wiring, guardrail, and observability changes introduced under `analysis/STRATEGIC_BLUEPRINT_2026-04-22.md`.

## 2026-04-22

### Post-P6 Execution Evaluation Guardrails

- Scope: post-P6 execution evaluation after canary/promote cleanup.
- Blueprint reference: Section 5 `P0 — Freeze Execution / Pastikan Execution Tetap Off` and `P6 — Canary -> Promote -> Baru Evaluasi P1-D / Execution`.
- Change: execution dispatch now returns the explicit disabled contract `{"sent": false, "reason": "execution_disabled"}` when `EXECUTION_ENABLED=0`.
- Change: EA manager does not retry requests that were blocked by the explicit `execution_disabled` contract.
- Change: allocation runtime precheck clamps initial execution rollout to `max 1 trade / 30 minutes / symbol` and `max 3 concurrent positions total`.
- Rationale: preserve constitutional safety while opening post-P6 execution evaluation without reintroducing hidden execution authority or unsafe broker dispatch.

### Post-P6 Operator Observability

- Scope: operator-visible runtime status for execution adapter mode.
- Blueprint reference: Section 5 `P0 — Freeze Execution / Pastikan Execution Tetap Off`, Section 5 `P6 — Canary -> Promote -> Baru Evaluasi P1-D / Execution`, and Section 7 `Gate Clarity`.
- Change: broker runtime mode is logged explicitly at startup, including disabled execution state.
- Change: `GET /api/v1/execution/queue` now exposes `execution_enabled`, `broker_calls_suppressed`, and `ea_url` so operators can confirm adapter mode without reading logs.
- Rationale: the blueprint requires auditable proof that execution remains off until evaluation gates are clean; exposing the mode on an existing runtime endpoint keeps that proof visible without adding a new authority surface.

### Verification Notes

- Focused route and executor tests cover the explicit disabled contract and runtime endpoint exposure.
- This changelog entry records blueprint-aligned wiring and observability work; it is not a production sign-off by itself.

### Verification Gate Scaffolding

- Scope: make the remaining sign-off path concrete for review, security, and performance gates.
- Blueprint reference: Section 7 `Verification Gate`.
- Change: added `docs/runbooks/verdict-recovery-signoff-pack.md` to centralize pending sign-off evidence paths.
- Change: added pending verification artifacts under `journal/verification/` for review, security, and performance gate collection.
- Rationale: the blueprint requires archived evidence, not only implemented code; these artifacts make the remaining gate work executable and auditable.
