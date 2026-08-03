# MT5 SHADOW matrix audit

`scripts/audit_mt5_shadow_matrix.py` is a read-only verifier. It cannot build,
sign, or enqueue an execution command. This preserves the execution authority
boundary: commands must originate from a separately audited operator session,
and the repository does not ship a reusable command-producer shortcut.

## Preconditions

- executor mode is exactly `SHADOW`;
- global executor kill switch is active;
- EA version is exactly `0.21-shadow-xm30-diag`;
- protocol is exactly `wolf15.mt5.exec.v1`;
- signed-wire-v2 database guarantees are ready;
- heartbeat and account snapshot are fresh;
- the account has zero open positions;
- the snapshot publishes the exact `WOLF15_XM_30_V1` mapping;
- no unrelated active command exists.

Use a PostgreSQL role with `SELECT` access only when running this against a
deployed environment. Do not provide the command-signing root secret, executor
token, verification key, login hash, or broker account number to this script.

## Manifest

The operator session exports identities only:

```json
{
  "schema_version": "wolf15.mt5.shadow-matrix-manifest.v1",
  "run_id": "xm30-acceptance-20260803-a1",
  "phase": "A1",
  "symbol_universe": "WOLF15_XM_30_V1",
  "executor_id": "00000000-0000-4000-8000-000000000000",
  "broker_server": "XMGlobal-MT5 10",
  "expected_ea_version": "0.21-shadow-xm30-diag",
  "expected_protocol_version": "wolf15.mt5.exec.v1",
  "started_at_utc": "2026-08-03T08:00:00+00:00",
  "commands": [
    {
      "canonical_symbol": "EURUSD",
      "broker_symbol": "EURUSD",
      "command_id": "00000000-0000-4000-8000-000000000001"
    }
  ]
}
```

`A1` requires exactly one command. `A2` requires all 30 audited pairs exactly
once. Unknown manifest fields are rejected so credentials cannot be added by
accident.

## Run

```bash
python scripts/audit_mt5_shadow_matrix.py \
  --manifest local/operator-manifest.json \
  --out local/matrix-audit-result.json
```

The output is always written, including fail-closed and unexpected failures.
The audit passes only when every command has exactly one `WOULD_EXECUTE` report,
`filled_volume=0`, null broker identifiers, no `broker_entities`, no unexpected
reports, no remaining active commands, and zero final open positions.

The audit proves transport and mechanical SHADOW validation only. It does not
prove durable risk reservation, final-signal authority, DEMO execution, or
broker order correctness.

## PostgreSQL integration-test safety

Destructive integration fixtures require all four values:

```text
WOLF15_RUN_POSTGRES_INTEGRATION=1
WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS=YES_I_UNDERSTAND
DATABASE_URL=postgresql://...@127.0.0.1/...test...
WOLF15_POSTGRES_TEST_DATABASE=<exact database name from DATABASE_URL>
```

The target must be loopback, its name must contain `test` or `audit`, the
explicit guard must match it, and `SELECT current_database()` must confirm the
same name after connection. New connections must also return:

```sql
SELECT current_setting('wolf15.environment_class', true);
-- DISPOSABLE_TEST

SELECT current_setting('wolf15.destructive_tests_allowed', true);
-- true
```

After taking its advisory lock, the fixture rejects any pre-existing rows in
the bridge executor, snapshot, command, report, broker-entity, or governance
audit tables. It snapshots and restores the complete global kill-switch row,
verifies exact restoration, and requires all operational tables to be empty
again before releasing the lock.
