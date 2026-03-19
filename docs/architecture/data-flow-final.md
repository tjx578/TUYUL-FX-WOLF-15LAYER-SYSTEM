---
title: TUYUL-FX Final Data Flow Architecture
status: official
version: v1
owner: TUYUL-FX
last_updated: 2026-03-19
tags:
  - architecture
  - data-flow
  - realtime
  - anti-stale
  - recovery
  - governance
---

**Status:** Official Architecture Reference
**Scope:** Realtime data flow, freshness governance, recovery safety, and anti-stale enforcement
**Applies to:** Ingest, Redis durability, engine runtime context, Wolf analysis pipeline, backend transports, dashboard consumers

---

## 1. Layer Overview

```text
┌───────────────────────────────────────────────────────────────┐
│              EXTERNAL MARKET / EVENT SOURCES                  │
│  Finnhub WS (ticks) │ Finnhub REST (candles) │ Calendar/News │
└──────────┬──────────────────────┬──────────────────┬─────────┘
           ▼                      ▼                  ▼
┌───────────────────────────────────────────────────────────────┐
│                   INGEST AUTHORITY LAYER                      │
│  FinnhubWebSocketFeed → Tick Validation → Candle Builder     │
│  REST Fallback Scheduler │ H1 Refresh │ News/Macro Ingest    │
│  Producer Heartbeat (wolf15:heartbeat:ingest)                │
└──────────┬────────────────────────────────────────────────────┘
           ▼ write-through
┌───────────────────────────────────────────────────────────────┐
│              REDIS DURABILITY + FANOUT LAYER                  │
│  HASH: latest_tick, latest_candle, heartbeats                │
│  LIST: candle_history per symbol:tf                          │
│  PUB/SUB: candle, tick, news, system:state                   │
│  RULES: no destructive overwrite, temp_key + atomic rename   │
└──────────┬────────────────────────────────────────────────────┘
           ▼ hydrate / subscribe
┌───────────────────────────────────────────────────────────────┐
│            ENGINE CONTEXT / RECOVERY LAYER                    │
│  RedisConsumer → LiveContextBus (candles, ticks, inference)  │
│  Recovery: Redis → PostgreSQL fallback → STALE_PRESERVED     │
└──────────┬────────────────────────────────────────────────────┘
           ▼ gate / assess
┌───────────────────────────────────────────────────────────────┐
│        FRESHNESS / QUALITY / GOVERNANCE LAYER                │
│  SystemStateManager │ Feed Freshness Guard │ DataQualityGate │
│  Producer Health Gate │ Kill-Switch / No-Trade Guard         │
│  → GovernanceVerdict: ALLOW / ALLOW_REDUCED / HOLD / BLOCK  │
└──────────┬────────────────────────────────────────────────────┘
           ▼ trigger
┌───────────────────────────────────────────────────────────────┐
│           WOLF ANALYSIS CONSTITUTIONAL DAG                    │
│  Warmup Gate → Phase 1–8 → L12 Verdict (SOLE AUTHORITY)     │
│  governance_penalty flows into L12 confidence/verdict         │
│  L13 Reflective → L15 Sovereignty → L14 Assembly            │
└──────────┬────────────────────────────────────────────────────┘
           ▼ publish
┌───────────────────────────────────────────────────────────────┐
│              OUTPUT / CONSUMER LAYER                          │
│  REST API │ WebSocket │ SSE │ PostgreSQL │ Telegram          │
└──────────┬────────────────────────────────────────────────────┘
           ▼ consume
┌───────────────────────────────────────────────────────────────┐
│                    DASHBOARD LAYER                            │
│  useLivePipeline: WS → SSE → REST polling                   │
│  Freshness: LIVE │ DEGRADED_BUT_REFRESHING │ STALE_PRESERVED│
│             NO_PRODUCER │ NO_TRANSPORT                       │
└───────────────────────────────────────────────────────────────┘
```

---

## 2. Purpose per Layer

### 2.1 External Market / Event Sources

Raw upstream inputs: Finnhub WebSocket ticks, Finnhub REST candles (M15/H1/H4/D1/W1/MN), calendar/news feeds. No decision authority.

### 2.2 Ingest Authority Layer

