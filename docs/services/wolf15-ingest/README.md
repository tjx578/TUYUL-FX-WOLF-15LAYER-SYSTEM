# wolf15-ingest

**Role:** provider ingestion and normalized market-context publication.

- Manifest: [`../../../railway-ingestor.toml`](../../../railway-ingestor.toml)
- Start script: [`../../../deploy/railway/start_ingest.sh`](../../../deploy/railway/start_ingest.sh)
- Runtime module: [`../../../services/ingest/ingest_worker.py`](../../../services/ingest/ingest_worker.py)

The service starts its health probe, imports the ingest runtime on the event-loop
thread, connects configured providers, and publishes context through the existing
transport. It owns neither global compliance nor strategy analysis.

`CONTEXT_MODE` defaults to Redis. `PORT` is bound to `INGEST_HEALTH_PORT`.
Provider/data degradation must be reported separately from process liveness.
Fatal bootstrap diagnostics keep the probe observable but do not imply readiness.

Verify with ingest-state, producer-heartbeat, feed, and Redis-context tests.
