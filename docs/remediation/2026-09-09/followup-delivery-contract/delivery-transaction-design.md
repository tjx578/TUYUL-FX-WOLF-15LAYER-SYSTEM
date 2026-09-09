# S03 delivery, lifecycle and analysis emission transaction contract

Status: IMPLEMENTATION TARGET / NOT WIRED. The typed protocol and identity rules have offline validation; the following persistence/relay/consumer transactions are not implemented or accepted. This design grants no production, hypothesis, risk or broker authority.

## Source-grounded problem

At candidate `0f7a98b28d9b3ee3a72cd1309ada2236b6a9e3fb`, `PostgresActivityRuntime.evaluate` persists evaluation/activity attachment/snapshot in its dedicated PostgreSQL binding. It does not persist a lifecycle delivery outbox. `StrategyLifecycleV2Repository.fetch_unlinked_events` reads only the legacy inbox joined with pressure_outbox. `episode_event_from_outbox_row` reads legacy directional/pressure fields and not the typed S03 evaluation. `storage/pressure_outbox.py` requires its existing PairAdmission rule, selection proof and lifecycle identity; an S03 grant is not that contract. These requirements must not be weakened or bypassed by inventing legacy fields.

The canonical source bytes remain the selected SSOT v3.1 copy under source-binding, SHA256 6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902. Its advisory-to-canonical upgrade retains the existing lifecycle. `analysis/strategy_5scr_v3/episode_hash.py` already excludes transport/deployment IDs from lifecycle identity. This design preserves that ownership.

## Decision: two local transactions with at-least-once delivery

Use a dedicated typed S03 analysis-delivery channel. Do not route it through legacy pressure_outbox or relabel it as CanonicalPressureEmissionV3. This avoids making directional admission a prerequisite for delivery of activity-quality evidence.

The producer and consumer may use different databases. There is no distributed atomic commit. Each database owns its local atomic boundary; acknowledgement loss is handled by replay of immutable delivery IDs. A same-database deployment must still prove database/transaction ownership instead of assuming that two DSNs name one transaction domain.

| Component | Logical owner and transaction | Required writes | Forbidden capability |
|---|---|---|---|
| S03 source | Existing PostgresActivityRuntime writer, dedicated activity DB | Evaluation, snapshot, activity sequence cursor, immutable delivery outbox in one transaction | Choosing strategy lifecycle/direction, reserving risk, commands |
| Relay | Bounded relay under configured source-outbox delivery identity | Lease/attempt/ack status on that outbox only; submit exact immutable bytes | Rewriting evaluation/policy, assigning lifecycle, producing emissions |
| Lifecycle consumer | Existing configured lifecycle/evidence owner, consumer DB | Inbox disposition, lifecycle state, activity mapping, cursor and analysis-emission outbox in one transaction | Parallel independent lifecycle writer, risk/trade outbox, commands |
| Analysis emission reader | Read/relay access to analysis-state notification only | Optional delivery receipt in its own bounded destination | Treating notification as pressure admission, TradePlan or order |

Concrete integration targets are `storage/strategy_5scr_activity_runtime.py`, `storage/strategy_5scr_shadow_evidence_v2_repository.py:persist_owner_bundle`, and its caller in `services/pressure_outbox/lifecycle_shadow_worker.py`. These are future extension points, not evidence of wiring. The existing owner bundle is atomic for its existing rows; common writer fencing, locked reload/reduction and S03 inbox/emission support remain required. A second worker with a separate in-memory reducer cannot be declared the same owner merely by sharing its name.

## Typed fields and identity

`contracts/strategy_5scr_activity_delivery.py` defines ActivityConsumerScopeV1, ActivityDeliveryV1 and ActivityLifecycleEmissionLinkV1. All reject extra fields and authority injection. Scope values are explicit logical references; possession of them is not authenticated policy approval or lease ownership.

| Identity | Definition / ownership |
|---|---|
| activity_id / evaluation_id / admission_id | Preserve exact validated S03 receipt values. Direction conflict remains quality evidence. |
| delivery_id | Digest of protocol version, consumer-scope hash and evaluation_id. Mint once when the source commits that evaluation for that scope. |
| source_snapshot_id / source_revision | Reference the committed source snapshot; verify its exact binding and evaluation membership in producer storage. These fields are not a delivery ordering cursor. |
| activity_sequence / previous_delivery_id | Producer allocates a monotonically increasing sequence per scope/activity under the source transaction lock. First sequence is 1 with no predecessor; later entries reference the immediately previous delivery. A new evaluation can increment this sequence without changing raw ledger revision. |
| delivery payload_hash | Canonical hash of the complete immutable envelope. Same delivery_id with different bytes is a conflict; never last-write-wins. |
| strategy_lifecycle_id | Selected or recovered by the existing lifecycle owner using its bound policy. Never derive it from delivery/evaluation/admission ID or restart/deployment ID. Existing advisory lifecycle is attached, not duplicated. |
| attachment_id | Digest of consumer scope and activity_id. Lifecycle ID is a stored value, not a new-key component; remapping must conflict and require explicit migration/reconciliation. |
| analysis_emission_id | Digest of scope, owner-selected lifecycle ID, lifecycle policy hash, owner material-state hash and emission purpose. Excludes retry, receipt time, source revision, snapshot and delivery ID. No material change means no new emission. |