- **Files:** `ingest/finnhub_ws.py`, `ingest/candle_builder.py`, `ingest/rest_poll_fallback.py`, `ingest/h1_refresh_scheduler.py`, `ingest/calendar_news.py`, `ingest/finnhub_market_news.py`, `ingest/macro_monthly_scheduler.py`
- **Purpose:** Acquire, validate, normalize, and publish data. Reject invalid/spike payloads. Construct runtime candles from tick flow. Activate REST fallback when WS degrades. Write producer heartbeat.
- **Authority:** Data production only. No trading decisions.

### 2.3 Redis Durability + Fanout Layer

- **Key registry:** `state/redis_keys.py` — all keys centralized
- **Hashes:** `wolf15:latest_tick:{symbol}`, `wolf15:candle:{symbol}:{tf}`, `wolf15:heartbeat:*`
- **Lists:** `wolf15:candle_history:{symbol}:{tf}` (max 300)
- **Pub/Sub:** `candle:{symbol}:{tf}`, `tick_updates`, `news_updates`, `system:state`
- **Critical rules:** No destructive overwrite. Temp key + atomic rename for seeding. `latest_tick` stores `last_seen_ts`. Stale ≠ deleted.

### 2.4 Engine Context / Recovery Layer

- **Files:** `context/live_context_bus.py`, `context/redis_consumer.py`, `startup/candle_seeding.py`
- **Purpose:** Hydrate engine memory from Redis lists on startup. Consume realtime pub/sub. Maintain feed timestamps, warmup state.
- **Recovery chain:** Redis → PostgreSQL snapshot fallback → STALE_PRESERVED marking
- **Public API:** `get_feed_timestamp()`, `get_feed_timestamps()`, `get_all_feed_status()`, `warmup_state`, `check_warmup()`

### 2.5 Freshness / Quality / Governance Layer

- **Files:** `state/governance_gate.py`, `state/data_freshness.py`, `analysis/data_quality_gate.py`, `context/system_state.py`
- **Components:**
  - A. **SystemStateManager:** INITIALIZING → WARMING_UP → READY → DEGRADED → ERROR
  - B. **Feed Freshness Guard:** per-symbol `last_seen_ts` → fresh / stale_preserved / no_producer / no_transport
  - C. **DataQualityGate:** gap ratio, low tick count, staleness penalty (0–0.50)
  - D. **Producer Health Gate:** heartbeat presence + max age (60s default)
  - E. **Kill-Switch / No-Trade Guard:** hard threshold enforcement
- **Output:** `GovernanceVerdict` with action (ALLOW / ALLOW_REDUCED / HOLD / BLOCK) and `confidence_penalty`
- **Thresholds:**
  - Hard stale: 600s (force HOLD)
  - Heartbeat max age: 60s (producer dead)
  - DQ penalty hold: ≥ 0.40

### 2.6 Wolf Analysis Constitutional DAG

- **File:** `pipeline/wolf_constitutional_pipeline.py` (~1600 lines, v8.0)
- **Phases:**
  1. L1–L3 Perception (halt-safe)
  2. L4–L5 Confluence & Scoring
  3. L7–L9 Probability & Validation
  4. L11→L6→L10 Execution + Risk
  5. Build synthesis → 9-Gate Check → **L12 verdict** (SOLE AUTHORITY)
  6. Two-pass L13 governance (baseline → meta → refined)
  7. L15 sovereignty enforcement (drift detection + verdict downgrade)
  8. L14 JSON export + result assembly
- **Governance integration:** `governance_penalty` flows from governance gate into `generate_l12_verdict()`. Non-trivial penalties (≥ 0.10) downgrade confidence label; heavy penalties (≥ 0.30) downgrade EXECUTE → EXECUTE_REDUCED_RISK.
- **Absolute rule:** Layer 12 remains sole authority. Stale/degraded data reduces confidence or forces HOLD.

### 2.7 Output / Consumer Layer

- Backend APIs: `/api/live/snapshot`, `/api/system/state`, `/api/risk/*`, `/api/pipeline/*`
- Realtime transports: WebSocket, SSE (reserved), REST polling
- Persistent outputs: PostgreSQL journals, metrics, health endpoints, Telegram alerting

### 2.8 Dashboard Layer

