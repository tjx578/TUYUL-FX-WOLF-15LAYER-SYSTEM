# Wolf15 Dumb Executor - Shadow Scaffold

`Wolf15_DumbExecutor_Shadow.mq5` implements the outbound HTTPS
register/heartbeat/poll/claim/report path for `wolf15.mt5.exec.v1`.

It is intentionally incapable of calling `OrderSend` and refuses to initialize
when `InpExecutionEnabled=true`.

Current scope:

- exact runtime `ACCOUNT_LOGIN` and broker-server binding;
- fresh account, position, and broker symbol capability snapshots;
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
3. Derive the executor bearer token from the server auth secret.
4. Derive that executor's scoped command-verification key on a trusted machine
   with `EXECUTOR_COMMAND_SIGNING_SECRET` set:

   ```powershell
   python scripts/derive_executor_command_key.py <executor-uuid>
   ```

5. Set `InpCommandVerificationKeyId` to the active
   `EXECUTOR_COMMAND_SIGNING_KEY_ID`, and set
   `InpCommandVerificationKey` to the script's `hex:<64 hex>` output. Never put
   the root signing secret in MT5.
6. Set the exact account id, `sha256:<64 hex>` login hash, broker server,
   canonical symbol, and broker symbol.

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
