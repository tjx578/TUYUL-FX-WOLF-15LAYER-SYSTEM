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
from untrusted command fields. Durable claim/report retry storage remains 3A-2
work and must be completed before DEMO promotion. The backend independently
validates command signatures and remains SHADOW by default.