- **Files:** `dashboard/nextjs/src/hooks/useLivePipeline.ts`, `dashboard/nextjs/src/store/useSystemStore.ts`
- **Transport ladder:** WS → SSE (reserved) → REST polling (10s interval)
- **UI freshness states:**
  - `LIVE` — producer alive, feed fresh, transport connected
  - `DEGRADED_BUT_REFRESHING` — governance allows reduced operation
  - `STALE_PRESERVED` — data exists but stale beyond threshold
  - `NO_PRODUCER` — producer heartbeat dead, no recovery source
  - `NO_TRANSPORT` — all transports failed
- **Store fields:** `freshnessState`, `producerHeartbeatAge`, `lastDataTimestamp`, `activeTransport`

---

## 3. Source of Truth per Component

| Component | Source of Truth | Notes |
| --------- | -------------- | ----- |
| Incoming ticks | Upstream providers | Finnhub WS/REST authoritative at ingestion |
| Validated ticks | Ingest Authority | After spike filter + schema validation |
| Operational state | Redis | `latest_tick`, `candle_history`, heartbeats |
| Durable recovery | PostgreSQL | `ohlc_candles` table, journal snapshots |
| Runtime analysis state | LiveContextBus | In-process only, hydrated from Redis/PG |
| System readiness | SystemStateManager + GovernanceGate | Feed timestamps + heartbeat age |
| Trade verdict | Layer 12 (VerdictEngine) | SOLE authority — no override allowed |
| Dashboard state | Backend API + transport | UI reflects backend-provided freshness |

---

## 4. Recovery Behavior

### 4.1 Ingest Recovery

- WebSocket reconnects with bounded backoff + jitter
- Leader election ensures single active producer
- REST fallback activates after WS failure + grace timeout (90s)
- H1/H4 scheduled refresh continues regardless of tick flow

### 4.2 Redis Recovery Safety

- Seeding uses `temp_key + atomic rename` (see `candle_history_temp()`)
- Existing valid history never destructively deleted before replacement confirmed
- `latest_tick` retains `last_seen_ts` — stale state remains observable

### 4.3 Engine Startup Hydration

1. Hydrate from Redis lists (`_seed_from_redis`)
2. If Redis empty after max retries → fallback to PostgreSQL (`_try_restore_from_postgres`)
3. If PostgreSQL recovery succeeds → data marked as recovered (STALE_PRESERVED)
4. Warmup not complete until required bars + minimum context present

### 4.4 Frontend Recovery

- Transport ladder: WS → SSE (reserved) → REST polling
- 30s grace period before WS → REST fallback
- Fallback preserves visibility into freshness, heartbeat age, transport mode
- Recovery probe every 60s to re-attempt WS

---

## 5. Enforcement / Hold Rules

### 5.1 Kill-Switch (BLOCK)

- Redis key `wolf15:system:kill_switch` or env `WOLF_KILL_SWITCH_ACTIVE`
- Immediate BLOCK — no analysis permitted

### 5.2 Warmup (HOLD)

- Required bars: `{"H1": 1, "H4": 5, "D1": 1, "W1": 1, "MN": 1}`
- Incomplete warmup → HOLD

### 5.3 Freshness (HOLD)

- Hard stale > 600s → HOLD
- No producer signal → HOLD (unless transport-only issue with alive producer)
- Stale preserved → ALLOW_REDUCED with penalty

### 5.4 Data Quality (HOLD)

- DQ penalty ≥ 0.40 → HOLD
- Penalty > 0 → ALLOW_REDUCED, penalty flows to L12

### 5.5 Governance Penalty → L12

- `governance_penalty` parameter in `generate_l12_verdict()`
- ≥ 0.10 → confidence label downgraded
- ≥ 0.30 → verdict downgraded to EXECUTE_REDUCED_RISK
- Advisory: modulates confidence, does not override constitutional gate logic

---

## 6. Closing Principle

TUYUL-FX must never treat data presence as equivalent to data legitimacy.

The system is operationally trustworthy only when:

- Producers are alive
- Freshness is within allowed thresholds
- Warmup is sufficient
- Recovery state is clearly classified
- Layer 12 is making decisions under valid governance constraints

Anything less must degrade gracefully, surface the truth clearly, and force HOLD where required.
