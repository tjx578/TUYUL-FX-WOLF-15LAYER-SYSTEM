# MT5 D0 Engineering DEMO Canary

Status: code and test implementation only; deployment and broker execution are
not authorized.

Purpose: prove one broker-DEMO execution path without treating the result as
Strategy 5S-CR, research, scorecard, production, or real-money evidence.

## Frozen authority boundary

The only D0 source is `ENGINEERING_DEMO_CANARY`. Its signed command contains:

```text
strategy_authority          = false
strategy_scorecard_eligible = false
research_result_eligible    = false
live_real_money_allowed     = false
demo_only                   = true
order_role                  = PARENT
max_broker_effects          = 1
```

The command must bind exactly one executor UUID, account, broker server,
canonical symbol, broker symbol, snapshot, and broker-minimum volume. It has no
risk reservation and cannot be relabelled as `signal_json`. Magic `150016`,
`GTC` lifetime, margin mode, balance, and equity are also signed bindings and
are rechecked by the EA before submission.

Generic DEMO delivery remains blocked. D0 commands can only be queued by
`EngineeringDemoCanaryAuthorityV1`, and only while the global kill switch is
engaged. Arming opens the exact persisted window and disengages the switch in
the same PostgreSQL transaction. PostgreSQL permits only one open D0 window
globally.

## Separate executor artifact

`Wolf15_DumbExecutor_Demo.mq5` is a separate build from the SHADOW EA. The
SHADOW source still contains no `OrderSend` call. The DEMO artifact:

- refuses non-DEMO accounts and mismatched account/server/executor/symbol
  bindings;
- starts only with `InpDemoExecutionArmed=true`;
- verifies the immutable HMAC-signed wire envelope before parsing command
  fields;
- requires attached SL and TP, exact broker-minimum volume, a flat account,
  fresh quote, and bounded spread/price drift;
- performs `OrderCheck` both before the blocking `SUBMITTING` acknowledgement
  and again from a fresh tick immediately before the single compiled
  `OrderSend` call;
- HMAC-protects and atomically persists its local state before submission;
- treats `submit_attempted=true` as irreversible and never submits from restart
  recovery;
- reconciles exact magic, symbol, comment, order, deal, and position lineage
  from current broker state and MT5 history;
- refuses to finalize `FILLED` until exact volume, order, deal, position, and
  attached SL/TP evidence have been recovered; an immediate deal remains
  `AMBIGUOUS_REQUIRES_RECONCILIATION` until then;
- blocks on multiple or conflicting broker artifacts.

An expired queued window becomes `EXPIRED`. An expired in-flight window becomes
`RECONCILIATION_REQUIRED`; its command remains reportable and the kill switch is
re-engaged. A broker outcome, terminal rejection, or ambiguity also re-engages
the switch automatically. Engaging the switch before `SUBMITTING` atomically
revokes a claimed D0 command. Once `SUBMITTING` has been accepted, the command
is treated as in-flight and the global D0 slot remains reserved for
reconciliation.

Every D0 report must repeat the exact signed volume, reference price, SL, and
TP. State-specific broker evidence is mandatory: broker acceptance needs an
order ticket and retcode, rejection needs a retcode and zero broker effects,
and `FILLED` needs complete order/deal/position lineage plus exact fill volume
and price. Partial fills never release the global slot.

## Direct broker truth is still a hard gate

The DEMO EA deliberately emits:

```text
broker_ledger_reconciled = false
```

It cannot promote its own account snapshot to reconciled. Before any future D0
queue or arm action, a separate authenticated, read-only broker reconciliation
must prove current positions, pending orders, order history, and deal history
for the exact account and server. Until that authority records a fresh
reconciled snapshot, issuance fails closed.

Database mirrors, stale heartbeats, or an operator assertion are not direct
broker truth.

## Code verification

The source-only gate uses disposable PostgreSQL/Redis and no broker connection:

```powershell
python -m alembic heads
python -m pytest -q tests/test_mt5_engineering_demo_canary.py `
  tests/test_mt5_demo_ea_safety.py tests/test_mt5_execution_protocol.py

$env:WOLF15_RUN_POSTGRES_INTEGRATION = "1"
$env:DATABASE_URL = "postgresql://<disposable-test-dsn>"
python -m pytest -q `
  tests/integration/test_mt5_bridge_postgres_e2e.py `
  tests/integration/test_mt5_executor_governance_postgres.py `
  tests/integration/test_mt5_engineering_demo_canary_postgres.py `
  --timeout=60
```

Compile `Wolf15_DumbExecutor_Demo.mq5` with MetaEditor and require zero errors
and zero warnings. Do not commit the generated `.ex5` artifact.

## Future runtime gate

None of these steps are authorized merely because this code exists. A future
operator must separately prove:

```text
G3 clean runner                  PASS
D0 code/test/compile             PASS
fresh dedicated DEMO executor   ONLINE
direct broker reconciliation    PASS
unattributed / ambiguous         0 / 0
open positions / pending orders 0 / 0
kill switch                     ENGAGED
exact one-order approval        RECORDED
```

Only then may the default-off issuance flag be enabled for one queue action.
Arming requires the exact confirmation phrase implemented by
`scripts/issue_mt5_engineering_demo_canary.py`. There is no permission here to
run that script, deploy Railway, change production data, attach the EA, or send
an order.

The CLI preflights its evidence path before mutating database authority. If an
ARM transaction commits but the local manifest cannot be persisted, the CLI
reports a distinct committed-evidence failure and makes a fail-closed attempt
to re-engage the kill switch. That outcome is not an aborted/no-mutation result
and requires operator reconciliation.
