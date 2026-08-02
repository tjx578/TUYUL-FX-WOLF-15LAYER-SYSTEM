# Wolf15 Dumb Executor - Shadow Scaffold

`Wolf15_DumbExecutor_Shadow.mq5` implements the outbound HTTPS
register/heartbeat/poll/claim/report path for `wolf15.mt5.exec.v1`.

It is intentionally incapable of calling `OrderSend` and refuses to initialize
when `InpExecutionEnabled=true`.

Current scope:

- exact runtime `ACCOUNT_LOGIN` and broker-server binding;
- fresh account, position, and broker symbol capability snapshots;
- one-command polling and atomic claim;
- fail-closed source, mode, expiry, price, symbol, and volume validation;
- local append-only shadow ledger;
- idempotent `WOULD_EXECUTE` / `WOULD_REJECT` report.

Before compiling:

1. Add the bridge `https://` URL to MT5 Tools -> Options -> Expert Advisors ->
   Allow WebRequest.
2. Pre-provision an EDUMB UUID in Agent Manager.
3. Derive the executor bearer token from the server auth secret.
4. Set the exact account id, `sha256:<64 hex>` login hash, broker server,
   canonical symbol, and broker symbol.

The backend now freezes and stores a `wolf15.mt5.exec.signed-bytes.v2` envelope
and exposes read-only command-status reconciliation. The current EA still only
checks that a signed command is present: local HMAC verification against the
frozen bytes and durable command/report retry storage are 3A-1/3A-2 work and
must be completed and compiled before DEMO promotion. The backend independently
validates command signatures and remains SHADOW by default.
