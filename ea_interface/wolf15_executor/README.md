# Wolf15 Dumb Executor - Shadow Scaffold

`Wolf15_DumbExecutor_Shadow.mq5` implements the outbound HTTPS
register/heartbeat/poll/claim/report path for `wolf15.mt5.exec.v1`.

It is intentionally incapable of calling `OrderSend` and refuses to initialize
when `InpExecutionEnabled=true`.

Current scope:

- exact runtime `ACCOUNT_LOGIN` and broker-server binding;
- fresh account, position, and 30-symbol broker capability snapshots from one
  EA instance;
- an audited XM mapping with `XAUUSD -> GOLD` and `XAGUSD -> SILVER` while the
  other 28 canonical symbols map directly;
- one-command polling and atomic claim;
- local HMAC-SHA256 verification of the immutable signed-wire payload before
  command JSON is parsed;
- startup golden-vector verification of the MQL5 SHA-256, base64url, and HMAC
  implementation;
- fail-closed source, mode, expiry, price, symbol, and volume validation;
- atomic local persistence of the exact report body and current claim token
  before the first report request;
- restart recovery that reconciles server status before any resend, reuses the
  original report id/body, and durably stores a rotated claim token before use;
- local append-only shadow ledger;
- idempotent `WOULD_EXECUTE` / `WOULD_REJECT` report.

Before compiling:

1. Add the bridge `https://` URL to MT5 Tools -> Options -> Expert Advisors ->
   Allow WebRequest.
2. Pre-provision an EDUMB UUID in Agent Manager.
3. Provision the executor-scoped bearer token and command-verification material
   into the approved DPAPI CurrentUser vault. Never put either scoped secret,
   or either root secret, in an EA input, profile, template, or `.set` file.
4. Start the one-shot `wolf15-credential-broker.exe` helper as the same Windows
   user as MT5. Bind its vault digest, executor, account-reference digest,
   broker server, verification key id, pipe name, and timeout explicitly.
5. Set `InpCredentialFile` to the local `\\.\pipe\...` reference exposed by
   that helper. Set `InpExpectedAccountReferenceSha256` and
   `InpCommandVerificationKeyId` to their nonsecret packet bindings. The helper
   serves one framed credential envelope to one current-user pipe client and
   then exits.
6. Set the exact account id, `sha256:<64 hex>` login hash, and broker server.
   The compiled `WOLF15_XM_30_V1` universe is recorded in
   `broker_maps/xmglobal-mt5-10.csv` and must match the target broker probe.

Attach exactly one EA instance for an executor id. Do not attach one copy per
chart: all instances would poll the same executor queue, and the wrong instance
could claim a command intended for another symbol. The single EA can inspect
and validate all 30 mapped symbols regardless of its host chart.

The backend now freezes and stores a `wolf15.mt5.exec.signed-bytes.v2` envelope
and exposes read-only command-status reconciliation. This EA authenticates the
exact frozen bytes locally, verifies their SHA-256 digest, and only then parses
the command. A failed envelope is quarantined without sending a report derived
from untrusted command fields.

Before a report is sent, the EA writes one binary pending record to its local
MT5 file sandbox under `MQL5/Files/Wolf15Executor/`. The record contains the
short-lived claim token and exact report body, but never the executor bearer
token, verification key, or signing root secret. Its content is protected by
an HMAC made with the executor-scoped verification key. Do not upload or share
this file. A restart reconciles the command-status endpoint before retrying the
same body. Corrupt, modified, key-mismatched, or account-mismatched local state
blocks initialization/polling instead of being discarded. If the verification
key is rotated while a report is pending, restore the previous scoped key long
enough to reconcile that record rather than deleting it.

The backend independently validates command signatures and remains SHADOW by
default. This EA still has no broker mutation calls. Runtime restart drills on
the demo terminal, durable risk reservation, and a separately governed DEMO
execution implementation remain required before any broker order test.

## Deterministic restart drill

Run this only against a bridge that already has the signed-wire-v2 migration
and backend from this branch. Keep the global kill switch engaged and the
executor in `SHADOW`.

1. Compile and attach this EA with its normal account-bound inputs and
   `InpRestartDrillHoldAfterDurableSave=true`.
2. Enqueue exactly one synthetic, signed `SHADOW` command through an audited
   operator session. This repository intentionally does not ship a production
   command-producer shortcut.
3. Wait for `REPORT_DURABLE` followed by `RESTART_DRILL_ARMED` in
   `MQL5/Files/Wolf15Executor/shadow-ledger.csv`. At this point the pending
   binary record exists and no report POST has occurred.
4. Restart the EA (remove and reattach it, or restart the terminal) without
   deleting anything under `MQL5/Files/Wolf15Executor/`. Recovery is not held
   by the drill input: it checks server status first and then submits the exact
   persisted report if the command is still non-terminal.
5. Require one terminal `SHADOW_COMPLETED` or `SHADOW_REJECTED` command, one
   terminal report id, removal of the pending binary, `filled_volume=0`, null
   broker order/deal/position identifiers, and zero broker positions/orders
   created by Wolf15.
6. Set `InpRestartDrillHoldAfterDurableSave=false` after the single drill so
   later SHADOW reports use their normal immediate delivery path.

The drill input defaults to `false`. It acts only after the exact report has
been atomically persisted and before the first report request; it never alters
signature validation, command validation, recovery, or broker state.

## Separate engineering DEMO artifact

`Wolf15_DumbExecutor_Demo.mq5` is the separately compiled, explicitly armed D0
artifact. It is not a switch inside the SHADOW EA. Its only broker-capable
lineage is `ENGINEERING_DEMO_CANARY`, with strategy, research, scorecard,
real-money, and production authority all fixed to false.

The DEMO artifact contains exactly one `OrderSend` call, preceded by signed
command validation, two freshness-sensitive `OrderCheck` passes around the
blocking submit acknowledgement, and a durable one-way submit marker. Restart
recovery never calls `OrderSend`; it reconciles exact MT5 order/deal/position
history and attached SL/TP first. An immediate fill remains ambiguous until
that complete lineage is recovered, and missing, partial, or conflicting
evidence never releases reconciliation authority.

The EA's own heartbeat always reports `broker_ledger_reconciled=false`. A
separate direct-broker reconciliation gate must establish that fact; the EA
cannot self-promote. See
[`docs/runbooks/mt5-d0-engineering-demo-canary.md`](../../docs/runbooks/mt5-d0-engineering-demo-canary.md).

This source does not authorize compilation output deployment, executor
promotion, kill-switch disarm, or broker submission.
