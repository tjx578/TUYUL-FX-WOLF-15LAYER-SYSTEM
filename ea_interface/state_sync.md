# EA ↔️ Executor State Sync

The EA must keep its internal state aligned with the live engine so orders are never duplicated or left stale.

## Snapshot Shape

```json
{
  "state": "PENDING_ACTIVE | CANCELLED | FILLED | IDLE",
  "order": {
    "symbol": "XAUUSD",
    "direction": "EXECUTE_BUY | EXECUTE_SELL",
    "entry": 2420.1,
    "sl": 2412.5,
    "tp": 2432.0,
    "mode": "TP1_ONLY"
  },
  "reason": "M15_INVALIDATION",
  "timestamp": "2025-02-09T07:00:00Z"
}
```

## Sync Rules

1. The engine is the source of truth. EA only mirrors.
2. On startup, EA pulls the latest snapshot then streams updates.
3. If EA misses a message, it should re-request the full snapshot.
4. State transitions are **append-only**; EA must not send commands that conflict with `state`.
