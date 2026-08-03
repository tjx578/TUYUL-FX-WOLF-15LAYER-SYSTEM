# MT5 C3 Operator-Controlled SHADOW Runbook

Status: code gate only; Railway execution flags remain off.

This runbook queues exactly one risk-authorized Strategy 5S-CR command.  It is
not a service loop, scheduler, automatic consumer, DEMO promotion, or LIVE
authority.  The MT5 EA remains the SHADOW-only build with no `OrderSend`.

## Hard invariants

```text
source_event                    = signal_json
execution_mode                  = SHADOW
kill_switch                     = ENGAGED
entry_role                      = PARENT
broker_execution                = FORBIDDEN
MT5_ORDER_SEND_ENABLED          = false
unrelated active commands       = 0
one operator run                = one selected reservation
terminal report                 = WOULD_EXECUTE or WOULD_REJECT
filled_volume                   = 0
broker order/deal/position IDs  = null
broker entities                 = 0
```

The issuer selects the reservation it just created.  It cannot fall through to
an older pending outbox row.  The append-only governance ledger records
`C3_SHADOW_REQUESTED`, followed by either `C3_SHADOW_QUEUED` or a redacted
`C3_SHADOW_ABORTED` event.

## Preconditions

Prove all of these before invoking the issuer:

1. Alembic is at `20260803_04`.
2. C1 and C2 schema readiness are green.
3. Global kill switch is engaged.
4. Target executor is `ONLINE`, non-revoked, and `SHADOW`.
5. No nonterminal command exists for the target executor.
6. The account heartbeat and snapshot are fresh, the account is flat, and the
   broker-symbol capability is present.
7. A fresh, non-executable `strategy_5scr_tradeplan_candidate` exists and is
   ready for risk reservation.
8. Record the current governance version.  The issuer rejects a stale version.

Do not put account numbers, login hashes, tokens, root signing secrets, or
verification keys in command-line arguments or manifests.

## Issue one command

Run inside the already deployed `wolf15-ea-bridge` container so the database
and command-signing root are available.  Set execution flags only for this one
issuer process.  Do not persist them as Railway service variables.

```bash
env \
  EXECUTION_ENABLED=true \
  SIGNED_COMMAND_BRIDGE_ENABLED=true \
  EXECUTION_COMMAND_PRODUCER_ENABLED=true \
  RISK_RESERVATION_ENABLED=true \
  TRADE_OUTBOX_WRITE_ENABLED=true \
  EA_COMMAND_DELIVERY_ENABLED=true \
  LEGACY_PUSH_EXECUTION_ENABLED=false \
  MT5_ORDER_SEND_ENABLED=false \
  python -m scripts.issue_mt5_risk_shadow_command \
    --operator-run-id <unique-run-id> \
    --confirm-run-id <same-unique-run-id> \
    --actor <operator-identity> \
    --reason "C3 EURUSD broker-connected SHADOW acceptance" \
    --tradeplan-id <5scr-plan-id> \
    --executor-id <executor-uuid> \
    --broker-symbol EURUSD \
    --expected-governance-version <current-version> \
    --ttl-seconds 120 \
    --out /tmp/wolf15-c3-shadow-manifest.json
```

The manifest contains identity and lineage only.  If the command was committed
but the process lost its response, repeat with the same run ID and target; the
issuer recovers the durable manifest instead of creating another command.

## Read-only acceptance audit

Keep MT5 connected and wait for its terminal report.  Then run:

```bash
python -m scripts.audit_mt5_risk_shadow_command \
  --manifest /tmp/wolf15-c3-shadow-manifest.json \
  --timeout-seconds 180
```

Acceptance is one JSON result with `status=PASS`, a SHADOW terminal command,
one `WOULD_EXECUTE` or `WOULD_REJECT` report, zero filled volume, null broker
IDs, and zero broker entities.  The auditor performs SELECT operations only.

## Stop conditions

Do not retry with a different run ID when any of these occurs:

- governance version changed;
- kill switch disengaged;
- executor is not SHADOW or not online;
- another command is active;
- candidate, heartbeat, or snapshot is stale;
- C1/C2 schema readiness is red;
- any broker effect is reported;
- the manifest cannot be recovered for an interrupted request.

Inspect the durable audit and command ledgers first.  A failed or interrupted
reservation expires fail-closed; it is never permission to create a second
command blindly.
