# wolf15-ea-bridge

**Role:** authenticated transport between the backend command ledger and an MT5
executor.

- Manifest: [`../../../railway-ea-bridge.toml`](../../../railway-ea-bridge.toml)
- Start script: [`../../../deploy/railway/start_ea_bridge.sh`](../../../deploy/railway/start_ea_bridge.sh)
- ASGI app: [`../../../services/ea_bridge/main.py`](../../../services/ea_bridge/main.py)

The service owns executor registration/snapshot/poll/claim/report HTTP transport
and signed-wire readiness checks. It does not own strategy, compliance scheduling,
or permission to execute an order.

Startup rejects missing database configuration or weak auth/signing references.
`/healthz` is liveness; `/health/ready` checks database, migrations, governance,
and signed-wire schema. Secrets are referenced by configuration name only.

Verify with executor bridge API, governance, signed-wire, and MT5 protocol tests.
