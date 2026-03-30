# Architecture Status Map

**Purpose:** Single-page status index for onboarding engineers and auditors.
Each entry is classified by maturity tier so readers know what to trust, what to build, and what to ignore.

## Status Tiers

| Tier | Label | Meaning |
| ------ | ------- | --------- |
| **C** | Canonical | Production truth. Code, tests, and CI enforce it. |
| **U** | Current | Implemented and operational but not yet fully hardened or doc-locked. |
| **H** | Historical | Preserved for traceability. Not authoritative for current behavior. |
| **A** | Aspirational | Planned or partially scoped. Not yet in code. |

---

## 1. Core Architecture

| Document / Surface | Tier | Key file(s) | Notes |
| -------------------- | ------ | ------------- | ------- |
| System overview | C | `docs/architecture/system-overview.md` | Authority separation model |
| Data flow | C | `docs/architecture/data-flow.md`, `data-flow-final.md` | Ingest → Redis → engine → verdict → execution |
| Runtime topology | C | `docs/architecture/runtime-topology-current.md` | Service boundaries, concurrency model, 1 debt item remaining |
| Engine lineage zones | H | `docs/architecture/engine-lineage-zones.md` | Zone-based pipeline ancestry; current truth is runtime-topology |
| Topology (service map) | C | `docs/architecture/topology.md` | Provider → ingest → Redis → engine → API → EA |

## 2. Governance

| Document / Surface | Tier | Key file(s) | Notes |
| -------------------- | ------ | ------------- | ------- |
| Authority boundaries | C | `docs/architecture/authority-boundaries.md` | Who may observe / decide / execute |
| Config governance | C | `docs/architecture/config-governance.md` | Change → approval → audit trail |
| Config resolver | C | `docs/architecture/config-resolver.md` | Precedence rules for runtime config |
| Lock enforcement | C | `docs/architecture/lock-enforcement.md` | Constitutional threshold mutation prevention |
| Stale-data guardrails | C | `docs/architecture/stale-data-guardrails.md` | Freshness classification, anti-zombie |

## 3. Constitutional Pipeline

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| L12 verdict engine | C | `constitution/verdict_engine.py` | Sole decision authority |
| Pipeline DAG (8-phase) | C | `pipeline/wolf_constitutional_pipeline.py`, `docs/architecture/core/engine-dag-architecture.md` | Semi-parallel halt-safe DAG |
| Constitutional boundary CI | C | `.github/workflows/wolf-pipeline-ci.yml` Phase 2 | 6 grep rules enforced in CI |
| Boundary regression tests | C | `tests/test_pr003_boundary.py` | Shim deletion, canonical import, boundary scan |

## 4. Contracts

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Redis stream contracts | C | `contracts/redis_stream_contracts.py` | VerdictPayload, ExecutionIntent, WorkerResult, OrchestratorCommand |
| Execution queue contract | C | `contracts/execution_queue_contract.py` | Allocation → worker stream |
| WebSocket events | C | `contracts/websocket_events.py` | MarketEvent, SignalEvent, RiskEvent |
| Dashboard DTO | C | `contracts/dashboard_dto.py` | SignalView, RiskRecommendation |
| API response envelope | C | `contracts/api_response_schema.py` | Generic `ApiResponse[T]` |
| L12 JSON schema | C | `schemas/l12_schema.json` | Validated in CI Phase 3 |
| Alert JSON schema | C | `schemas/alert_schema.json` | Validated in CI Phase 3 |
| ACCOUNT_STATE contract | A | — | Redis key; Pydantic model not yet created |
| TRADE_RISK contract | A | — | Redis key; Pydantic model not yet created |
| Layer output template | C | `docs/architecture/contracts/wolf-15-layer-output-template-v7.4r∞.md` | Shape each layer must produce |
| L14 schema mapping | C | `docs/architecture/contracts/wolf-15-layer-output-to-l14-schema-mapping.md` | Layer → adaptive learning mapping |
| Canonical metrics | C | `docs/architecture/contracts/canonical-metrics.md` | Wolf discipline, TII formula |
| Event acceptance spec | C | `docs/architecture/contracts/operational-api-event-acceptance-spec.md` | API event validation |
| Outbox admin API | C | `docs/architecture/contracts/outbox-admin-api.md` | Replay / drain endpoints |

## 5. Risk

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Risk stack | C | `docs/architecture/risk-stack.md` | Market-quality → analytical → execution → prop-firm layers |
| Risk monitor | C | `docs/architecture/risk-monitor.md` | Feed freshness, drawdown, lock violations |
| Risk management summary | C | `docs/architecture/risk/risk-management-summary.md` | Prop-firm guardrails, circuit breakers |
| L6 capital firewall | C | `analysis/l6_risk.py` | Veto authority in risk chain |
| Prop-firm rule engine | C | `accounts/prop_rule_engine.py` | FTMO / prop compliance |

