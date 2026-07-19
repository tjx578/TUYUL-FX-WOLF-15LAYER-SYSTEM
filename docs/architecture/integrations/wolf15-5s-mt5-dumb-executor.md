# Wolf15 Strategy 5S-CR to MT5 Dumb Executor

Status: production foundation, live execution disabled by rollout policy

Protocol: `wolf15.mt5.exec.v1`
Decision authority: frozen Strategy 5S-CR proof / final SignalJSON only

Strategy 5S-CR Final is the primary candidate baseline. Strategy 5-S Final is
retained as the pre-Context-Resolution benchmark. The candidate is strong
provisional, not out-of-sample validated, and not production-proven.

## Architecture decision

Use the existing `TUYUL-FX-WOLF-15LAYER-SYSTEM` monorepo. Deploy the MT5 bridge
as a dedicated Railway service in the same Wolf15 Railway project.

Do not create a second strategy repository and do not deploy an independent
Railway project for the first production rollout.

The dedicated service boundary provides the required isolation without
duplicating strategy code, contracts, migration history, CI, or audit lineage.

```text
MT5 terminal / Wolf15_DumbExecutor
        |
        | outbound HTTPS only
        v
wolf15-ea-bridge (public domain, minimal API)
        |
        | Railway private network
        v
PostgreSQL command/report/snapshot ledger
        ^
        |
wolf15 trade/risk plane <- final SignalJSON <- frozen Strategy 5S-CR authority chain
```

### Railway service boundary

| Component | Public | Authority | Storage |
| --- | --- | --- | --- |
| `wolf15-engine` | No | Analysis and final constitutional verdict | Redis/PostgreSQL |
| `wolf15-trade` | No | Account/risk authorization and command creation | PostgreSQL |
| `wolf15-ea-bridge` | Yes, HTTPS | Transport, auth, lease, reports; no strategy | PostgreSQL |
| MT5 EA | Outbound client | Mechanical validation and broker side effect | Local append-only ledger |

The EA bridge uses `railway-ea-bridge.toml` and
`deploy/railway/start_ea_bridge.sh`. It must receive its own public domain and
must not share dashboard credentials.

Create a separate Railway project only when one of these boundaries becomes a
real requirement:

- a different legal owner or tenant;
- independent billing and operator access;
- strict network isolation between analysis and execution organizations;
- a separate disaster-recovery region;
- multiple production brokers that must not share a database or master key.

Those conditions do not justify duplicating the Git repository. A separate
Railway project may still deploy a service from this monorepo.

## Verified source facts

- `SignalPressureStateJSON` forcibly sets `final_direction=WAIT` and
  `valid_for_execution=false` in the current emitter.
- The two supplied July log exports are byte-identical (580 records each), so
  they are one observation set, not two independent samples.
- Those records contain pressure telemetry, not executable orders.
- The existing HTTP EA v3 reports heartbeat and account snapshots but does not
  poll, claim, or report execution commands.
- The existing execution worker pushes HTTP to `EA_BRIDGE_URL`; a terminal
  behind a VPS/NAT should instead open outbound HTTPS and pull commands.
- The repo already contains Agent Manager, EDUMB subtype, PostgreSQL, Railway
  service manifests, and constitutional execution boundaries.

## Non-negotiable promotion gate

Only `event=signal_json` may produce a command. All conditions below must be
true at promotion time:

```text
is_final_signal
valid_for_execution
execution_valid_now
tradeplan_valid
analysis_valid
direction_valid
signal_valid
final_direction in BUY, SELL
RR status is final and execution-grade
lifecycle anchor exists
strategy_5scr proof schema is complete and frozen
Context Resolution status is RESOLVED
H1 structure is confirmed by a closed candle
M15 closed structural break is followed by acceptance or failed-reclaim/retest
H4 structural TP1, M1 fill, and structural SL match the command exactly
fresh reconciled account snapshot exists
risk reservation exists
executor/account/broker mapping matches
```

