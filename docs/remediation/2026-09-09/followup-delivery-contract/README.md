# S03 delivery contract and corrected hosted-runner diagnosis

**INCOMPLETE / HOLD; 0/6 milestones complete.** Source commit `a25b41cf020a0ffb349aa6dfe3e34d6184e2d45e` adds a draft typed delivery/attachment protocol and offline identity/order checks. It does not connect a new producer outbox, relay, lifecycle consumer or database transaction.

## Runner interpretation correction

The repository `/actions/runners` endpoint lists **self-hosted runners only**. Its empty result never established that GitHub-hosted Linux was unavailable. Earlier wording that combined that inventory with Linux availability must be read with this correction. See [the REST API definition](https://docs.github.com/en/rest/actions/self-hosted-runners#list-self-hosted-runners-for-a-repository) and [GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).

At candidate `0f7a98b28d9b3ee3a72cd1309ada2236b6a9e3fb`, `.github/workflows/ci.yml` specifies `runs-on: ubuntu-latest` for all seven jobs. The actual Python job labels also contain ubuntu-latest. Both the push CI [run 34281716405](https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM/actions/runs/34281716405) and pull-request CI [run 34281720281](https://github.com/tjx578/TUYUL-FX-WOLF-15LAYER-SYSTEM/actions/runs/34281720281) have the annotation:

> The job was not started because your account is locked due to a billing issue.

This is GitHub's reported reason for those jobs not starting. No unpaid amount, account history or wider billing diagnosis is inferred. Billing remediation remains excluded. No rerun, runner registration, payment, provider/host operation or capacity probe occurred. Workflow bytes are bound to the candidate Git head and corroborated by job labels; no executed checkout is claimed.

## Implemented protocol scope

- ActivityDeliveryV1 preserves the full validated S03 evaluation, explicit consumer/owner/policy references, source snapshot/revision and a stable delivery ID. A model being valid does not authenticate the source or approve its referenced policy.
- The producer's activity sequence and predecessor are distinct from raw ledger revision. New evaluations without new raw facts can still be ordered. Missing predecessor waits; unseen stale or regressing delivery requires reconciliation.
- Same delivery ID and payload gives DUPLICATE_NO_EFFECT; the same ID with a changed payload is quarantined. Retry metadata is not part of the immutable payload.
- Attachment identity is keyed by activity/scope. The owner-selected lifecycle is a value that cannot be silently changed into a new row. Existing advisory lifecycle identity is preserved by this mapping invariant, but actual advisory-to-canonical integration remains unimplemented.
- Analysis-emission identity depends on owner lifecycle/material state/policy/purpose, excluding delivery/retry/snapshot counters. The object is a draft analysis-state notification link, not a pressure emission, hypothesis, TradePlan or command.
- Hypothesis, risk and execution authority remain false; nested model-copy tampering and extra execution-shaped fields are rejected.

The [transaction design](delivery-transaction-design.md) specifies producer-local outbox commit, relay retry semantics, consumer-local inbox/lifecycle/mapping/cursor/emission commit, single-owner fencing, rollback, acknowledgement loss and recovery. The design is ready to guide implementation; none of those new SQL/transport/owner transactions has been exercised or added by this patch. No migration was changed.

## Verification

Final bounded suite: **126 collected =126 exact JUnit identities passed; zero failure/error/skip**. Source stayed unchanged in the final run. It includes the new protocol tests and existing pair-activity, lifecycle-worker fixture and pressure-emission containment tests. All results are local/offline; lifecycle worker tests use fake repositories. Serialization replay is not database/process restart evidence. Three generated schemas and examples pass JSON Schema validation. Ruff lint/format pass across1,388 Python files.

A prior iteration failed two predecessor-shape tests; the missing model-level pairing guard was fixed and the final same-scope suite passed. Both receipts are retained. Final review was performed by the parent; specialist agents were not retried after their earlier usage-limit failure. No completed independent final agent review is claimed.

These126 results overlap earlier241/613 scopes and must not be summed. The original45 PostgreSQL acceptance cases were not rerun or changed. Their previous skipped control remains the latest evidence; real PostgreSQL migration/persistence/recovery and Linux acceptance remain NOT_EXECUTED.

## Remaining closure work

1. Implement producer outbox+sequence allocation in the existing source transaction, with local reference/uniqueness constraints.
2. Implement the dedicated typed relay and consumer inbox, common owner fencing and locked lifecycle reduction. Do not bypass the legacy directional outbox gate or invent its missing fields.
3. Bind real policy/attestor/owner identities and exclusive-expiry checks at consumption; current strategy consumer remains V1.
4. Exercise D01-D11 in the transaction design through real disposable PostgreSQL, including concurrency, rollback, predecessor recovery and commit-before-ack failure.
5. Obtain executed required CI and separate actual migration receipts. Passing the previous45-case persistence subset does not close lifecycle/emission integration or natural DEMO.