The link object is a proposed bundle member, not a receipt claiming a database commit. Its emission represents an analysis-state notification. It is deliberately not the existing legacy pressure-emission contract and is not a strategy signal.

## Producer transaction

1. Lock the activity ledger and sequence cursor; validate the configured source/attestor and current policy binding.
2. Evaluate complete durable evidence and persist evaluation plus snapshot using the current transaction.
3. For a new `(consumer_scope, evaluation_id)` only, allocate the next activity sequence and predecessor. Persist the first immutable delivery payload and its hash, referencing the exact committed source scope/snapshot/evaluation.
4. A duplicate evaluation reuses the first delivery bytes and sequence. A differing envelope at that key aborts/quarantines; it does not allocate another sequence.
5. Commit all writes together. On rollback none of the evaluation/delivery/sequence advancement may survive. Never submit to a remote consumer inside this transaction.

The future migration must add uniqueness for delivery_id and `(scope, activity_id, activity_sequence)`, plus local source-reference integrity. Do not edit already-published migration 20260909_01. No DDL has been added or executed in this follow-up.

## Consumer transaction and recovery

1. Verify configured scope, producer binding, SSOT/policy identity and source receipt. Authenticate the service identity separately. Acquire the common owner fence and scope/symbol lock used by every lifecycle writer; reject an expired/replaced fence.
2. Look up the inbox key before applying current-time gates. An already committed identical delivery returns its stored outcome without new effects, even if its original grant has since expired. A changed payload at the same key is quarantined.
3. For a new delivery, verify the per-activity predecessor against the committed cursor. Gaps remain WAITING_PREDECESSOR. An unseen older sequence, conflicting predecessor or source clock/revision regression requires reconciliation. Missing delivery cannot be skipped because a newer grant looks usable.
4. Reload lifecycle/mapping state inside the transaction. Apply current policy/coverage/expiry at owner decision time, including exclusive valid_until. PENDING is diagnostic only. GRANTED may request open/attach analysis only. SUSPENDED and RECONCILIATION_REQUIRED update an existing mapping; they cannot create a replacement lifecycle or erase frozen admission lineage. A missing expected mapping is deferred/reconciled, not fabricated.
5. Existing lifecycle owner chooses the lifecycle and material state. A policy digest in a payload is not approval to default missing merge/transition semantics. Preserve advisory-to-canonical identity and independent directional-hypothesis checks.
6. Atomically persist inbox outcome, activity mapping, lifecycle update, cursor and any genuinely new analysis emission. Check mapping and emission payload consistency under unique constraints. A material-identity collision aborts the transaction.
7. Acknowledge only after commit. Crash before commit leaves no effects and must discard staged in-memory reducer state. Crash after commit but before acknowledgement replays to the stored inbox outcome. Restart reconstructs cursor/mapping/lifecycle from the consumer DB.

Receiver/source retention must preserve predecessor and dedupe records through the bound replay horizon. No uncalibrated retention duration, lease TTL or lifecycle merge policy is selected here. Rollout must bind those policies, writer identity, grants, DSNs, migrations and feature flags; all runtime activation remains off until that packet is complete.

## Acceptance matrix

| ID | Scenario | Required result | Current evidence |
|---|---|---|---|
| D01 | BUY@0 -> SELL@150 -> BUY@300 with valid coverage | One source activity at 300s, conflict remains quality; deliver through owner to one lifecycle with zero hypothesis/risk/order authority | Source fixture + typed envelope locally tested; real consumer NOT_IMPLEMENTED |
| D02 | Identical duplicate / serialized replay | Same delivery, mapping and emission IDs; no repeated effect | Pure contract PASS; DB/runtime NOT_EXECUTED |
| D03 | Same delivery ID, changed payload | Quarantine, preserve first committed outcome | Pure comparison PASS; DB constraint NOT_IMPLEMENTED |
| D04 | Missing predecessor / late unseen delivery | Wait or reconcile; no cursor skip or clock rewind | Pure ordering PASS; durable recovery NOT_IMPLEMENTED |
| D05 | New evaluation with unchanged raw revision | New activity sequence; same lifecycle mapping; emission only on material change | Pure identity/order PASS; allocation transaction NOT_IMPLEMENTED |
| D06 | Source crash before/after commit | Outbox/evaluation atomicity; retry of same immutable delivery | NOT_EXECUTED |
| D07 | Consumer crash at each write and after commit-before-ack | Full rollback or exact replay of committed outcome; no duplicate lifecycle/emission | NOT_EXECUTED |
| D08 | Concurrent deliveries and legacy/S03 writers | Common fence/lock; one committed mapping and material emission | NOT_EXECUTED |
| D09 | Existing advisory lifecycle gains canonical activity | Retain strategy_lifecycle_id | Mapping invariant PASS; actual policy/consumer integration NOT_IMPLEMENTED |
| D10 | Expired grant, missing policy/attestor/owner fence | Explicit denial/defer with no authority; duplicate ACK does not renew grant | Owner-runtime enforcement NOT_IMPLEMENTED |
| D11 | Scope/lifecycle-owner/authority tampering | Reject or quarantine before effects | Contract negatives PASS; credentials/network/storage enforcement NOT_EXECUTED |

The existing 45 PostgreSQL tests cover their earlier persistence/recovery scope only. Closing this matrix requires a separate bound integration suite through the real producer, relay and lifecycle owner, including migration and database evidence. Local serialization tests are not process/database restart proof.
