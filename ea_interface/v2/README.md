# TuyulFX EA v3 — Agent Manager Integration

## Overview

This directory (`ea_interface/v2/`) contains the **version 3** MQL5 Expert Advisor files that integrate with the Phase 2 Agent Manager backend (`/api/v1/agent-manager/*` and `/api/v1/agent-ingest/*`).

These files are **separate from** the legacy `ea_interface/TuyulFX_Bridge_EA.mq5` which uses the old file-based bridge protocol. Both can coexist simultaneously on different charts.

---

## Architecture

### EA Types

| EA | File | Class | Purpose |
| ---- | ------ | ------- | --------- |
| **PRIMARY** | `TuyulFX_Primary_EA.mq5` | PRIMARY | Full execution + reporting |
| **PORTFOLIO** | `TuyulFX_Portfolio_EA.mq5` | PORTFOLIO | Reporter-only, no execution |

### vs Legacy v1

| Feature | v1 (Bridge EA) | v2 (Agent Manager EA) |
| --------- | ---------------- | ---------------------- |
| Communication | File-based JSON | HTTP REST API |
| Registration | None | Agent Manager backend |
| Heartbeat | None | Every 30 s (configurable) |
| Config sync | None | Polls backend config |
| Risk guard | None (backend only) | Local + backend (defense in depth) |
| Safe mode | Manual | Auto (backend-controlled + local failsafe) |
| Portfolio reporting | None | Periodic snapshots |
| Audit trail | None | All events logged in backend |

---

## Include Files

| File | Purpose |
| ------ | --------- |
| `Include/TuyulFX_Common.mqh` | Constants, enums, utility functions |
| `Include/TuyulFX_Json.mqh` | JSON parser / builder (improved v2) |
| `Include/TuyulFX_Http.mqh` | HTTP client for Agent Manager API |
| `Include/TuyulFX_RiskGuard.mqh` | Client-side risk guard (defense-in-depth) |

---

## Backend API Endpoints Used

| Method | Endpoint | Purpose |
| -------- | ---------- | --------- |
| `POST` | `/api/v1/agent-ingest/heartbeat` | Send heartbeat |
| `POST` | `/api/v1/agent-ingest/status-change` | Send status change |
| `POST` | `/api/v1/agent-ingest/portfolio-snapshot` | Send account snapshot |
| `GET`  | `/api/v1/agent-manager/agents/{id}` | Fetch agent config |

---

## Setup

### 1. Create an Agent in Agent Manager

Use the Agent Manager UI or API to create a new agent:

```json
POST /api/v1/agent-manager/agents
{
  "agent_name": "My Primary EA",
  "ea_class": "PRIMARY",
  "ea_subtype": "BROKER",
  "execution_mode": "DEMO",
  "reporter_mode": "FULL"
}
```

### 2. Copy the Agent UUID

Note the `id` field from the response. This is your `AgentId`.

### 3. Copy EA Files to MetaTrader 5

Copy the contents of `ea_interface/v2/` to your MT5 data directory:
- `TuyulFX_Primary_EA.mq5` → `MQL5/Experts/TuyulFX/`
- `TuyulFX_Portfolio_EA.mq5` → `MQL5/Experts/TuyulFX/`
- `Include/TuyulFX_Common.mqh` → `MQL5/Include/TuyulFX/`
- `Include/TuyulFX_Http.mqh` → `MQL5/Include/TuyulFX/`
- `Include/TuyulFX_Json.mqh` → `MQL5/Include/TuyulFX/`
- `Include/TuyulFX_RiskGuard.mqh` → `MQL5/Include/TuyulFX/`

### 4. Allow WebRequest in MT5

Go to **Tools → Options → Expert Advisors** and add your backend URL to the allowed URLs list (e.g. `http://localhost:8000`).

### 5. Attach EA to Chart

Set the following input parameters:
- `AgentId` — UUID from step 2 (**required**)
- `ApiBaseUrl` — e.g. `http://your-backend.railway.app`
- `ApiKey` — your JWT or API key

---

## Input Parameters

### TuyulFX_Primary_EA.mq5

