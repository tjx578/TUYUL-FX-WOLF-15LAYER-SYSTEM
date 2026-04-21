# CADJPY D1 Audit Sheet

Gunakan sheet ini untuk audit end-to-end kasus CADJPY D1 stale dan pair HTF lain dengan pola serupa.

## Metadata

- Pair: `CADJPY`
- Timeframe: `D1`
- Audit UTC: `__________`
- Ingest deployment: `__________`
- Engine deployment: `__________`
- Redis endpoint / namespace: `__________`

## A. Provider / HTF Refresh

### A1. Fetch Evidence

- Ada log `Fetched 10 D1 bars for CADJPY`: `Ya / Tidak`
- Timestamp fetch: `__________`
- Ada log `Fetched 12 W1 bars for CADJPY`: `Ya / Tidak`

### A2. Write-Result Telemetry

- `fetched_count`: `__________`
- `written_count`: `__________`
- `dedup_skipped`: `__________`
- `provider_latest_ts`: `__________`
- `redis_latest_ts_before`: `__________`
- `redis_latest_ts_after`: `__________`
- `history_len_before`: `__________`
- `history_len_after`: `__________`
- `result`: `__________`

### A3. Keputusan Ingest

- Provider/fetch sehat: `Ya / Tidak`
- Write ke Redis terbukti: `Ya / Tidak`
- Root cause sisi ingest: `__________`

## B. Redis Inspection

### B1. Latest Hash

Key canonical:

`wolf15:candle:CADJPY:D1`

- `last_seen_ts`: `__________`
- candle latest timestamp/open_time/close_time: `__________`

### B2. History List

Key canonical:

`wolf15:candle_history:CADJPY:D1`

- history length: `__________`
- last 3 candle timestamps:
  - `__________`
  - `__________`
  - `__________`

### B3. Keputusan Redis

- latest hash fresh: `Ya / Tidak`
- history list fresh: `Ya / Tidak`
- latest hash sinkron dengan history tail: `Ya / Tidak`
- Root cause sisi Redis: `__________`

## C. Engine Hydration

### C1. Warmup Source

Cari log engine:

- `warmup loaded ... CADJPY:D1`
- `fallback: 1 bar from HASH`
- `PG recovery: CADJPY:D1`
- `skipping CADJPY:D1 — bus already has ...`

Isi:

- sumber warmup: `__________`
- jumlah bar yang dimuat: `__________`

### C2. Runtime Evidence

Cari log engine:

- `CADJPY DATA QUALITY degraded`
- `staleness_seconds`
- `freshness_state`
- `candle_age_by_tf`

Isi:

- `staleness_seconds`: `__________`
- `freshness_state`: `__________`
- `candle_age_by_tf.D1`: `__________`

### C3. Keputusan Engine

- Engine membaca data fresh: `Ya / Tidak`
- Engine tertahan di stale-preserved recovery: `Ya / Tidak`
- Root cause sisi engine: `__________`

## D. Final Root Cause

Pilih satu:

- `Provider / fetch failure`
- `HTF write-to-Redis failure`
- `Redis latest/history sync issue`
- `Engine hydration / read path issue`
- `Startup recovery stale dominance`
- `Symbol-specific mapping issue`
- `Systemic HTF refresh issue`
- `Belum cukup bukti`

### Evidence Utama

- `__________`
- `__________`
- `__________`

### Final Decision

- `P1-D = HOLD`
- `Execution untouched`
- Next fix target: `__________`

## Shortcut Rules

- Provider fresh + Redis stale => write path atau key sync problem.
- Redis fresh + engine stale => hydration/read problem.
- Redis kosong + engine punya 50 candles => startup recovery stale dominance.
- Hanya CADJPY yang kena => symbol-specific issue.
- Banyak pair D1 serupa => systemic HTF refresh issue.# CADJPY D1 Audit Sheet

Gunakan sheet ini untuk audit end-to-end kasus CADJPY D1 stale dan pair HTF lain dengan pola serupa.

## Metadata

- Pair: `CADJPY`
- Timeframe: `D1`
- Audit UTC: `__________`
- Ingest deployment: `__________`
- Engine deployment: `__________`
- Redis endpoint / namespace: `__________`

## A. Provider / HTF Refresh

### A1. Fetch Evidence

- Ada log `Fetched 10 D1 bars for CADJPY`: `Ya / Tidak`
- Timestamp fetch: `__________`
- Ada log `Fetched 12 W1 bars for CADJPY`: `Ya / Tidak`

### A2. Write-Result Telemetry

- `fetched_count`: `__________`
- `written_count`: `__________`
- `dedup_skipped`: `__________`
- `provider_latest_ts`: `__________`
- `redis_latest_ts_before`: `__________`
- `redis_latest_ts_after`: `__________`
- `history_len_before`: `__________`
- `history_len_after`: `__________`
- `result`: `__________`

### A3. Keputusan Ingest

- Provider/fetch sehat: `Ya / Tidak`
- Write ke Redis terbukti: `Ya / Tidak`
- Root cause sisi ingest: `__________`

## B. Redis Inspection

### B1. Latest Hash

Key canonical:

`wolf15:candle:CADJPY:D1`

- `last_seen_ts`: `__________`
- candle latest timestamp/open_time/close_time: `__________`

### B2. History List

Key canonical:

`wolf15:candle_history:CADJPY:D1`

- history length: `__________`
- last 3 candle timestamps:
  - `__________`
  - `__________`
  - `__________`

### B3. Keputusan Redis

- latest hash fresh: `Ya / Tidak`
- history list fresh: `Ya / Tidak`
- latest hash sinkron dengan history tail: `Ya / Tidak`
- Root cause sisi Redis: `__________`

## C. Engine Hydration

### C1. Warmup Source

Cari log engine:

- `warmup loaded ... CADJPY:D1`
- `fallback: 1 bar from HASH`
- `PG recovery: CADJPY:D1`
- `skipping CADJPY:D1 — bus already has ...`

Isi:

- sumber warmup: `__________`
- jumlah bar yang dimuat: `__________`

### C2. Runtime Evidence

Cari log engine:

- `CADJPY DATA QUALITY degraded`
- `staleness_seconds`
- `freshness_state`
- `candle_age_by_tf`

Isi:

- `staleness_seconds`: `__________`
- `freshness_state`: `__________`
- `candle_age_by_tf.D1`: `__________`

### C3. Keputusan Engine

- Engine membaca data fresh: `Ya / Tidak`
- Engine tertahan di stale-preserved recovery: `Ya / Tidak`
- Root cause sisi engine: `__________`

## D. Final Root Cause

Pilih satu:

- `Provider / fetch failure`
- `HTF write-to-Redis failure`
- `Redis latest/history sync issue`
- `Engine hydration / read path issue`
- `Startup recovery stale dominance`
- `Symbol-specific mapping issue`
- `Systemic HTF refresh issue`
- `Belum cukup bukti`

### Evidence Utama

- `__________`
- `__________`
- `__________`

### Final Decision

- `P1-D = HOLD`
- `Execution untouched`
- Next fix target: `__________`

## Shortcut Rules

- Provider fresh + Redis stale => write path atau key sync problem.
- Redis fresh + engine stale => hydration/read problem.
- Redis kosong + engine punya 50 candles => startup recovery stale dominance.
- Hanya CADJPY yang kena => symbol-specific issue.
- Banyak pair D1 serupa => systemic HTF refresh issue.
