# Owner dashboard release profile

Use only the existing WOLF15-DASHBOARD-FRONTEND and wolf15-api services.
The root railway.toml is a legacy consolidated profile and must not be used
for this release: its start script forces embedded orchestrator activation.

On wolf15-api, select `/deploy/railway/owner-dashboard-api.json` as the config
file and pin each deployment request to the verified full commit SHA.
The profile runs `python -m api.owner_dashboard_release`, with no pre-deploy
commands or automatic restart loop. Its environment validator rejects enabled
or malformed execution flags and missing owner identity/signing configuration.
It then starts Gunicorn through start_api.sh with API-only role and a read-only
startup profile. That profile skips PostgreSQL startup initialization, the trade
outbox worker, WS relay, peer checker and candle aggregator. Ordinary API startup
retains its previous behavior when this profile is not selected.

This is a startup containment profile, not a claim that every API endpoint is
read-only. Existing machine consumers and broader API authorization remain a
separate boundary; owner tokens are still limited to viewer/read:dashboard.

Each API worker emits `WOLF15_OWNER_STARTUP_ATTESTATION` before accepting traffic.
The fixed JSON receipt contains its PID, the 14 disabled-flag checks, five
background-component states, and SHA-256 hashes of four release/startup files.
It never includes environment dumps, owner identifiers, verifiers or tokens.
Compare those hashes to canonical Git blobs from the pinned deployment commit
and bind the log to that deployment ID. This is a worker-emitted runtime receipt;
SSH inspection, whole-image attestation and database/broker state remain separate
evidence classes. An unexpected background component prevents startup.

Before deploying: preserve exact currently active deployment IDs for rollback,
verify the selected services and domains, validate effective disabled flags,
configure the owner through masked local input, and verify the provider's
effective config file/start command. Use a service-scoped deployment mechanism;
never accept an unrelated environment-wide staged patch. Do not merge main as
a deployment shortcut, because other services watch that branch.

Deploy API first. Verify its release identity and auth/containment; then deploy
the exact frontend commit with root dashboard/nextjs, its Dockerfile, port 8080,
and config file `/deploy/railway/owner-dashboard-frontend.json`,
viewer mode and canonical origin
https://wolf15-dashboard-frontend-production.up.railway.app. The server-only API
origin is https://wolf15-api-production.up.railway.app. Retain the BFF until real
login and direct GET projections work and no other consumer needs it.

Billing-related GitHub runner unavailability is waived temporarily by the user;
it is not a passing remote check. Linux/provider build, runtime acceptance,
source identity, live login, and rollback remain separate gates. Do not enable
trading, run migrations, or alter engine/broker services during this release.
