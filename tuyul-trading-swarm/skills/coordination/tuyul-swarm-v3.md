---
name: "tuyul-swarm-v3"
description: "Multi-agent swarm coordination untuk TUYUL Trading Swarm — topologi hierarchical-veto-mesh dengan 24/5 shift rotation."
version: "3.0.0"
concept: "tuyul-exception-v3"
topology: hierarchical-veto-mesh
---

# TUYUL Swarm Coordination v3

## Topologi: Hierarchical Veto Mesh

`
                     [Orchestrator]
                           │
         ┌────────────────┬┴──────────────────┐
         │                │                   │
  [Pre-Qual Layer]  [Analysis Layer]   [Control Layer]
  ┌─────────────┐  ┌─────────────┐    ┌─────────────┐
  │ Scanner     │  │ Technical   │    │ Psychology  │
  │ MktCond     │  │ SmartMoney  │    │ Execution   │
  │ NewsRisk    │  │ RiskReward  │    │             │
  └─────────────┘  └─────────────┘    └─────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
       [Review Layer]           [Memory Layer]
       ┌─────────────┐          ┌─────────────┐
       │ Journal     │          │ MemHandoff  │
       │ Audit       │          │             │
       └─────────────┘          └─────────────┘
``

## Shift Rotation 24/5

| Shift       | UTC       | Active Agents                          |
|-------------|-----------|----------------------------------------|
| MONITORING  | 00-06     | Scanner, NewsRisk, MarketCondition     |
| ANALYSIS    | 06-12     | Technical, SmartMoney, RiskReward      |
| CONTROL     | 12-18     | Orchestrator, Psychology, Execution    |
| REVIEW      | 18-24     | Journal, Audit, MemoryHandoff          |

## Handoff Protocol

Setiap pergantian shift WAJIB menghasilkan handoff summary berisi:

- Active watchlist
- Open trades
- Psychology warnings
- Pending confirmations
- Upcoming events
- Rule breaches
- Audit flags

## Memory Namespaces

```text
tuyul:memory:session_bias:<instrument>:<session>
tuyul:memory:active_watchlist
tuyul:memory:rejected_reasons:<instrument>
tuyul:memory:psychology_warnings
tuyul:memory:audit_flags
tuyul:memory:handoff:<shift_id>
tuyul:memory:decisions:<date>
tuyul:memory:open_trades
tuyul:memory:upcoming_events
```
