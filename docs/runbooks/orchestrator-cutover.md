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
- `WOLF15_EMBED_ORCHESTRATOR` is absent or literal `false` in the effective API
  environment, not merely in repository defaults;
- the standalone lease/fence keys are shared by old and new deployments, lease
  TTL/renewal configuration passes startup validation, and `/healthz` plus
  `/readyz` report the expected supervisor state.

## Ordered cutover

1. Deploy the API candidate with `railway.toml` and verify API startup contains
   no `services.orchestrator.state_manager` compliance tick.
2. Wait until all predecessor API instances have terminated.
3. Deploy or start the standalone candidate with `railway-orchestrator.toml`.
4. During rolling overlap, verify one `OWNER` and any replacement instance only
   `STANDBY`; fence generations must increase on takeover and the prior
   generation must no longer update state, heartbeat, or kill switch.
5. Verify exactly one standalone heartbeat owner and no API-owned tick.
6. Verify API read endpoints reflect the standalone durable state.

Do not overlap an embedded predecessor API with a standalone writer. Rollback
must restore only one owner: never start an embedded API while standalone is
active. Database migration, execution activation, MT5, and broker actions are
outside this runbook.

Rollback must identify the exact predecessor deployment and preserve the same
lease/fence namespace. Stop the candidate writer or wait for its lease to expire
before accepting a predecessor takeover; never reset the generation counter or
manually overwrite the lease key.
