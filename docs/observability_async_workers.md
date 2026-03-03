# Observability + Async Worker Pattern

## What is added

1. **Prometheus + Grafana stack** via [docker-compose.yml](../docker-compose.yml)
2. **Async allocation worker** in [allocation/async_worker.py](../allocation/async_worker.py)
3. **Async execution worker** in [execution/async_worker.py](../execution/async_worker.py)
4. Prometheus scrape config in [monitoring/prometheus.yml](../monitoring/prometheus.yml)
5. Grafana provisioning and starter dashboard in [monitoring/grafana](../monitoring/grafana)

## Runtime ports

- Prometheus: `9090`
- Grafana: `3000`
- Allocation worker metrics: `9102`
- Execution worker metrics: `9103`

## Worker run commands

- Allocation worker: `python -m allocation.async_worker`
- Execution worker: `python -m execution.async_worker`

## Redis streams

- Allocation input stream: `allocation:request`
- Execution queue stream: `execution:queue`
- Allocation group: `alloc-group`
- Execution group: `exec-group`

## Expected message shape

### `allocation:request`

```json
{
  "request_id": "uuid-optional",
  "signal_id": "l12-signal-id",
  "account_ids": "[\"A1\",\"A2\"]",
  "risk_percent": "1.0"
}
```

### `execution:queue`

```json
{
  "request_id": "uuid",
  "signal_id": "signal-id",
  "account_id": "A1",
  "symbol": "EURUSD",
  "order_type": "BUY_LIMIT",
  "entry_price": "1.08123",
  "stop_loss": "1.07900",
  "take_profit_1": "1.08500",
  "lot_size": "0.10"
}
```

## Main metrics

- `wolf_allocation_latency_seconds`
- `wolf_alloc_success_total{account_id}`
- `wolf_alloc_reject_total{account_id,reason}`
- `wolf_execution_latency_seconds`
- `wolf_orders_total`
- `wolf_orders_failed_total`
- `wolf_redis_stream_lag{stream,group}`
- `wolf_process_memory_bytes{service}`