| Parameter | Default | Description |
| ----------- | --------- | ------------- |
| `AgentId` | *(empty)* | Agent Manager UUID — **REQUIRED** |
| `ApiBaseUrl` | `http://localhost:8000` | Backend API URL |
| `ApiKey` | *(empty)* | Bearer token for authentication |
| `EAClass` | `PRIMARY` | EA class (mirrors backend enum) |
| `EASubtype` | `BROKER` | EA subtype (BROKER/PROP_FIRM/EDUMB) |
| `ExecutionMode` | `LIVE` | LIVE / DEMO / SHADOW |
| `MagicNumber` | `151515` | Magic number for all orders |
| `MaxSlippagePoints` | `20` | Max slippage in points |
| `HeartbeatIntervalSec` | `30` | Heartbeat frequency |
| `ConfigPollIntervalSec` | `60` | Config refresh frequency |
| `SnapshotIntervalSec` | `300` | Portfolio snapshot frequency |
| `MaxDailyDDPercent` | `4.0` | Local daily drawdown limit (%) |
| `MaxTotalDDPercent` | `8.0` | Local total drawdown limit (%) |
| `MaxConcurrentTrades` | `3` | Max open positions |
| `MaxLotSize` | `1.0` | Max lot size per trade |
| `MaxSpreadPips` | `3.0` | Max spread before blocking trade |
| `BridgeDir` | `C:\TuyulFX\bridge` | Legacy bridge directory |
| `UseLegacyBridge` | `false` | Poll legacy file-based commands |
| `UseHttpBridge` | `true` | Use HTTP-based protocol |

### TuyulFX_Portfolio_EA.mq5

| Parameter | Default | Description |
| ----------- | --------- | ------------- |
| `AgentId` | *(empty)* | Agent Manager UUID — **REQUIRED** |
| `ApiBaseUrl` | `http://localhost:8000` | Backend API URL |
| `ApiKey` | *(empty)* | Bearer token for authentication |
| `EASubtype` | `STANDARD_REPORTER` | STANDARD_REPORTER or BALANCE_ONLY |
| `ReporterMode` | `FULL` | FULL / BALANCE_ONLY / DISABLED |
| `HeartbeatIntervalSec` | `60` | Heartbeat frequency |
| `SnapshotIntervalSec` | `60` | Snapshot frequency |
| `ConfigPollIntervalSec` | `120` | Config refresh frequency |

---

## Safety Features

### Primary EA

- **Auto safe-mode** if backend is unreachable for 5 minutes
- **Local risk guard** checks before every trade (defense-in-depth):
  - Daily drawdown limit
  - Total drawdown vs equity high-water mark
  - Max concurrent open positions
  - Max lot size
  - Max spread
  - Margin availability
- **Consecutive failure detection**: WARNING status sent after 3 consecutive execution failures
- **Daily drawdown auto-quarantine**: QUARANTINED status sent if local DD limit is breached
- **New day reset**: Daily counters reset at day rollover
- **Shadow mode**: `ExecutionMode=SHADOW` logs signals without executing

### Portfolio EA

- **Disabled state**: Stops reporting if backend sets `safe_mode=true` or `ReporterMode=DISABLED`
- **Balance-only mode**: Sends minimal snapshot (balance + equity only) when `ReporterMode=BALANCE_ONLY`

---

## Migration from v1

The Primary EA supports backwards-compatible operation with v1:

1. Set `UseLegacyBridge=true` on the Primary EA to continue polling file-based commands from `BridgeDir\commands\`
2. Set `UseHttpBridge=true` (default) to also send HTTP heartbeats/snapshots/events
3. Both v1 (`TuyulFX_Bridge_EA.mq5`) and v2 (`TuyulFX_Primary_EA.mq5`) can run simultaneously on different charts
4. Legacy file-based reports are still written to `BridgeDir\reports\` when `UseLegacyBridge=true`

---

## Naming Conventions (MQL5)

- `g_` prefix — global variables
- `m_` prefix — class member variables
- `SCREAMING_SNAKE` — constants and `#define` macros
- `CTuyulXxx` — class names
- All functions have `//+---...---+//` style comment blocks

---

## Version History

| Version | File | Description |
| --------- | ------ | ------------- |
| 2.00 | `ea_interface/TuyulFX_Bridge_EA.mq5` | Legacy file-based bridge executor |
| 3.00 | `ea_interface/v2/TuyulFX_Primary_EA.mq5` | HTTP-based Primary EA + Agent Manager |
| 3.00 | `ea_interface/v2/TuyulFX_Portfolio_EA.mq5` | HTTP-based Portfolio reporter EA |
