# Code Citations

All file references use repository-relative paths (e.g. `constitution/verdict_engine.py`),
not absolute local paths. If you see a full local path in this document, it is an error —
please submit a fix.

## Constitution (Layer-12)

| File | Purpose |
| ------ | --------- |
| `constitution/verdict_engine.py` | L12 verdict engine — sole decision authority |
| `constitution/violation_log.py` | Constitutional violation logger |
| `config/constitution.py` | Threshold constants for gates |

## Analysis (L1–L11)

| File | Purpose |
| ------ | --------- |
| `analysis/portfolio_monte_carlo.py` | L7 extension: portfolio-level correlated MC (advisory) |

## Execution

| File | Purpose |
| ------ | --------- |
| `execution/state_machine.py` | Trade state machine (executor only, no strategy logic) |

## Dashboard

| File | Purpose |
| ------ | --------- |
| `dashboard/app.py` | FastAPI backend — account/risk governor + ledger |
| `dashboard/metrics.py` | Prometheus metrics collector |
| `dashboard/ws_manager.py` | WebSocket manager with HTTP polling fallback |

## Risk

| File | Purpose |
| ------ | --------- |
| `risk/prop_firm.py` | Prop firm guard — rule authority for account limits |

## Journal (J1–J4)

| File | Purpose |
| ------ | --------- |
| `journal/` | Immutable decision audit trail (append-only) |

## Schemas

| File | Purpose |
| ------ | --------- |
| `schemas/l12_schema.json` | L12 verdict/signal contract |
| `schemas/alert_schema.json` | Trade reporting event schemas |

## Context

| File | Purpose |
| ------ | --------- |
| `context/live_context_bus.py` | Feed staleness + live context distribution |

## Config

| File | Purpose |
| ------ | --------- |
| `config/constitution.py` | Constitutional thresholds |

---

> **Rule**: Never commit absolute local paths (e.g. `C:\Users\...` or `/home/user/...`).
> All references must be repo-relative.
