# Outbox Admin API

Dokumen ini merangkum endpoint admin untuk inspeksi dan replay `trade_outbox`.

Base path: `/api/v1/outbox`

Header umum:

- `Authorization: Bearer <token>`

Catatan governance:

- Endpoint `POST` juga melewati write policy (`enforce_write_policy`).

## 1) Inspect Pending Outbox + Filter

Endpoint:

- `GET /api/v1/outbox/pending`

Query params:

- `limit` (opsional, default `100`, min `1`, max `500`)
- `status_filter` (opsional, `PENDING|PUBLISHED`, default `PENDING`)
- `trade_id` (opsional)
- `event_type` (opsional)

Contoh request:

```bash
curl -X GET "http://localhost:8000/api/v1/outbox/pending?status_filter=PENDING&trade_id=T-20260309-01&event_type=ORDER_PLACED&limit=50" \
  -H "Authorization: Bearer <token>"
```

Contoh response `200`:

```json
{
  "status": "PENDING",
  "trade_id": "T-20260309-01",
  "event_type": "ORDER_PLACED",
  "count": 1,
  "items": [
    {
      "outbox_id": "obx-17",
      "outbox_key": "T-20260309-01:ORDER_PLACED",
      "trade_id": "T-20260309-01",
      "event_type": "ORDER_PLACED",
      "topic": "trade_lifecycle",
      "status": "PENDING",
      "attempts": 2,
      "last_error": "timeout publish",
      "next_attempt_at": "2026-03-09T07:12:20.120000+00:00",
      "published_at": null,
      "created_at": "2026-03-09T07:11:02.310000+00:00",
      "updated_at": "2026-03-09T07:11:50.500000+00:00"
    }
  ]
}
```

## 2) Single Record Detail

Endpoint:

- `GET /api/v1/outbox/{outbox_id}`

Contoh request:

```bash
curl -X GET "http://localhost:8000/api/v1/outbox/obx-17" \
  -H "Authorization: Bearer <token>"
```

Contoh response `200`:

```json
{
  "outbox_id": "obx-17",
  "outbox_key": "T-20260309-01:ORDER_PLACED",
  "trade_id": "T-20260309-01",
  "event_type": "ORDER_PLACED",
  "topic": "trade_lifecycle",
  "status": "PENDING",
  "attempts": 2,
  "last_error": "timeout publish",
  "next_attempt_at": "2026-03-09T07:12:20.120000+00:00",
  "published_at": null,
  "created_at": "2026-03-09T07:11:02.310000+00:00",
  "updated_at": "2026-03-09T07:11:50.500000+00:00",
  "payload": {
    "trade": {
      "trade_id": "T-20260309-01",
      "status": "ORDER_PLACED"
    }
  }
}
```

Contoh response `404`:

```json
{
  "detail": "Outbox not found: obx-unknown"
}
```

## 3) Retry Batch (Mass Replay) + Safety Cap

Endpoint:

- `POST /api/v1/outbox/retry-batch`

Request body:

- `limit` (default `50`, max request `1000`)
- `status_filter` (`PENDING|PUBLISHED`, default `PENDING`)
- `trade_id` (opsional)
- `event_type` (opsional)

Safety cap:

- Server menerapkan hard cap `200` item per request (`RETRY_BATCH_SAFETY_CAP`).
- Jika `limit > 200`, response menandai `capped: true` dan `applied_limit: 200`.

Contoh request:

```bash
curl -X POST "http://localhost:8000/api/v1/outbox/retry-batch" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "limit": 500,
    "status_filter": "PENDING",
    "trade_id": "T-20260309-01",
    "event_type": "ORDER_PLACED"
  }'
```

Contoh response `200`:

```json
{
  "requested_limit": 500,
  "applied_limit": 200,
  "safety_cap": 200,
  "capped": true,
  "status_filter": "PENDING",
  "trade_id": "T-20260309-01",
  "event_type": "ORDER_PLACED",
  "count": 2,
  "replayed": 1,
  "failed": 1,
  "skipped": 0,
  "results": [
    {
      "outbox_id": "obx-17",
      "replayed": true,
      "status": "PUBLISHED"
    },
    {
      "outbox_id": "obx-19",
      "replayed": false,
      "status": "PENDING",
      "attempts": 3,
      "next_attempt_at": "2026-03-09T07:14:06.020000+00:00",
      "error": "publish timeout"
    }
  ]
}
```

## Error Response Umum

Contoh `503` saat PostgreSQL tidak tersedia:

```json
{
  "detail": "PostgreSQL unavailable"
}
```
