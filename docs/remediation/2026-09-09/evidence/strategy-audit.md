# Strategy, risk and natural execution audit — 9 September 2026 WITA

**P2/P3 and N07 are not DONE.** On exact `773150952311db3dbf5188f36536b7837d8ec296`, 211 focused Python component tests passed, zero failed and zero skipped. Direct diagnostic checks nevertheless reproduce v3.1 gaps in mixed-direction pair admission and the current-candidate risk handoff. Passing existing tests therefore does not establish the new DoD.

## Scope and identity

- Clean detached worktree: `D:/WOLF15-work/master-strategy-audit-20260909`.
- Commit `773150952311db3dbf5188f36536b7837d8ec296`; tree `ba145af03adce09b3d43d0a4138f5ccea73f92f9`.
- Initial historical inspection used `1837f4b7cbded620c35933af980e9abd166de39e`. After root detected main movement, this independent worktree was advanced to current 77315095 before tests. Strategy/risk source under analysis/contracts/storage/risk is unchanged between these two commits. A moving remote is not frozen by this report.
- Selected v3.1 document is separately on docs branch commit `dd27ae87d0207466caad4c3e098224112ac0eaf7`, path `docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md`.
- Exact Git blob: 86,002 bytes, SHA256 `6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902`. Windows worktree file: 89,471 bytes, SHA256 `b23e432633fb7f6f005fa70613ae3db1d7d43a80b4f4541c31e583f25a4b8b79`. These are equal only after CRLF/LF normalization. Do not equate byte hashes.
- Python 3.11.9, pytest 8.4.2, Pydantic 2.10.3. Machine timestamp in receipt is UTC, local review date WITA. Full source hashes and per-ID findings are in `strategy-audit.json`.

## Action findings

| ID | Scope verdict | Evidence and remaining work |
|---|---|---|
| S01 | BLOCKED | Repo v3.1 document and exact digest now discoverable. Complete policy/schema/authority mapping remains unresolved; document exists on separate docs branch, not tested main. Root contract audit owns full binding. |
| S02 | INCOMPLETE | Closed/as-of/future/partial component cases pass. Fresh runtime coverage, heartbeat freeze, owner-atomic lease and target provider proof not measured here. |
| S03 | FAIL | `raw_admission_blocks.py:307-319` splits on direction; `pair_admission.py:299,343-346` requires resolved uniform direction. With explicitly synthetic complete three-event input and diagnostic max gap 300 seconds, BUY0/BUY150/BUY300 produces one 300-second block and one grant, whereas BUY0/SELL150/BUY300 produces three zero-duration blocks and zero grants. This demonstrates direction coupling, not real-world continuity or trading permission. Gap100 fixture also grants zero, as required for insufficient continuity. |
| S04 | BLOCKED | `storage/observer_strategy_events.py:1-6` explicitly says no MATURE_ADVISORY producer exists until a canonical source owns it. Existing v2 lifecycle recovery tests do not implement v3.1 qualifying advisory admission, same-lifecycle upgrade or mandatory re-evaluation. |
| S05 | FAIL | `contracts/strategy_5scr_tradeplan_candidate_v2.py:21` admits only H4 strict swing target kinds; its authority cohort requires H4 and H1 consumption. v3.1 §17.2 requires D1/H4/H1 plus other legal structural sources. Nearest-target/SL/1.5RR component cases pass within narrower implemented universe. |
| S06 | INCOMPLETE | Full 15 strategy acceptance +20 zero-tolerance clauses are mapped separately. None claims a whole-v3.1 denominator from component tests. Frozen complete dataset/policies, parser/runtime replay and deterministic whole-pipeline receipts remain outstanding. |
| R01 | UNBOUND | `risk/s5_campaign_risk.py:39-41` defaults equal 5% per entry and 10% account cap. No actual account/mode/currency profile was selected or verified by this audit. Do not substitute asymmetric 3.5+1.5 or infer deployment configuration. |
| R02 | BLOCKED | Atomic account lock exists at repository line397; safe Decimal floor/below-min rejection passes unit tests. Current repository requires zero broker positions at line469 and legacy candidate IDs. Real PostgreSQL race/capacity, partial fill and unknown ledger tests not run. Existing concurrent test line548 replays the same request twice; it does not establish capacity under two distinct candidates. |
| R03 | BLOCKED | Risk request regex accepts `5scr-plan:` and rejects current `5scr-tradeplan-v2:` with `string_pattern_mismatch` in an executed diagnostic. Natural source class/current proof/L12/post-verdict/risk lineage remains absent/unbound. ID rewriting would bypass semantic binding, so is not a repair. |
| N01 | BLOCKED | Deterministic command ID and transaction exist for the explicitly default-off SHADOW producer. File header says not wired to service loop; complete current natural L12 plus mandatory post-verdict plus separate risk path not proven. |
| N02 | BLOCKED | Producer line284 requires SHADOW; natural DEMO source/EA allowlist/compile/wire vectors and fault rehearsal not tested. No EA/broker action taken. |
| N03 | BLOCKED | No converged natural combined source/schema/EA release is established; legacy/current contracts incompatible. This audit did not cherry-pick PR418/419 or mutate migration history. |
| N04 | NOT_EXECUTED | Full required combined suite, MetaEditor build, disposable PostgreSQL migrations and partial-fill/cancel/out-of-order/unknown/revocation acceptance remain unexecuted. Focused suite is only component evidence. |
| N07 | BLOCKED | Pure campaign helper can reason about child, but durable request contract line40 is PARENT-only. Child lifetime slot, broker-proved release and durable partial-fill/close recovery need implementation and independently bound child artifact tests. |

## Executed tests

1. Six suites: raw admission, pair admission, closed candle, tradeplan candidate v2, durable risk contract, S5 campaign sizing — **95 passed in 18.22s**.
2. Five suites: context epoch, directional thesis, microboost, tradeplan containment, lifecycle runtime — **116 passed in 7.24s**.
3. External diagnostic harness executes same/mixed-direction comparisons at explicit diagnostic gap settings and legacy/current risk-ID validation. Its output records observations and does not present defect reproduction as implementation PASS.

The XML/logs preserve per-test receipts. `strategy-testcases.json` inventories the 211 executed cases. `strategy-acceptance-matrix.json` maps all 35 acceptance clauses and preserves null acceptance numerators/denominators. Related test-family counts are traceability leads, not coverage percentages.

## Safe implementation order

Bind v3.1 source and policy/schema mapping first. S03 requires separate symbol-activity admission and direction hypothesis contracts, additive persistence/runtime changes, and mixed-direction/coverage/gap/restart tests; deleting the direction-change condition alone would break mandatory downstream directional assumptions. S04 requires canonical dual admission and versioned maturity policy; numeric maturity/gap/SLA values must not be invented. S05 needs an explicit versioned target-universe contract and fixtures proving a nearer H1/D1 target cannot be bypassed. Then R02/R03 can consume the actual immutable current candidate plus L12/post-verdict proof with account policy and reconciliation binding. Only after these gates should natural producer/EA convergence and child proof proceed.

Immediate safe deliverables are this source-bound report, complete clause matrix and runnable local diagnostic. They add no execution authority. The inspected checkout remains clean; no original dirty checkout edit, commit, push, PostgreSQL connection/mutation, Docker operation, Railway change, EA compile/run or broker effect occurred in this audit.

**Engineering closure: INCOMPLETE. Runtime/database: NOT_MEASURED. Broker: NOT_MEASURED. Natural DEMO and REAL readiness: not established.**
