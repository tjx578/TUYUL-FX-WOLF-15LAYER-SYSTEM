# S01, S03 and pinned API dependency verification

Program verdict remains **INCOMPLETE / HOLD; 0/6 engineering milestones DONE**.
S01 source binding and contract mapping are complete within the stated scope;
S01 policy/schema closure is not complete. S03 now has a tested versioned pair
activity evaluator and analyzer/pipeline reporting integration; full durable
runtime acceptance is not complete. This package is not a DEMO binding packet.

Tested source commit: `385188d02097d3fd5fb3e48cb9669613b8ff6ea7`. Final combined suite: **334 expected = 334 recorded, zero failure/error/skip**, with unchanged source hashes throughout execution. Whole-source Ruff lint and format pass (1,372 files).

## S01 source binding

The reference selected by the user is repository SSOT v3.1 from commit
`dd27ae87d0207466caad4c3e098224112ac0eaf7`, path
`docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md`.
Its exact Git bytes are 86,002 bytes and SHA-256
`6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902`.
The existing [archived source](../source-binding/selected-ssot-v3.1.md) is identical.

The historical assessment receipt names 85,414 bytes and SHA-256
`2cd41d01fdd3661af59284c78df669f7b312a7b7e4870f1620cfcfbe1aedb624`.
Those exact bytes were not present in the supplied ZIP. The 588-byte/13-line
difference does not establish semantic equivalence. No older-copy parity or
approval for a new strategy version is inferred.

[S01 review](s01-review.md), [source comparison](s01-source-comparison.json),
[contract inventory](s01-contract-binding.json), and
[rule-contract-test matrix](s01-rule-contract-test-matrix.json) bind 56 paths,
15 rule groups, all 35 acceptance clauses, 18 policy registries and 36 validated
numeric section references. The matrix is anchored to the pre-change checkpoint
`261a3b476055accc3d0ea45ebc80a910e0e80f6b`; the new S03 contracts are described below.

Resolved interpretation differences include the full SSOT versus the stub,
the normative target universe precedence, and the solver ordering precedence.
Open items include missing pressure-contract fields, the unresolved lifecycle
enum entry, candidate order type, the separate-route/conflict decision table,
active policy selections, and mandatory L12/post-verdict natural-path binding.
The current legacy target-kind contract is still H4-only; this work does not
claim an S05 repair.

## S03 implementation and boundary

New code lives in `contracts/strategy_5scr_pair_activity.py`,
`analysis/strategy_5scr_pair_activity.py`, and
`analysis/strategy_5scr_pair_activity_report.py`.
`analyze_signal_throttle_events(..., pair_activity_context=...)` invokes it when
the caller supplies bound coverage, explicit policy and decision time.
The pipeline carries validated receipts under `pair_activity_v31` in its
observability payload. This field does not substitute the existing directional
`PairAdmissionGrant`, select a risk profile or create a command.

The current `SignalThrottleLiveAnalyzer.snapshot()` service caller supplies no
v3.1 context; its new field remains UNBOUND. No service rollout, completeness
attestor or active policy was fabricated to turn the hook into live readiness.
There is no new database writer or automatic recovery job in this patch.

| Fixture / expected behavior | Actual behavior asserted by the tests |
| --- | --- |
| BUY@0, SELL@150, BUY@300; complete coverage and explicit valid continuity | One 300-second activity; GRANTED for activity only; current direction quality CONFLICT; hypothesis/risk/execution flags false |
| No caller-bound raw context | UNBOUND; a process buffer is not treated as a complete ledger |
| UNKNOWN or INCOMPLETE raw coverage | Same activity retained; SUSPENDED; no admission ID |
| Gap beyond the explicitly bound policy | Same activity suspended, not split or finalized solely by the gap |
| Cross-symbol event | Finalizes the prior activity; finalizer identity/time must match the exact next global row |
| Continued global source after finalization | Prior unexpired receipt remains valid; global source stoppage still suspends |
| Duplicate or reordered replay | Stable identity and no raw-count inflation from duplicate stable IDs |
| Late/backfill changes pre-admission lineage or removes required prior evidence | Reconciliation required; no silent replacement of an earlier admission |
| Current direction changes after the first grant | Current quality changes; first-threshold identity, lineage and expiry remain immutable |
| JSON snapshot restored in a fresh Python subprocess | Identical replayed audit and identity for the same bound input |
| Tampered direction, finalizer, global watermark or authority fields | Receipt rejected; no conversion into the legacy grant |

Fixture gap/TTL values are explicitly test policy values. Only the 300-second
minimum duration is taken directly from the selected normative SSOT. No test
value is an active production policy.

[Kernel report](s03-kernel-report.md) and
[independent source review](s03-independent-review.md) describe the corrected
finalized-block freshness defect and remaining limitations. Local JSON/file and
subprocess replay prove serialization/reconstruction, not PostgreSQL atomicity,
transactional watermark recovery or runtime crash acceptance. Source facts from
THROTTLED/DOWNGRADED are not silently merged into a logical pulse without a bound
producer identity; that S03 acceptance item remains open.

## Dependency and CI evidence

All applicable requirements were installed unchanged in a separate Windows
Python 3.11.9 environment. Pydantic 2.9.2, pydantic-settings 2.5.2, pytest 8.3.2
and pytest-asyncio 0.24.0 are verified; 42 applicable direct constraints and
`pip check` pass. The existing uvloop platform marker excludes it on Windows.
This is not proof of the Linux-only dependency path or full required CI.
MCP, MetaTrader5 and psutil are absent from the API environment. The existing
isolated native MCP fixture job remains mandatory and unchanged.

The exact final test counts, hashes, source commit and command are in
[followup-validation.json](followup-validation.json). Initial API and legacy
runs at checkpoint 261a3b47 passed 93 and 33 cases respectively. These overlap
with the final combined suite and are not added to it as unique coverage.

An intermediate combined run was discarded because source bytes changed during
import cleanup. A subsequent frozen run exposed a real test failure: a legacy
test assumed arrival order for two facts with identical timestamps, while the
producer uses raw-ID tiebreak ordering. The behavior was reproduced identically
on checkpoint and candidate at two fixed timestamps, with matching AST hashes
for all four recording/ordering methods. The test now checks both deterministic
orders, event-type fields and non-execution. Production ordering is unchanged;
the failed test was not skipped or softened.

Remote CI jobs had runner_id=0 and empty steps at observation. No source-test
execution or billing cause is inferred, and no workflow rerun or billing action
was performed. Main moved from 77315095 to
`2b060f8e55beedd21340cda37bfb0a70c238386e` via PR #424, adding four Codex/settings
files. Those settings were not adopted into this worktree. Candidate-source
tests do not claim a tested merge with the changed main.

## Remaining acceptance and release status

- S01: policy/schema/example parity and mandatory authority mapping remain open.
- S03: authoritative completeness binding, active policy registry, logical pulse
  normalization, durable ledger/attachment/SLA and runtime recovery remain open.
- CI: the pinned local API dependency gap is addressed; full required remote
  execution, Linux closure and database integration are not demonstrated.
- R01/E02/E06: actual account/server DEMO, risk profile and independent-reader
  identity remain unbound. EA, canary scope/window and complete artifact are
  still required before broker work.

Main merge/deployment, Railway changes, database mutation and broker execution
remain HOLD. Original checkout changes and all original input bytes are preserved.
