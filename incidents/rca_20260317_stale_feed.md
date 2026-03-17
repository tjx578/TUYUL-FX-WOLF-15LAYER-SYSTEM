# Incident RCA — Stale Feed Warnings

**Date:** 2026-03-17
**Severity:** Medium
**Status:** Resolved (deployment topology corrected)

---

## Summary

Engine service started successfully, but it was launched in `RUN_MODE=engine-only`, which explicitly skips all ingest services and only consumes previously recovered market data from Redis/PostgreSQL. Startup logs confirm candle history was seeded into `LiveContextBus`, but the recovered dataset was already about **31,374 seconds (~8.7 hours)** old across nearly all symbols. Because no live ingest producer was running in this container, and no fresh ticks/candles arrived after startup, the analysis loop continued operating on stale seed data only. This caused the data-quality layer to degrade nearly every symbol (`confidence_penalty=0.15`) and naturally led the dashboard to show stale/live-feed warnings. Therefore, the stale banner is not the root cause; the root cause is a **deployment/runtime topology issue**: the engine was running without an active realtime data producer refreshing Redis.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| T+0 | Engine container starts in `RUN_MODE=engine-only` |
| T+1 | `init_persistent_storage()` runs → "Redis appears empty; attempting recovery from PostgreSQL" |
| T+2 | Candle history seeded into `LiveContextBus` from PostgreSQL recovery (~8.7 h stale) |
| T+3 | No ingest container running → no Finnhub WebSocket producer active |
| T+60s | `wolf15:latest_tick:*` keys expire (TTL=60 s) → tick data gone from Redis |
| T+∞ | Analysis loop operates on stale seed data only → data-quality layer applies `confidence_penalty=0.15` to all symbols |
| T+∞ | Dashboard shows "Verdict data is stale — live feed not responding" banner |

---

## Root Cause

**Deployment/runtime topology misconfiguration.**

The engine service was started without a co-located or networked ingest service writing fresh ticks and candles to Redis. In `RUN_MODE=engine-only` the engine deliberately skips all ingest startup paths, so:

1. No Finnhub WebSocket connection was established.
2. No `RestPollFallback` was active to refresh candle data.
3. The seed data loaded from PostgreSQL at startup became progressively staler with each analysis loop cycle.
4. The 60-second TTL on `wolf15:latest_tick:*` keys caused all tick keys to expire, leaving the engine with zero live data.

The dashboard "stale feed" warning is a **correct symptom**, not a bug in monitoring or the analysis pipeline itself.

---

## Contributing Factors

| # | Factor | Description |
|---|---|---|
| 1 | `LATEST_TICK_TTL_SECONDS = 60` | Tick keys expire after 60 s with no incoming ticks. During a typical Finnhub rate-limit back-off (30–300 s) or brief network blip this causes all tick keys to vanish, leaving the engine with zero live data. A 1-hour TTL covers normal reconnection scenarios; outages beyond that fall back to PostgreSQL recovery on restart. |
| 2 | Destructive warmup seed | `_seed_redis_candle_history()` deletes existing candle lists before confirming new data is available, risking data loss on Finnhub rate-limit errors (403/429). |
| 3 | `RestPollFallback` not writing to Redis | REST poll fallback updates `LiveContextBus` in memory but did not reliably persist candles back to Redis, so a restarting engine container sees empty lists. |
| 4 | No deployment guard | Nothing prevented the engine from starting without an active ingest producer. |

---

## Resolution

### Immediate
- Deploy the ingest service alongside the engine service so a live Finnhub WebSocket producer refreshes Redis continuously.
- Verify `RUN_MODE` is set correctly per deployment topology (do not use `engine-only` unless a separate ingest service is confirmed running).

### Code Fixes Applied
- **Non-destructive candle seed:** `_seed_redis_candle_history()` now writes to a temporary Redis key and performs an atomic `RENAME`, preserving existing data if the new fetch fails.
- **Tick TTL extended:** `LATEST_TICK_TTL_SECONDS` raised from 60 s to 3,600 s (1 h) so stale-but-valid tick data remains available during typical reconnection windows (network blips, rate-limit back-off). Staleness is detected via the timestamp field inside the hash rather than key expiry, so consumers receive "stale but present" data instead of "key missing". Outages longer than 1 h are handled by the PostgreSQL recovery path on the next restart.
- **`RestPollFallback` Redis writes:** Constructor now accepts `redis_client` and persists REST-polled candles to Redis so that engine restarts see recent data.
- **Sentinel key robustness:** `init_persistent_storage()` now checks multiple sentinel keys (`wolf15:peak_equity`, `wolf15:drawdown:daily`, `wolf15:circuit_breaker:state`) before triggering PostgreSQL recovery, and the log level is downgraded from `WARNING` to `INFO` since recovery on fresh deploy is expected behaviour.

---

## Lessons Learned

1. **Topology must be validated at deploy time.** The engine should refuse to start (or emit a startup alert) when Redis contains no candle data and no ingest producer heartbeat is detected.
2. **Destructive cache operations are dangerous.** Any operation that deletes live data before confirming replacement data is available can cause cascading data loss under rate-limit or network errors.
3. **TTL-based staleness detection is fragile.** Key expiry should signal "connection lost" only; last-known data should remain accessible for downstream consumers to act on a "stale but available" state rather than a "missing" state.
4. **Stale dashboard banners are lagging indicators.** Root causes are upstream in data production, not in the dashboard or analysis pipeline.

---

## Action Items

| # | Owner | Action | Status |
|---|---|---|---|
| 1 | Platform / DevOps | Always deploy engine + ingest in the same Railway environment or linked services | ✅ Done |
| 2 | Backend | Non-destructive candle seed (atomic RENAME) | ✅ Done |
| 3 | Backend | Extend `LATEST_TICK_TTL_SECONDS` to 3,600 | ✅ Done |
| 4 | Backend | `RestPollFallback` must write to Redis | ✅ Done |
| 5 | Backend | Multi-sentinel key check + downgrade log level to INFO | ✅ Done |
| 6 | Platform | Add startup health check: abort engine if Redis candle lists empty AND no ingest heartbeat | 🔲 Planned |
