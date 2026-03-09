# News Engine (PR2/PR3 Overlay)

## Scope

Calendar/news is advisory-only and must not make execution decisions.
The engine provides:

- event ingestion from provider chain
- blocker advisory status for dashboard/risk monitoring
- source health telemetry
- event intensity heatmap for operator visibility

## Authority Boundaries

- Analysis and execution authority remain outside this module.
- News routes expose read-only advisory data, except explicit manual lock endpoints.
- Manual lock only governs risk gating and does not calculate market direction.

## Data Flow

1. `NewsService` requests events from provider chain (first provider with data wins).
2. Events are deduplicated and cached in Redis.
3. Optional Postgres upsert runs best-effort.
4. Dashboard queries calendar, blocker, and source health endpoints.

## Observability

- Source health records are stored per provider key.
- Health status is evaluated as `healthy`, `degraded`, `down`, `stale`, or `unknown`.
- Heatmap aggregates hourly impact load in UTC.
