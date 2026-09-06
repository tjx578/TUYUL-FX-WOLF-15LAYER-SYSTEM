# Orchestrator state authority and recovery contract

This contract describes authority and recovery; it does not authorize rollout
or execution. Missing, corrupt, stale, or scope-mismatched state is a hold—not a
reason to synthesize a replacement.

| State | Writer / authority | Storage and commit boundary | Startup and recovery rule |
| --- | --- | --- | --- |
| Account snapshot | Account-state producer; orchestrator is reader only | Canonical operational Redis `ACCOUNT_STATE` key; durable lineage remains the producer/PostgreSQL contract where implemented | Load the newest valid scoped record and revalidate freshness. Missing or stale input holds compliance. Never create a dummy account. |
| Risk snapshot | Risk subsystem; orchestrator is reader only | Canonical operational Redis `TRADE_RISK` key; durable lineage remains the producer/PostgreSQL contract where implemented | Revalidate identity/version/freshness. Hydration cannot grant execution authority. |
| Last compliance state | Current fenced orchestrator generation | Fenced Redis state publication; durable history belongs in PostgreSQL audit/journal paths | A new owner may read the last committed record as history, but must re-evaluate source inputs before publishing. Unfenced or malformed records are rejected. |
| Evaluation watermark | Current fenced orchestrator generation | `state_revision` in the committed, fenced orchestrator state record | Only a successful commit advances it. An interrupted evaluation is not completed. A recovered revision never makes old inputs fresh. |
| Inflight evaluation | Process that began the evaluation | Process-local until the authoritative commit boundary | Shutdown must finish or cancel it before release. A new process repeats evaluation only when no committed result exists, and must not replay downstream effects. |
| Lease and fence generation | Redis atomic ownership scripts | Redis lease plus monotonic counter | All instances share one namespace. Expiry permits a new, higher generation; an old generation can never write or release ownership. Counter loss is fail-closed. |
| Heartbeat and readiness | Current owner for writer readiness; every process for liveness | Redis fenced heartbeat plus local health supervisor | Heartbeat is telemetry, not durable business authority. Healthy standby is live but not writer-ready. |
| `recovery_count` | Current `StateManager` process | Process memory | Diagnostic transition hysteresis for the current process. Reset on process restart is intentional; it must not replace committed state or authorize execution. |
| Trade-outbox WebSocket projection | API `TradeOutboxWorker` | Existing outbox plus API projection cursor contract | API may recover projection delivery idempotently; it never owns orchestration, command issuance, or broker execution. |

## Recovery sequence

1. Start fail-closed and connect to required stores.
2. Read durable account/risk inputs and the last committed orchestrator state.
3. Validate schema, scope, identity, version, and freshness.
4. Acquire a new Redis lease generation; do not publish before ownership.
5. Reconcile the last committed watermark with any interrupted work. Only a
   durable, complete commit counts as completed.
6. Re-evaluate current inputs. Do not replay downstream effects from historical
   state and do not inherit freshness.
7. Publish state and heartbeat through fenced writes only.

Shutdown stops intake, settles or cancels process-local inflight evaluation,
publishes `SHUTDOWN` only if still owner, and conditionally releases the exact
owner/generation. A shutdown race must not let a predecessor overwrite a newer
owner.

## Evidence boundary

Unit and disposable Redis tests may establish process-restart idempotency,
interrupted-versus-committed behavior, and stale-owner rejection. Redis-server
loss and PostgreSQL reconstruction remain separate scenarios. Production
durability, replica overlap, and rollback are runtime acceptance gates and are
not inferred from repository documentation.
