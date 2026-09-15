# D0 canary control capabilities V3

This contract closes four control-plane gaps without granting deployment or broker authority.

1. A canary command is created only from an immutable, canonical JSON authority packet. The packet contains the preselected command UUID, exact order parameters, one-command limit, maximum two `OrderCheck` calls, maximum one `OrderSend`, and no retry or child order.
2. Direct MT5 observations are hashed before persistence. The server derives `broker_ledger_reconciled`; heartbeat payloads cannot promote this result for frozen issuance.
3. `SHADOW -> DEMO` requires a one-use authority packet bound to executor, account, server, configuration, and final-SHADOW receipt. Registration and heartbeat remain unable to promote mode. `DEMO -> SHADOW` remains the containment path and may also carry a one-use packet.
4. The frozen issuer receives an explicit process-local capability bound to one packet digest and one command UUID. It does not read the global execution toggle. An identical durable command returns `ALREADY_ISSUED`; different content under the same identity is rejected.

The global kill switch remains engaged while the command is queued. Opening a scoped canary window, any real `OrderCheck`, and any real `OrderSend` remain separately authorized operations.

## Evidence classes

- Unit and disposable-PostgreSQL tests prove code and schema behavior only.
- A local bundle or EX5 digest proves artifact identity only.
- Deployment identity, terminal installation, direct broker truth, and broker effects require separate runtime evidence.
- No local PASS may be promoted to `EXECUTION_READY` or DEMO order authority.
