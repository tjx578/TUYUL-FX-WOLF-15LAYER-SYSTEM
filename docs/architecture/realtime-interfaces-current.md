# Realtime Interfaces — Current

**Status:** Canonical
**Last Verified:** 2026-04-15
**Source of Truth:** `api/ws_routes.py`

## Purpose

Defines the current real-time interface inventory.
This document is the canonical list of WebSocket and streaming endpoints.

## WebSocket Endpoints

All endpoints require JWT or API key as `?token=` query parameter.
Connections without valid token are closed with code 4401.

### Core Market Data

| Endpoint | Purpose | Update Model | Interval |
| -------- | ------- | ----------- | -------- |
| `/ws/prices` | Live tick-by-tick price stream | Event-driven + fallback | 100ms batch |
| `/ws/candles` | Real-time candle aggregation (M1/M5/M15/H1) | Polling | 500ms |

### Trade & Execution

| Endpoint | Purpose | Update Model | Interval |
| -------- | ------- | ----------- | -------- |
| `/ws/trades` | Trade status change events | Event-driven diff + fallback | 250ms |
| `/ws/signals` | Frozen signal stream | Event-driven (PubSub) + fallback | 50ms event / 500ms fallback |

### Constitutional Pipeline

| Endpoint | Purpose | Update Model | Interval |
| -------- | ------- | ----------- | -------- |
| `/ws/verdict` | L12 verdict stream | Event-driven (PubSub) + fallback | 50ms event / 500ms fallback |
| `/ws/pipeline` | Pipeline panel stream (gate results, phase status) | Event-driven (PubSub) + fallback | 50ms event / 500ms fallback |

### Risk & Account

| Endpoint | Purpose | Update Model | Interval |
| -------- | ------- | ----------- | -------- |
| `/ws/risk` | Risk state (drawdown, circuit breaker, kill switch) | Polling | 1.0s |
| `/ws/equity` | Equity curve with drawdown overlay | Polling | 2.0s |

### Composite & Diagnostics

| Endpoint | Purpose | Update Model | Interval |
| -------- | ------- | ----------- | -------- |
| `/ws` | General-purpose signal relay (Redis PubSub) | Event-driven | — |
| `/ws/live` | Unified live feed (signals + accounts + trades) | Polling | 1.0s |
| `/ws/alerts` | Event-driven alert stream (risk events, trade events) | Event-driven (PubSub) | — |
| `/ws/trq` | TRQ pre-move alert stream (Zone A micro-wave) | Polling | 2.0s |

Total: 12 WebSocket endpoints

## REST Streaming / Polling Endpoints

| Endpoint | Purpose |
| -------- | ------- |
| `GET /api/v1/trq/{symbol}/r3d` | TRQ R3D history (Zone A micro-wave) |

## Connection Infrastructure

| Feature | Value |
| ------- | ----- |
| Server-side ping | Every 15s (configurable via `WS_PING_INTERVAL`) |
| Dead connection detection | Ping/pong timeout |
| Message envelope | Versioned event envelope (v1.0): `event_version`, `event_id`, `event_type`, `server_ts`, `trace_id`, `payload` |
| Reconnect support | Ring-buffer per manager for replay on reconnect |
| Auth rejection code | 4401 |

## Update Interval Constants

Defined in `api/ws_routes.py`:

```text
TICK_BATCH_INTERVAL      = 0.1   # 100ms
TRADE_CHECK_INTERVAL     = 0.25  # 250ms
CANDLE_UPDATE_INTERVAL   = 0.5   # 500ms
RISK_STATE_INTERVAL      = 1.0   # 1s
EQUITY_PUSH_INTERVAL     = 2.0   # 2s
VERDICT_FALLBACK_INTERVAL = 0.5  # 500ms
WS_PING_INTERVAL         = 15    # 15s (env configurable)
```

## Authority Boundary

All WebSocket endpoints are **read-only consumers** of system state.
They do not:

- produce verdicts
- modify risk state
- issue execution commands
- bypass constitutional boundaries

They are part of Zone F (Governed Distribution) in the architectural zone model.