Explicitly denied sources include pressure state, pressure summary, watch,
decision update, SignalThrottle, and pressure-tier events. Railway logs are an
audit/validation source and must never be scraped as the live order queue.

The locked authority chain is:

```text
Pressure -> Context Resolution -> H4 -> H1 -> M15 -> M1 -> Risk Engine
```

One rejection candle or a weakening-but-unconfirmed H1 must remain
`NO_TRADE_CONTEXT_UNRESOLVED`. See
`docs/strategy/strategy-5scr-final.md` for the frozen rule and validation record.

## Pull protocol

All executor mutations require:

```text
Authorization: Bearer <executor-scoped token>
X-Executor-Id: <pre-provisioned EDUMB agent UUID>
X-Request-Id: <unique request UUID>
```

The token is derived from `EXECUTOR_BRIDGE_AUTH_SECRET` and the executor UUID.
Commands are independently signed using `EXECUTOR_COMMAND_SIGNING_SECRET`.
Both secrets support a previous-key slot for controlled rotation.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/executors/register` | Bind a pre-provisioned EDUMB agent; mode is forced to SHADOW |
| `POST` | `/api/v1/executors/{id}/heartbeat` | Append account and broker capability snapshot |
| `GET` | `/api/v1/executors/{id}/commands/next` | Fetch one eligible command; `204` when empty |
| `POST` | `/api/v1/commands/{id}/claim` | Atomic claim and short lease |
| `POST` | `/api/v1/commands/{id}/reports` | Append idempotent state report; requires claim token |

## Exactly-once behavior

Exactly-once refers to the logical broker side effect, not packet delivery.

- command identity is immutable;
- `(account_id, idempotency_key)` is unique;
- one claim lease is active at a time;
- `(command_id, report sequence)` is unique;
- duplicate payloads are replay-safe;
- the same key with different content is rejected;
- terminal command states cannot transition back to active states;
- an ambiguous submit must reconcile broker order/deal/position history before
  any retry.

The EA local ledger must be persisted before and after `OrderSend`. A timeout
after submission is not permission to send again.

## Strategy 5S-CR risk profiles

Backtest statistics and production rollout use separate, explicit profiles:

```text
campaign closed-balance base = USD 1,000
campaign R                   = 5% = USD 50
parent maximum planned loss  = USD 50

BACKTEST_FULL_RISK
child maximum planned loss   = USD 50 (1.0R)

