# Strategy 5S-CR Lifecycle V2 Shadow Evidence Owner

Status: dark-by-default capability. It has no execution authority and must not
be used to invoke C2, C3, the EA bridge, or broker execution.

## Boundary

The only supported flow is:

```text
PairAdmissionV2
→ StrategyLifecycleV2
→ Evidence Job V2
→ authoritative closed-candle snapshot
→ non-executable shadow result
→ durable legacy-vs-V2 comparison
```

Transport identity remains lineage. `pressure_outbox.lifecycle_id`, clean-block
IDs, and watch IDs never become the Strategy Lifecycle V2 identity.

## Hard invariants

Every rollout stage keeps:

```text
execution flags          = OFF
kill switch              = DEFAULT_ENGAGED
C3 issuer                = NOT INVOKED
valid_for_execution      = false
execution_authority      = false
risk reservations        = 0 from this path
final-signal outbox rows = 0 from this path
execution commands       = 0 from this path
broker entities          = 0 from this path
```

The database CHECK constraints enforce the two false authority fields. Startup
readiness validates complete column shapes and complete PostgreSQL constraint
definitions, not names alone.

## Runtime flags

All flags are scoped to the pressure-outbox service. Defaults are inert:

```text
STRATEGY_5SCR_LIFECYCLE_V2_ENABLED=false
STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY=true
STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED=false
STRATEGY_5SCR_LIFECYCLE_V2_EVIDENCE_OWNER_WRITER_ENABLED=false
STRATEGY_5SCR_SHADOW_EVIDENCE_V2_ENABLED=false
STRATEGY_5SCR_SHADOW_EVIDENCE_V2_SHADOW_ONLY=true
```

Do not add these values to a shared Railway variable set. Apply them only to
the dedicated pressure-outbox service and only for the current rollout stage.

## Rollout stages

### 1. Dark

Apply Alembic revision `20260804_01`. Leave every new writer and worker flag
false. Preflight must report both Lifecycle V2 schemas ready.

### 2. Writer-only

Enable Lifecycle V2, its shadow-only dual write, then its owner writer:

```text
STRATEGY_5SCR_LIFECYCLE_V2_ENABLED=true
STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY=true
STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED=true
STRATEGY_5SCR_LIFECYCLE_V2_EVIDENCE_OWNER_WRITER_ENABLED=true
STRATEGY_5SCR_SHADOW_EVIDENCE_V2_ENABLED=false
```

Acceptance: each canonical admission has one durable Lifecycle V2 link and at
most one pending evidence job. Missing raw-admission lineage fails closed.

### 3. Shadow evidence

Only after writer-only counts and restart recovery are stable:

```text
STRATEGY_5SCR_SHADOW_EVIDENCE_V2_ENABLED=true
STRATEGY_5SCR_SHADOW_EVIDENCE_V2_SHADOW_ONLY=true
```

The worker freezes `decision_time` on its first attempt. A restart reuses the
same job and decision time, so the same closed candles produce the same hash.
Any forming or future candle fails the job without a snapshot or comparison.

### 4. Thirty-pair soak

Observe all configured pairs. Restart the pressure-outbox service during the
soak and compare grouping and hashes before and after restart. Do not set a
target lifecycle or candidate count; require determinism and explained
differences.

### 5. Authority review

Review the comparison corpus. Promotion is a separate design and PR. This
runbook does not authorize changing production evidence ownership.

## Metrics

`StrategyShadowEvidenceV2Repository.metrics_snapshot()` reports:

- emission, legacy lifecycle, and V2 lifecycle counts;
- legacy-per-V2 compression ratio;
- events and clean blocks per V2 lifecycle;
- evidence completeness and WAIT/NO_TRADE/CONDITIONAL counts;
- durable legacy-vs-V2 divergence count;
- completed-job-without-snapshot restart-parity failures.

Every comparison dimension may differ, but every missing or different
dimension must carry a reason code.

## PostgreSQL acceptance

Use a disposable database. Run migrations through head, then run:

```text
tests/integration/test_5scr_lifecycle_v2_postgres.py
tests/integration/test_5scr_shadow_evidence_owner_v2_postgres.py
```

Acceptance includes atomic admission/lifecycle/job persistence, restart parity,
as-of closed-candle enforcement, definition-aware readiness, and zero deltas in
risk reservations, final-signal outbox, execution commands, and broker entities.

## Rollback

Turn off the evidence worker first, then the owner writer. Preserve the tables
for audit. Do not downgrade the migration while any writer is running.
