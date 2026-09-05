# API/orchestrator single-owner cutover

This is a future operations runbook. Repository verification does not authorize
Railway mutation.

## Preconditions

- exact candidate commit/tree and both manifest digests are frozen;
- API contains no autonomous orchestrator constructor;
- legacy embed flag is absent or literal false;
- execution controls remain false and kill switch remains engaged;
- active commands, reservations, and executable outboxes are zero;
- rollback deployment identities are recorded.

## Ordered cutover

1. Deploy the API candidate with `railway.toml` and verify API startup contains
   no `services.orchestrator.state_manager` compliance tick.
2. Wait until all predecessor API instances have terminated.
3. Deploy or start the standalone candidate with `railway-orchestrator.toml`.
4. Verify exactly one standalone heartbeat owner and no API-owned tick.
5. Verify API read endpoints reflect the standalone durable state.

Do not overlap an embedded predecessor API with a standalone writer. Rollback
must restore only one owner: never start an embedded API while standalone is
active. Database migration, execution activation, MT5, and broker actions are
outside this runbook.