PRODUCTION_ADJUSTED
child maximum planned loss   = USD 25 (0.5R)
parent must be BE/protected before child
campaign open-risk cap       = 1.0R-1.25R
```

`risk/s5_campaign_risk.py` implements the broker-aware primitive:

```text
ticks_to_stop = abs(entry - stop) / tick_size
loss_per_lot  = ticks_to_stop * tick_value_loss + cost buffers
raw_volume    = campaign_R / loss_per_lot
final_volume  = floor(raw_volume / volume_step) * volume_step
```

The implementation never rounds volume upward and never clamps a calculated
volume up to the broker minimum. Floating equity affects safety checks but does
not increase the locked campaign R.

The current primitive implements the full-risk parent/child calculation. The
production-adjusted child multiplier and durable reservation ledger remain a
DEMO gate; production execution must stay disabled until both are integrated.

The initial account-wide open-risk cap is 10%. This is a rollout policy, not a
fact inferred from pressure logs.

## Deployment runbook

1. Merge only after contract, risk, migration, and router tests pass.
2. Run the migrator deliberately and verify revision `20260719_01`.
3. Create Railway service `wolf15-ea-bridge` from this repository.
4. Configure its config-as-code path as `/railway-ea-bridge.toml`.
5. Attach only `DATABASE_URL`; Redis is not command truth for this service.
6. Set independent 32-byte-or-longer auth and command signing secrets.
7. Give the service a public HTTPS domain and allow that URL in MT5 WebRequest.
8. Pre-provision the EA as `ea_subtype=EDUMB` in Agent Manager.
9. Derive its scoped token with
   `python -m scripts.derive_executor_token <executor-uuid>` in a secure shell.
10. Register the executor; verify the returned mode is `SHADOW`.
11. Run shadow validation until every final signal has exactly one terminal
    `WOULD_EXECUTE` or `WOULD_REJECT` result and zero broker side effects.
12. Promote to DEMO through a governed database/config change.
13. Promote to LIVE only after demo acceptance, reconciliation, and kill-switch
    drills pass.

## GO / NO-GO

GO now:

- strict protocol review;
- migration review;
- bridge deployment in SHADOW;
- historical replay and shadow correlation;
- MT5 compile and Strategy Tester validation.

NO-GO now:

- enabling LIVE on first deployment;
- using pressure telemetry as a direction or command;
- scraping Railway logs for live orders;
- allowing the EA to calculate risk, direction, entry, SL, or TP;
- merging before the MQL5 executor compiles and shadow replay is deterministic.

## Pressure-to-tradeplan module

The analysis path now contains:

- `contracts/strategy_5scr_pressure.py`: immutable pressure, lifecycle, market
  evidence, and tradeplan contracts;
- `analysis/strategy_5scr_pressure_to_tradeplan.py`: Railway-log/current-event
  normalizer, SHA-256 deduplication, legacy replay lifecycle grouping, and the
  fail-closed 5S-CR proof/tradeplan assembler;
- `tests/test_strategy_5scr_pressure_to_tradeplan.py`: pressure invariants,
  replay deduplication, Context Resolution gates, future-leakage rejection,
  broker-aware target floor, direction authority, and deterministic plan IDs.

The output event is `strategy_5scr_tradeplan_candidate`, not `signal_json`.
Even a strategy-ready plan remains:

```text
is_final_signal=false
valid_for_execution=false
next_required_stage=RISK_RESERVATION
```

Only a later transaction may reserve risk and write the final `signal_json`
outbox row atomically. A LIVE pressure event without `source_clean_block_id` or
a stable `source_watch_id` defers with
`STRATEGY_5SCR_CANONICAL_LIFECYCLE_REQUIRED`. Legacy synthetic anchors are
limited to deterministic replay and cannot become production lineage.

## Remaining production increments

This foundation now enforces the frozen 5S-CR proof at final-signal and command
promotion boundaries. It does not claim OOS or production validation.

The durable pressure transport is now implemented behind
`SIGNAL_PRESSURE_OUTBOX_ENABLED=false`:

- migration `20260720_01` creates a distinct `pressure_outbox`, atomic
  per-lifecycle sequences, and the idempotent `strategy_5scr_inbox`;
- the engine writes canonical-lineage pressure into PostgreSQL before log
  sampling, while retaining `SignalPressureStateJSON` for observability;
- the dedicated `services.pressure_outbox.runner` worker claims events with a
  PostgreSQL lease and `FOR UPDATE SKIP LOCKED`, retries exponentially, and
  moves exhausted or integrity-violating events to `DEAD`;
- at-least-once redelivery is collapsed by the inbox `event_id` key and
  `payload_hash`; a reused ID with a different hash is quarantined;
- replay reads `pressure_outbox` rows through lifecycle sequence, never Railway
  logs. Historical JSON remains a backtest-only compatibility input.

Apply the migration and deploy `deploy/railway/start_pressure_outbox.sh` before
enabling the engine producer flag. The worker stops at `WAITING_EVIDENCE` until
the closed-candle provider is supplied. It never routes pressure to the EA.

The next increments are:

1. connect the implemented pressure-to-tradeplan assembler to the live closed-
   candle evidence provider and lifecycle repository, then replay-validate its
   Context/H4/H1/M15/M1 inputs without future leakage;
2. persist the resulting non-executable tradeplan candidate;
3. persist campaign risk locks and reservations atomically with final-signal
   outbox rows;
4. add local cryptographic verification and durable restart/retry storage to
   the MQL5 scaffold, then compile it in MetaEditor;
5. run SHADOW, DEMO, then a symbol-limited LIVE canary.
