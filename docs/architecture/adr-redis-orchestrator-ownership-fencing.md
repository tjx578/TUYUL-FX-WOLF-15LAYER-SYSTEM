# ADR: Redis ownership and fencing for the standalone orchestrator

**Status:** Accepted repository architecture

## Context

`wolf15-orchestrator` is the sole runtime owner of orchestration and compliance
evaluation. Multiple process instances may overlap during replacement or
failure recovery, but at most one generation may publish orchestrator state,
heartbeat, kill-switch state, or release ownership.

An earlier design proposal suggested a PostgreSQL advisory lock when no other
guard could provide this invariant. The implemented source instead uses Redis
atomic scripts, one lease key, and a monotonically increasing fence generation.

## Decision

Redis is the canonical coordination substrate for orchestrator ownership:

- acquisition atomically increments the counter and stores owner plus generation;
- renewal succeeds only for the exact owner and generation;
- state, heartbeat, kill-switch, and release writes re-check that same pair;
- a stale owner is rejected even if its process later resumes;
- loss of ownership moves the instance to `STANDBY`; it does not create a new
  execution authority.

We do **not** add a PostgreSQL advisory lock in parallel. A second lock would
create ambiguous ordering, split-brain failure modes, and no stronger guarantee
unless every writer observed both guards identically. PostgreSQL remains the
durable authority for journals, ledgers, audit records, and recovery snapshots;
it is not a second orchestrator-owner registry.

## Required configuration and invariants

`ORCHESTRATOR_LEASE_KEY` and `ORCHESTRATOR_FENCE_COUNTER_KEY` must be shared by
all candidate and predecessor instances in one environment. The renew interval
must be less than half the lease TTL. The fence counter must never be reset as a
rollback or cleanup operation. `/healthz` proves process/supervisor liveness;
only an owner may pass `/readyz` as writer-ready.

Redis loss is fail-closed. No process may infer ownership from cached memory,
restore the counter from a local default, publish unfenced state, or promote a
standby merely because the current lease cannot be read.

## Consequences and limits

This decision establishes single-writer coordination; it does not make every
Redis value durable. Process restart with Redis intact differs from Redis data
loss. Durable recovery claims are limited by
[`orchestrator-state-authority-recovery.md`](orchestrator-state-authority-recovery.md)
and by the configured Redis persistence plus PostgreSQL recovery contracts.

This ADR does not alter strategy, risk, command, execution, MT5, or broker
authority. `TradeOutboxWorker` remains API-owned WebSocket projection delivery.

## Source and verification anchors

- `services/orchestrator/ownership.py`
- `services/orchestrator/state_manager.py`
- `tests/test_orchestrator_fencing.py`
- `tests/integration/test_orchestrator_redis_pubsub.py`
- `docs/runbooks/orchestrator-cutover.md`

Repository tests establish source behavior only. Runtime replica, persistence,
and cutover acceptance require separate evidence.
