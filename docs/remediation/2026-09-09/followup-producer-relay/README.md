# S03 producer outbox and relay checkpoint

Status: **INCOMPLETE / HOLD**. Source commit `5219624a92253b66fe8bc67a1acace99b71e61e7`. This is a partial implementation of the delivery design; there is no connected lifecycle consumer and no owner fencing yet. No milestone is closed.

The opt-in service factory accepts `WOLF15_PAIR_ACTIVITY_DELIVERY_SCOPE_PATH`. Its strict scope must match the runtime producer binding and environment; invalid scope returns `ACTIVITY_DELIVERY_SCOPE_INVALID`. Absent scope preserves the existing non-delivery path. A file is configuration, not authenticated owner or policy approval.

`PostgresActivityRuntime.evaluate` calls the producer allocator before its existing connection transaction commits. Source snapshot membership, revision and binding are checked. The cursor is a locked row updated with evaluation/snapshot/outbox, not `nextval()`. Repeated evaluation keeps the original envelope and sequence even when encountered in another snapshot. Migration `20260909_02` adds source/predecessor foreign keys, unique identities and an immutable-payload UPDATE trigger; the published previous migration is unchanged. Actual migration and trigger behavior remain unexecuted.

The bounded relay claims an explicit-duration lease, commits it, then sends the stored UTF-8 payload outside the database transaction. It waits for the predecessor's ACK. Only an ACK matching delivery ID/hash and committed outcome marks delivery acknowledged; expired/replaced lease ACK is ignored. Timeout leaves the original payload retryable. The injected transport still needs authentication and an actual consumer endpoint. Relay lease fencing is **not** lifecycle owner fencing.

| Expected | Actual evidence |
|---|---|
| Same bytes/identity on retry, source membership failures rejected, invalid service scope explicit | Local unit/model tests pass; fake transport/store are identified in tests |
| Evaluation, snapshot, outbox and counter rollback together | Real PostgreSQL test authored; NOT_EXECUTED |
| Concurrent allocation and predecessor ordering | Real PostgreSQL tests authored; NOT_EXECUTED |
| Database payload cannot be rewritten | Trigger and real PostgreSQL negative test authored; NOT_EXECUTED |
| Consumer inbox/lifecycle/mapping/cursor/emission atomicity and stale owner denial | NOT_IMPLEMENTED; legacy writer still requires common fencing |
| D01 through actual lifecycle owner, D07 ACK loss after consumer commit, D09 advisory attachment | NOT_IMPLEMENTED |

Latest local subset: **176 passed, 0 failures, 0 skips**, Windows Python 3.11.9 / pinned API environment. Do not add this count to earlier overlapping suites. An earlier migration-head assertion was corrected; another attempt hit FileNotFoundError in a long temporary fixture path and passed with a shorter label. Receipts retain both failed attempts.

The original **45** PostgreSQL tests are unchanged. **Seven** producer/relay tests have a separate runner and CI step; see `acceptance-inventory.json` for exact collected identities and partial D01-D11 mapping. All **52** PostgreSQL cases skipped in the disabled control. On this source commit, the separate strict runner rejected all seven skips. PostgreSQL acceptance is false. One Alembic head and offline SQL generation passed; upgrade execution remains NOT_EXECUTED.

Next dependency: implement locked lifecycle recovery/reduction and a common owner fence covering every legacy/S03 writer, then wire the authenticated relay destination to that owner transaction. Consumer policy/attestor/owner binding must be explicit; no default lifecycle or directional authority is invented. S03 delivery remains separate from the V1 strategy consumer migration. Required Linux/GitHub checks, disposable database execution, DEMO account/EA/risk/canary/independent broker reader remain open. Railway and broker were not changed.
