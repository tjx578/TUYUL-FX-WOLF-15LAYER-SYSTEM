# wolf15-pressure-outbox

**Role:** durable pressure dispatch plus explicitly enabled evidence, lifecycle,
and outcome consumers.

- Manifest: [`../../../railway-pressure-outbox.toml`](../../../railway-pressure-outbox.toml)
- Start script: [`../../../deploy/railway/start_pressure_outbox.sh`](../../../deploy/railway/start_pressure_outbox.sh)
- Preflight: [`../../../services/pressure_outbox/preflight.py`](../../../services/pressure_outbox/preflight.py)
- Runtime: [`../../../services/pressure_outbox/runner.py`](../../../services/pressure_outbox/runner.py)

Preflight runs before the worker. The service owns leases/delivery and only the
optional workers whose exact flags pass preflight. It does not own global
orchestration, risk authority, or order submission.

Database availability is required. Shutdown stops all enabled workers and closes
the shared PostgreSQL client. Verify with pressure-outbox preflight, repository,
delivery, and lifecycle/evidence worker tests.
