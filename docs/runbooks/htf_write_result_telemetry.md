# HTF Write-Result Telemetry

## Tujuan

Membuktikan bahwa refresh HTF D1/W1 tidak berhenti pada status fetched, tetapi benar-benar:

- menulis ke Redis canonical keys,
- memajukan latest timestamp Redis bila provider lebih baru,
- dan memberi alasan yang jelas bila write tidak mengubah state.

Scope patch ini sengaja sempit: ingest observability only.

## Scope

- File utama: ingest/htf_refresh_scheduler.py
- Tidak mengubah authority, execution, L12, atau threshold freshness.

## Event

Nama event structured log:

`htf_refresh_write_result`

Emit per symbol/timeframe untuk D1 dan W1 setelah write attempt selesai.

## Field Minimum

```json
{
  "event": "htf_refresh_write_result",
  "symbol": "CADJPY",
  "timeframe": "D1",
  "fetched_count": 10,
  "written_count": 10,
  "dedup_skipped": 0,
  "provider_latest_ts": "2026-04-20T00:00:00+00:00",
  "redis_latest_ts_before": "2026-04-16T00:00:00+00:00",
  "redis_latest_ts_after": "2026-04-20T00:00:00+00:00",
  "redis_last_seen_before": 1776624000.0,
  "redis_last_seen_after": 1776969600.0,
  "history_len_before": 50,
  "history_len_after": 60,
  "latest_age_seconds_after": 126000.0,
  "redis_history_key": "wolf15:candle_history:CADJPY:D1",
  "redis_latest_key": "wolf15:candle:CADJPY:D1",
  "result": "latest_updated"
}
```

## Result Enum

- `latest_updated`
  Redis latest timestamp sesudah write lebih baru dari sebelum write.

- `same_latest_dedup_ok`
  Provider latest tidak lebih baru dari Redis latest; tidak ada indikasi write path rusak.

- `provider_older_ignored`
  Provider latest timestamp lebih tua dari Redis latest sebelum write, sehingga latest existing dipertahankan.

- `latest_update_failed`
  Provider latest lebih baru dari Redis latest sebelum write, tetapi latest sesudah write masih tertinggal.

- `write_not_proven`
  Fetch ada, tetapi latest Redis setelah write tidak bisa dibuktikan.

- `redis_write_error`
  RPUSH, LTRIM, PUBLISH, atau readback Redis gagal.

- `timestamp_parse_error`
  Timestamp provider atau Redis tidak dapat diparse.

## Severity Rules

- `info`
  - `latest_updated`
  - `same_latest_dedup_ok`
  - `provider_older_ignored`

- `warning`
  - `write_not_proven`

- `error`
  - `latest_update_failed`
  - `redis_write_error`
  - `timestamp_parse_error`

## Acceptance Criteria

Operator harus bisa menjawab dari log saja:

1. Apakah CADJPY D1 benar-benar menulis ke Redis?
2. Apakah latest Redis timestamp bergerak maju?
3. Apakah write nol terjadi karena duplicate normal atau karena bug?
4. Apakah provider lebih tua dari latest existing atau latest update justru gagal?
5. Apakah latest hash dan history list tetap sinkron?

## Test Minimum

- provider latest > redis latest before dan latest hash maju => `latest_updated`
- provider latest > redis latest before tapi latest hash tetap tertinggal => `latest_update_failed`
- provider latest < redis latest before => `provider_older_ignored`
- redis write exception => `redis_write_error`
- invalid timestamp => `timestamp_parse_error`

## Non-Goals

- Tidak menambah dedup HTF baru.
- Tidak mengubah behavior write path.
- Tidak mengubah governance, L2/L3, atau execution.# HTF Write-Result Telemetry

## Tujuan

Membuktikan bahwa refresh HTF D1/W1 tidak berhenti pada status fetched, tetapi benar-benar:

- menulis ke Redis canonical keys,
- memajukan latest timestamp Redis bila provider lebih baru,
- dan memberi alasan yang jelas bila write tidak mengubah state.

Scope patch ini sengaja sempit: ingest observability only.

## Scope

- File utama: ingest/htf_refresh_scheduler.py
- Tidak mengubah authority, execution, L12, atau threshold freshness.

## Event

Nama event structured log:

`htf_refresh_write_result`

Emit per symbol/timeframe untuk D1 dan W1 setelah write attempt selesai.

## Field Minimum

```json
{
  "event": "htf_refresh_write_result",
  "symbol": "CADJPY",
  "timeframe": "D1",
  "fetched_count": 10,
  "written_count": 10,
  "dedup_skipped": 0,
  "provider_latest_ts": "2026-04-20T00:00:00+00:00",
  "redis_latest_ts_before": "2026-04-16T00:00:00+00:00",
  "redis_latest_ts_after": "2026-04-20T00:00:00+00:00",
  "redis_last_seen_before": 1776624000.0,
  "redis_last_seen_after": 1776969600.0,
  "history_len_before": 50,
  "history_len_after": 60,
  "latest_age_seconds_after": 126000.0,
  "redis_history_key": "wolf15:candle_history:CADJPY:D1",
  "redis_latest_key": "wolf15:candle:CADJPY:D1",
  "result": "advanced_latest"
}
```

## Result Enum

- `advanced_latest`
  Redis latest timestamp sesudah write lebih baru dari sebelum write.

- `same_latest_dedup_ok`
  Provider latest tidak lebih baru dari Redis latest; tidak ada indikasi write path rusak.

- `provider_stale`
  Provider latest timestamp lebih tua atau sama dengan Redis latest sebelum write.

- `write_not_proven`
  Fetch ada, tetapi latest Redis setelah write tidak bisa dibuktikan.

- `redis_write_error`
  RPUSH, LTRIM, PUBLISH, atau readback Redis gagal.

- `timestamp_parse_error`
  Timestamp provider atau Redis tidak dapat diparse.

## Severity Rules

- `info`
  - `advanced_latest`
  - `same_latest_dedup_ok`
  - `provider_stale`

- `warning`
  - `write_not_proven`

- `error`
  - `redis_write_error`
  - `timestamp_parse_error`

## Acceptance Criteria

Operator harus bisa menjawab dari log saja:

1. Apakah CADJPY D1 benar-benar menulis ke Redis?
2. Apakah latest Redis timestamp bergerak maju?
3. Apakah write nol terjadi karena duplicate normal atau karena bug?
4. Apakah provider sendiri stale?
5. Apakah latest hash dan history list tetap sinkron?

## Test Minimum

- provider latest > redis latest before => `advanced_latest`
- provider latest <= redis latest before => `provider_stale`
- redis write exception => `redis_write_error`
- invalid timestamp => `timestamp_parse_error`

## Non-Goals

- Tidak menambah dedup HTF baru.
- Tidak mengubah behavior write path.
- Tidak mengubah governance, L2/L3, atau execution.
