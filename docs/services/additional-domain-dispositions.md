# Additional package-domain dispositions

The ZIP proposal named seven domains beyond the seven core application-service
READMEs. Each is resolved below without creating services or copying proposal
files wholesale. A disposition describes repository documentation only; it does
not prove deployment.

| Domain | Disposition | Inventory basis | Canonical documentation |
| --- | --- | --- | --- |
| `wolf15-dashboard` | `EQUIVALENT_EXISTING_DOC` | Dashboard is a Vercel frontend; its Railway companion is the non-authoritative dashboard BFF (`railway-dashboard-bff.toml`, `deploy/railway/start_dashboard_bff.sh`). | `docs/architecture/dashboard-hybrid-topology.md`, `docs/architecture/dashboard-control-surface.md` |
| `wolf15-migrator` | `ADOPT` | `railway-migrator.toml` invokes one-shot `deploy/railway/start_migrator.sh`; it is not an application replica and has no runtime orchestration authority. | `docs/architecture/operations/deploy-order-staging-prod.md` plus this disposition |
| `postgresql` | `EQUIVALENT_EXISTING_DOC` | PostgreSQL supplies durable journal/audit/ledger/recovery authority. It is not the orchestrator ownership lock. | `docs/architecture/authority-boundaries.md`, `docs/architecture/orchestrator-state-authority-recovery.md` |
| `redis` | `ADOPT` | Redis supplies operational state/fanout plus the atomic lease and monotonic fence generation. | `docs/architecture/infrastructure/redis-deployment.md`, `docs/architecture/adr-redis-orchestrator-ownership-fencing.md` |
| `worker-backtest` | `EQUIVALENT_EXISTING_DOC` | `railway-worker-backtest.toml` runs `services.worker.nightly_backtest` as a `NEVER`-restart scheduled job. | manifest, module docstrings, and this inventory disposition |
| `worker-montecarlo` | `EQUIVALENT_EXISTING_DOC` | `railway-worker-montecarlo.toml` runs `services.worker.montecarlo_job` as a `NEVER`-restart scheduled job. | manifest, module docstrings, and this inventory disposition |
| `worker-regime` | `EQUIVALENT_EXISTING_DOC` | `railway-worker-regime.toml` runs `services.worker.regime_recalibration` as a `NEVER`-restart scheduled job. | manifest, module docstrings, and this inventory disposition |

## Authority boundaries

The migrator owns a bounded schema-transition invocation; it does not own normal
application startup or orchestration. A migration test-contract discrepancy is
classified and repaired as test/contract drift unless source evidence establishes
a production migration defect. No documentation change authorizes migration.

The three research workers are scheduled jobs, not always-on application
services. They do not own orchestration, compliance, strategy authority, risk
authority, command issuance, or broker execution. Their presence in an inventory
does not require enabling or deploying them.

Redis and PostgreSQL are infrastructure dependencies with different authority.
They must not be presented as interchangeable locks or as trading authorities.
