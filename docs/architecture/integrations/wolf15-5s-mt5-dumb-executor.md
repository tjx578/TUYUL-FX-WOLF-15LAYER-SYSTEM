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
For signed wire v2, the backend derives a separate 32-byte verification key per
executor and signs an immutable base64url payload. The EA verifies those exact
bytes; it must never reconstruct Python JSON for signature verification. Both
root secrets support a previous-key slot for controlled rotation.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/executors/register` | Bind a pre-provisioned EDUMB agent; mode is forced to SHADOW |
| `POST` | `/api/v1/executors/{id}/heartbeat` | Append account and broker capability snapshot |
| `GET` | `/api/v1/executors/{id}/commands/next` | Fetch one eligible command; `204` when empty |
| `POST` | `/api/v1/commands/{id}/claim` | Atomic claim and short lease |
| `POST` | `/api/v1/commands/{id}/reports` | Append idempotent state report; requires claim token |
| `GET` | `/api/v1/executors/{executor_id}/commands/{command_id}/status` | Reconcile terminal state after an ambiguous client restart; never returns a claim token |

Poll and claim retain the legacy `command` object and additionally return a
`signed_envelope` for newly enqueued commands:

```text
wire_version      = wolf15.mt5.exec.signed-bytes.v2
payload_encoding  = base64url
payload_b64       = exact frozen canonical command bytes
payload_sha256    = sha256:<64 lowercase hex>
algorithm         = HMAC-SHA256
key_id            = versioned key id
executor_id       = bound EDUMB UUID
signature         = base64url:<43 characters>
```

PostgreSQL stores this envelope at enqueue time. JSONB remains queryable but is
not the signature authority. Existing pre-migration rows are explicitly marked
`legacy-json-v1`; new rows default to signed wire v2 and are protected by
`ck_execution_command_signed_wire_complete`.

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
2. Run the migrator deliberately and verify revision `20260803_01` or newer.
3. Create Railway service `wolf15-ea-bridge` from this repository.
4. Configure its config-as-code path as `/railway-ea-bridge.toml`.
5. Attach only `DATABASE_URL`; Redis is not command truth for this service.
6. Set independent 32-byte-or-longer auth and command signing secrets.
7. Give the service a public HTTPS domain and allow that URL in MT5 WebRequest.
8. Pre-provision the EA as `ea_subtype=EDUMB` in Agent Manager.
9. Derive its scoped token with
   `python -m scripts.derive_executor_token <executor-uuid>` in a secure shell.
10. Derive its independent command-verification key with
    `python -m scripts.derive_executor_command_key <executor-uuid>` in a secure
    shell. Never copy the root signing secret to MT5.
11. Register the executor; verify the returned mode is `SHADOW`.
12. Run shadow validation until every final signal has exactly one terminal
    `WOULD_EXECUTE` or `WOULD_REJECT` result and zero broker side effects.
13. Promote to DEMO through a governed database/config change.
14. Promote to LIVE only after demo acceptance, reconciliation, and kill-switch
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
outbox row atomically. A LIVE pressure event without canonical Pair Admission
and an `ANALYSIS_READY` radar-selection proof defers with
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

Production log validation also proves that pressure qualification and canonical
lineage arrive in different events. `pressure_radar_gate_v1` therefore creates
a deployment-scoped provisional manifest at `ticks >= 3` plus an allowed stage,
then associates a later clean-block interval without allowing the latest
one-tick row to erase the latched qualification. Exact `context_version` is not
a join key because it changes across otherwise stable structural snapshots.
See [Pressure Radar Gate v1 validation](pressure-radar-gate-v1-validation.md)
for the frozen provisional predicate and legacy 10-pair baseline. That archive
does not contain the newer Pair Admission authority and cannot approve rollout.

Migration `20260720_02` makes that deferred association durable:

- `pressure_radar_events` deduplicates on `(deployment_id, event_id)` and
  rejects identity reuse with a different payload hash;
- `pressure_radar_manifests` persists the qualifying payload, latched stage and
  ticks, context signature, expiry, lineage state, and optional outbox link;
- ingestion takes a PostgreSQL advisory transaction lock scoped to deployment
  and symbol before loading active manifests `FOR UPDATE`;
- a provisional or reserve event cannot enter `pressure_outbox`;
- the transition to `ANALYSIS_READY` and canonical pressure-outbox enqueue use
  one PostgreSQL transaction, so a crash cannot commit only one side;
- duplicate delivery after a committed write returns the same manifest and
  outbox event without advancing the lifecycle sequence;
- database constraints preserve `final_direction=WAIT`,
  `valid_for_execution=false`, and `is_final_signal=false`.

The engine uses this path only when `SIGNAL_PRESSURE_RADAR_WRITE_ENABLED=true`
in addition to both existing outbox master/write flags. All three flags default
to `false`. The legacy direct-writer fallback is forbidden: engine preflight
rejects master+write without radar, and the pipeline will not invoke the direct
writer when radar authority is absent.

Apply the migration, create the dedicated Railway service from
`railway-pressure-outbox.toml`, and set its service variables before enabling
any runtime path. Railway variables are service-scoped: writer flags belong to
the engine, while dispatcher and consumer flags belong to the pressure worker.
`SIGNAL_PRESSURE_OUTBOX_ENABLED` remains the master kill switch in each service.

The fail-closed rollout order is:

1. dark: engine master/write are `false`; worker
   `PRESSURE_OUTBOX_EXPECTED_PHASE=dark` and all four feature flags are `false`;
2. radar capture: after migration plus fresh Pair Admission shadow checks, engine
   master/write/radar-write become `true`; worker remains in the dark phase so
   no row can be claimed;
3. dispatch: worker phase becomes `dispatcher`, with master/dispatch `true` and
   write/consumer `false`; delivery stops at durable inbox status `RECEIVED`;
4. consume: worker phase becomes `consumer`, with master/dispatch/consumer
   `true` and write `false`; shadow processing covers new deliveries and the
   previously received backlog.

The startup preflight verifies the exact phase/flag contract plus all migration
tables and indexes before the worker loop starts. All feature flags default to
`false`. The consumer stops at `WAITING_EVIDENCE` until the closed-candle
provider is supplied, and pressure is never routed to the EA.

The next increments are:

1. apply migration `20260720_02`, validate radar schema preflight, and shadow
   compare the atomic durable path against fresh global-raw-ledger Pair
   Admission capture (using the frozen 10-pair set only as a provisional
   selection regression baseline) before
   enabling `SIGNAL_PRESSURE_RADAR_WRITE_ENABLED`;
2. connect the implemented pressure-to-tradeplan assembler to the live closed-
   candle evidence provider and lifecycle repository, then replay-validate its
   Context/H4/H1/M15/M1 inputs without future leakage;
3. persist the resulting non-executable tradeplan candidate;
4. persist campaign risk locks and reservations atomically with final-signal
   outbox rows;
5. run the signed-wire golden-vector and durable report restart drills in the
   actual MT5 terminal; the MQL5 scaffold now implements both gates and
   compiles without broker mutation calls;
6. persist campaign risk locks and reservations and implement the separately
   governed DEMO executor path;
7. run SHADOW, DEMO, then a symbol-limited LIVE canary.