## 6. Execution

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Execution feedback loop | C | `docs/architecture/execution-feedback-loop.md` | Verdict → intent → broker → exposure |
| Service contracts | C | `docs/architecture/service-contracts.md` | Cross-service ownership, retry rules |
| Allocation service | U | `allocation/allocation_service.py` | Signal → execution worker routing |
| EA interface | C | `ea_interface/` | Blind executor only; CI-enforced |

## 7. Deployment & Infrastructure

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Railway deployment | C | `docs/architecture/deployment-railway.md` | Core services, probes, readiness gates |
| Deployment topology final | C | `docs/architecture/deployment-topology-final.md` | Full service map, observability endpoints |
| Deploy scripts | U | `deploy/railway/start_*.sh` | 11 role-scoped start scripts |
| Railway TOML configs | U | `railway-*.toml` | Service-level Railway config |
| Infrastructure baseline | C | `docs/architecture/infrastructure/deployment-baseline.md` | Architecture diagram |
| Redis deployment | C | `docs/architecture/infrastructure/redis-deployment.md` | Stream/key namespace conventions |
| Docker strategy | C | `docs/architecture/infrastructure/docker.md` | Multi-stage build |
| Docker Compose (legacy) | H | `docs/legacy/architecture-history/docker-compose-legacy.md` | Superseded by Railway |

## 8. Operations

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Go-live checklist | C | `docs/architecture/operations/go-live-checklist.md` | Vercel + Railway pre-launch |
| Go-live (prop firm) | C | `docs/architecture/operations/go-live-checklist-prop-firm.md` | Compliance-specific launch |
| Deploy order | C | `docs/architecture/operations/deploy-order-staging-prod.md` | Staging → production sequence |
| Forensic replay & RCA | C | `docs/architecture/operations/forensic-replay-rca.md` | Incident investigation |
| Observability (workers) | C | `docs/architecture/operations/observability-async-workers.md` | Async worker monitoring |

## 9. Dashboard

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Dashboard control surface | C | `docs/architecture/dashboard-control-surface.md` | Owner-operated; not public multi-user |
| API key rotation | C | `dashboard/api_key_manager.py` | HMAC + grace-period rotation |
| State manager (RWLock) | C | `dashboard/state_manager.py` | Write-preferring lock, torn-read prevention |
| Next.js frontend | U | `dashboard/nextjs/` | TypeScript, CI build-gated |

## 10. CI / Quality

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Wolf pipeline CI (authoritative) | C | `.github/workflows/wolf-pipeline-ci.yml` | 8-phase, governance verdict gate |
| CI (lightweight) | C | `.github/workflows/ci.yml` | Ruff, tests, dashboard, shim-guard, drift-guard |
| Docs hygiene | C | `.github/workflows/docs-hygiene.yml` | Reading-order, legacy quarantine, cross-refs |
| Perf guard | C | `.github/workflows/perf-guard.yml` | Import budget, slow-test enforcement, module size |
| Security scan | C | `.github/workflows/wolf-security-scan.yml` | Secret detection |

## 11. Migration Backlogs

| Backlog | Tier | Key file(s) | Scope |
| --------- | ------ | ------------- | ------- |
| P0 | C | `docs/architecture/migration-backlog-p0.md` | Stop-the-bleeding: ingest, heartbeat, freshness, readiness |
| P1 | C | `docs/architecture/migration-backlog-p1.md` | Contract hardening, legality flow, execution lifecycle |
| P2 | C | `docs/architecture/migration-backlog-p2.md` | Topology alignment, event/schema, observability |
| Repo migration plan | C | `docs/architecture/repo-migration-plan.md` | Repository layout restructuring |

## 12. Legacy / Historical

| Surface | Tier | Key file(s) | Notes |
| --------- | ------ | ------------- | ------- |
| Legacy quarantine | H | `docs/legacy/README.md` | Index of historical materials |
| Final system review | H | `docs/legacy/architecture-history/final-system-review.md` | v7.4r∞ snapshot |
| Unified architecture v2.1 | H | `docs/legacy/architecture-history/unified-architecture-v2.1.md` | Historical unified arch |
| Docker Compose legacy | H | `docs/legacy/architecture-history/docker-compose-legacy.md` | Pre-Railway deployment |

---

## Quick Reference: Aspirational (Not Yet Built)

| Item | Target zone | Dependency |
| ------ | ------------- | ------------ |
| `ACCOUNT_STATE` Pydantic contract | contracts/ | Dashboard risk zone |
| `TRADE_RISK` Pydantic contract | contracts/ | Execution/risk zone |
| Orchestrator compliance-before-downstream enforcement | orchestrator | Runtime topology debt item |

---

## Audit Companion

This status map is the human-readable companion to `docs/architecture/audit-manifest.json`.

- **audit-manifest.json** — machine-readable index with domain tags and last-updated timestamps
- **status-map.md** — tier-classified overview for onboarding and manual audit

When adding or retiring a document, update both files.
