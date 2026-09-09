# Pursuit binding and source checkpoint

Program verdict: **INCOMPLETE / HOLD; 0/6 milestones closed**. This checkpoint
adds a TEST_ONLY net-geometry kernel and imports the user-supplied pursuit package.
It does not close S01, S03, S04, S05 or any runtime milestone. A00's historical
acquisition closure is preserved. The canonical register and every existing README
remain unchanged.

## Authority and source

The adopted instruction is `input/START_CODEX_DESKTOP.md`. The immutable package
remains a planning artifact; its template permissions are not runtime credentials
or execution authority. `state.json` is the separate operational copy. All 22
imported files retain their original byte hashes. The package validator reports
234 structural checks, 41 canonical actions and 54 GOAP nodes; that is document
validation only. The original validator is excluded from application Ruff via a
single explicit imported-data directory in `pyproject.toml`; it is not reformatted.

Selected SSOT remains repository v3.1 at commit
`dd27ae87d0207466caad4c3e098224112ac0eaf7`, path
`docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md`, blob
`cd848447a2e923d0ea0de6c566a558c7205d3d3b`, SHA-256
`6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902`.
Its 86,002 Git bytes equal the committed selected-SSOT evidence copy. The package's
historical SSOT reference does not replace this selection.

Source checkpoint before this slice was `79597e91a33d88a60c74c4c714cefa8120147fc9`;
new executable source is `f8fcbfb1b53f4cc9861a32aa1368dc3828070caa` on
`codex/s03-runtime-recovery-20260909`. PR #428 was independently read as open and
Draft at the former checkpoint; main was `68ad0794e087177571972a7b95f4b7dde70b5286`.
These identities are observation-time bindings, not continuing remote guarantees.

## K01/K02 reconciliation, still partial

| Requirement | Source binding and evidence | Remaining acceptance |
| --- | --- | --- |
| Pair activity and durable caller state | Existing activity runtime, producer and consumer source; prior consumer validation binds source `3d8df68057d6a0c2f9dc1b1969651f8f298aa713` | 45 existing, 7 producer and 11 consumer PostgreSQL tests remain unexecuted; do not rerun absent a resource change |
| Shared lifecycle owner | `storage/strategy_5scr_lifecycle_v2_repository.py` writes the lifecycle table; `services/pressure_outbox/lifecycle_shadow_worker.py` calls `persist_owner_bundle`; consumer binds owner through the same repository | Migration 20260909_03 adds a shared row trigger, but actual migration, runtime grants and concurrent old-owner rejection are not proven |
| Managed legacy writer | Unfenced legacy writes to managed symbols are rejected by the authored trigger; the worker does not silently acquire a new owner | Managed-symbol deployment/owner binding and database acceptance; privileged trigger bypass is outside the demonstrated scope |
| Transport and ACK | Opt-in authenticated endpoint, explicit destination and ACK after consumer commit exist in source | Active destination/key/owner/policy and real HTTPS/database run unbound |
| Direction consumer | Existing `strategy_5scr_directional_thesis_v1` remains the selected implementation in the old candidate path | Full v3.1 consumer binding is not complete |
| SSOT §17.2 target universe | Existing V2 target map derives strict H4 swings with H1 consumption | Full D1/H4/H1 and other versioned legal structural sources/attestor remain incomplete |
| SSOT §17.4–17.6 cost/geometry | New fixed-target net interval kernel and explicit TEST_ONLY contracts | Active policy, broker cost conversion, target attestor, v3.1 candidate/caller and persistence integration remain incomplete |

The older 15-row S01 rule/contract/test matrix is useful discovery material but
its old source checkpoint is not silently relabeled current. This table binds
the inspected paths and leaves uninspected/full-contract closure open. API provider
configuration reports `python -m api.owner_dashboard_release`; no production
runtime or readiness result was inferred from that setting.

## K06 implemented sub-slice

The old V2 solver uses gross RR and a spread multiplier. The new standalone
`analysis/strategy_5scr_net_geometry_v31.py` kernel accepts an already-fixed target
and structural stop, three explicit entry intervals, broker tick/unit geometry,
and separate profit/loss scenario costs. All four cost components must be supplied,
including explicit zero. It cannot select a farther target, tighten a stop, query
an account, reserve capital, produce a command or grant hypothesis authority.

The contract accepts TEST_ONLY profiles. Policy and cost references are supplied
evidence locators, not independently attested approvals. Non-FX units are explicit;
no FX pip convention is silently applied to metals. Negative credits, incomplete
costs, off-grid fixed prices and naive clocks are rejected. Missing bindings,
symbol/class mismatch, future capture and expiry yield explicit WAIT reasons.

For a fixed BUY target T, stop S, win cost Cw, loss cost Cl and minimum ratio R,
the upper entry bound is `(T + R*S - Cw - R*Cl)/(1+R)`; SELL uses the mirrored
lower bound `(T + R*S + Cw + R*Cl)/(1+R)`. Exact rational arithmetic intersects
the bounds and rounds inward to the tick grid. Reporting precision is separate
from exact acceptance. No live currency/commission conversion model is inferred.

| Expected | Actual local result |
| --- | --- |
| Every feasible tick agrees with a separate brute-force inequality oracle for BUY/SELL, EURUSD, USDJPY and XAUUSD | 24 parameterized oracle cases pass |
| Gross RR 2.4 can fail after costs | Both direction cases return no valid domain |
| Exact net RR 1.5 boundary admitted; next outward tick rejected | BUY/SELL boundary cases pass |
| Missing, mismatched, expired, malformed or authority-escalating input does not pass | Binding and negative cases pass |
| New kernel does not acquire the old Candidate V2 consumer dependency | Existing containment test passes after removal of a helper import; the test was not relaxed |

Final selected suite: **82 passed, 0 failed, 0 errors, 0 skipped** on Windows,
including 45 new kernel cases and 37 existing regressions. Exact JUnit identities
match collection. These 45 kernel tests are unrelated to the 45 PostgreSQL tests.
Do not add this overlapping suite to older test totals. Earlier `ng2` failure and
its source receipt are retained alongside the final `ng3` result. Full repository
Ruff lint and format checks pass (1,404 application Python files formatted).
Independent agent review remains unavailable after the previously reported quota
failure; this checkpoint includes self-review, not an invented independent verdict.

## Publication and next frontier

The GitHub Railway workflow restricts automatic deployment to successful main CI.
Read-only Railway source configurations name main or a release branch for most
same-repository services; pinned-image services and the other repository are
separate. However, the frontend service source omits its branch. Its latest main
deployment does not prove the next-push trigger. **New push is HOLD** until that
read-only trigger binding is verified; local engineering and commits can continue.
No Railway mutation, main merge, billing operation or broker operation occurred.

Next executable work is the K01/K06 target-universe and candidate/caller contract,
using explicit TEST_ONLY policy when active binding is absent. K03 runtime tests
remain prioritized once a permitted disposable resource becomes available. Known
runner, billing and DEMO questions are retained with stable blocker keys and are
not repeated.
