# 🐺 TUYUL FX — UNIFIED ARCHITECTURE v2.1 → v2.2

## Reference Architecture / Constitutional Worldview

**Version**: 2.2 (Revised)
**Lineage**: v2.1 Unified → v2.2 Reference
**Authority**: Reference Architecture — NOT current-state master
**Last Updated**: 2026-04-15

> **⚠️ STATUS NOTICE**
>
> This document has been **downgraded from MASTER to Reference Architecture**.
> It remains valid for constitutional worldview, design principles, and zone
> boundary definitions. It is **not** the source of truth for:
>
> - **Runtime thresholds** → `config/constitution.yaml`, `config/v11.yaml`
> - **Current runtime topology** → `docs/architecture/runtime-topology-current.md`
> - **Dashboard authority** → `docs/architecture/dashboard-control-surface.md`
> - **Service entrypoints** → `services/api/main.py`, `services/engine/runner.py`
> - **Current deployment shape** → `docker-compose.yml`, `docs/architecture/deployment-classification.md`
> - **WS/output channels** → `api/ws_routes.py`
> - **Component inventory** → `docs/architecture/component-inventory-current.md`

---

## 1. Design Principles

| Principle | Rule |
| ----------- | ------ |
| Constitutional separation | `analysis/` ≠ `execution/` ≠ `dashboard/` — each zone has one role |
| Sole decision authority | **L12 is the ONLY module that may issue EXECUTE/HOLD/NO_TRADE** |
| Dumb executor | EA is a **ZERO-INTELLIGENCE** file-polling executor; it never evaluates market state |
| Owner-operated control surface | Dashboard is an **owner-operated control surface** for visibility, diagnostics, and transport orchestration; it is **NOT** constitutional verdict authority (see `docs/architecture/dashboard-control-surface.md`) |
| No bypass | Any module that overrides L12 output = **INVALID SYSTEM** |

---

## 2. System Flow Overview

```text
Finnhub WebSocket
  → SpikeFilter + DedupCache        (ZONE A: Ingest & Filter)
  → TickBuffer + CandleBuilder       (ZONE B: Buffer & Candle)
  → LiveContextBus + EventBus        (ZONE C: Context & Events)
  → analysis_loop()                  (ZONE D: Analysis Trigger)
  → Pipeline v8.0  L1→L15 + V11     (ZONE E: Constitutional Pipeline)
  → Output Fan-Out  7 channels       (ZONE F: Distribution)
  → ExecutionStateMachine            (ZONE G: Execution Path)
  → FileBasedMT5Bridge → EA → Broker (ZONE G continued)
```

---

## 3. Master Pipeline Diagram

```text
╔══════════════════════════════════════════════════════════════════════════════╗
║  ZONE A  DATA INGESTION                                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  FinnhubWebSocket  (ingest/finnhub_ws.py)                                    ║
║    leader election · exponential backoff · API key rotation                  ║
║        │                                                                     ║
║        ▼                                                                     ║
║  SpikeFilter  (analysis/tick_filter.py)                                      ║
║    per-symbol % threshold · staleness reset on outlier                       ║
║        │                          │ REJECTED                                 ║
║        ▼                          ▼                                          ║
║  DedupCache  (analysis/tick_filter.py)          DLQ (audit trail)            ║
║    TTL OrderedDict · thread-safe                                             ║
║        │                                                                     ║
║        ├── News/Calendar  (news/)                                            ║
║        │     economic calendar lock · news event suppression                 ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE B  TICK BUFFER & CANDLE CONSTRUCTION                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  TickBuffer  (analysis/candle_builder.py)                                    ║
║    10,000 tick max · non-destructive · 3 consumers:                          ║
║      candle_builder · VWAP · orderflow                                       ║
║        │                                                                     ║
║        ▼                                                                     ║
║  MultiTimeframeCandleBuilder  (ingest/candle_builder.py)                     ║
║    Tick → M15 → H1  chained aggregation                                      ║
║        │                                                                     ║
║        ▼                                                                     ║
║  CandleAccumulator  (analysis/candle_accumulator.py)                         ║
║    gap-aware · fills missing candles before delivery                         ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE C  LIVE CONTEXT + EVENT BUS                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  LiveContextBus  (context/live_context_bus.py)  singleton                    ║
║    _ticks · _candle_history (250 max/TF/symbol) · _macro_state               ║
║    CONTEXT_MODE=local → in-process dict                                      ║
║    CONTEXT_MODE=redis  → RedisContextBridge                                  ║
║        │                                                                     ║
║        ▼                                                                     ║
║  EventBus  (core/event_bus.py)  17+ event types  authority-gated             ║
║    Source authority matrix:                                                  ║
║      TICK_RECEIVED     → ingest                                              ║
║      CANDLE_CLOSED     → ingest                                              ║
║      VERDICT_ISSUED    → constitution                                        ║
║      ORDER_*           → execution                                           ║
║    PermissionError on unauthorized emit                                      ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │  CANDLE_CLOSED event
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE D  ANALYSIS LOOP                                                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  analysis_loop()  (startup/analysis_loop.py)                                 ║
║    Event-driven: wakes on CANDLE_CLOSED  (<2 s latency)                      ║
║    Fallback:      polling every 60 s (ANALYSIS_LOOP_INTERVAL_SEC)            ║
║    Per-symbol:    only re-analyzes symbol from event                         ║
║    Warmup gate:   H1≥20 · H4≥10 · D1≥5 (M15 excluded — arrives via WS)      ║
║    Candle seed:   Redis history OR Finnhub REST on startup                   ║
║                                                                              ║
║  NOTE: Runtime entrypoints are now service-oriented:                         ║
║    services/api/main.py        — dedicated API service (ASGI)                ║
║    services/engine/runner.py   — dedicated engine process (no HTTP)           ║
║    main.py remains as logical flow reference                                 ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE E  WOLF CONSTITUTIONAL PIPELINE v8.0  (15 Layers + V11)               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Phase 1 — Perception & Context  [halt-on-fail]                              ║
║    L1 Context  →  L2 MTA  →  L3 Technical (SMC/ICT/OB/FVG/BOS)              ║
║                                                                              ║
║  Phase 2 — Confluence & Psychology                                           ║
║    L4 Scoring (FTA)  →  L5 Psychology (Wolf 30-pt)                           ║
║                                                                              ║
║  Phase 2.5 — Engine Enrichment  (9 facades)                                  ║
║    CorrelationRisk · MonteCarlo · BayesianPosterior · FusionMomentum         ║
║    VWAPVolume · OrderFlowImbalance · MultiTFDivergence                       ║
║    HTFStructure · MacroVolatility                                            ║
║                                                                              ║
║  Phase 3 — Probability & Validation                                          ║
║    L7 Probability  →  L8 TII  →  L9 SMC                                     ║
║                                                                              ║
║  Phase 4 — Execution Prep  [L11 BEFORE L6]                                  ║
║    L11 RR  →  L6 Risk  →  L10 Position Sizing                                ║
║                                                                              ║
║  Phase 5 — L12 Constitutional Verdict  ★ SOLE AUTHORITY ★                   ║
║  ┌──────────────────────────────────────────────────────────────────────┐    ║
║  │  Build Synthesis  →  9-Gate Check  →  Verdict                        │    ║
║  │                                                                      │    ║
║  │  G1 integrity≥min    G2 TII≥min        G3 win_prob                   │    ║
║  │  G4 RR≥min           G5 position      G6 TF law                     │    ║
║  │  G7 market law       G8 PENDING_ONLY  G9 all layers present         │    ║
║  │                                                                      │    ║
║  │  ⚠ Thresholds are in config/constitution.yaml (not hardcoded here)   │    ║
║  │  Current runtime: tii≥0.72 integrity≥0.78 rr≥1.5 conf12≥0.62        │    ║
║  │                                                                      │    ║
║  │  Safety:  SignalDedup(SHA-256) · SignalExpiry                        │    ║
║  │           SignalThrottle(3/5 min) · ViolationLog                    │    ║
║  │                                                                      │    ║
║  │  Output:  EXECUTE_BUY | EXECUTE_SELL | HOLD | NO_TRADE              │    ║
║  └──────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  Phase 6 — L13 Governance  (Two-Pass)                                        ║
║    Pass 1: baseline reflective  →  Pass 2: real meta  →  refined             ║
║                                                                              ║
║  Phase 7 — L15 Sovereignty                                                   ║
║    Drift detection  →  verdict downgrade if drift > threshold                ║
║                                                                              ║
║  Phase 8.5 — V11 SNIPER FILTER  [Post-Pipeline Overlay]                     ║
║  ┌──────────────────────────────────────────────────────────────────────┐    ║
║  │  Decision Matrix:                                                    │    ║
║  │    L12=EXECUTE + V11=ALLOW  → ✅ TRADE                               │    ║
║  │    L12=EXECUTE + V11=BLOCK  → ❌ NO TRADE  (veto, downgrade HOLD)   │    ║
║  │    L12=HOLD / NO_TRADE      → ❌  (L12 authority preserved)         │    ║
║  │                                                                      │    ║
║  │  Layer 1 VETO  (9 binary — ANY trips block)                         │    ║
║  │    regime_confidence<min · transition_risk>max                      │    ║
║  │    discipline<min · eaf<min · cluster>max                           │    ║
║  │    correlation>max · emotion_delta>max                              │    ║
║  │    vol_state invalid · regime=SHOCK                                  │    ║
║  │                                                                      │    ║
║  │  Layer 2 SCORING  (7 weighted → composite≥min)                      │    ║
║  │    regime(0.20) · liq_sweep(0.15) · exhaustion(0.15)                │    ║
║  │    divergence(0.10) · mc_win(0.15) · posterior(0.15)                │    ║
║  │    cluster_inv(0.10)                                                 │    ║
║  │                                                                      │    ║
║  │  Layer 3 EXECUTION  (5 AND — all must pass)                         │    ║
║  │    MC≥min · posterior≥min · PF≥min                                  │    ║
║  │    vol_expansion≥min · composite≥min                                │    ║
║  │                                                                      │    ║
║  │  ⚠ All V11 thresholds are in config/v11.yaml                        │    ║
║  │  Current runtime values differ from original doc targets             │    ║
║  │                                                                      │    ║
║  │  V11 Sub-Engines:                                                    │    ║
║  │    ExhaustionDetector       engines/v11/exhaustion_detector.py       │    ║
║  │    ExhaustionDVGFusion      engines/v11/exhaustion_dvg_fusion.py     │    ║
║  │      45/55 weighted fusion                                           │    ║
║  │    LiquiditySweepScorer     engines/v11/liquidity_sweep_scorer.py    │    ║
║  │      5-factor quality model                                          │    ║
║  │    RegimeService            engines/v11/regime_ai/regime_service.py  │    ║
║  │      OnlineKMeans 4-cluster                                          │    ║
║  │    SniperOptimizer          engines/v11/portfolio/sniper_optimizer.py│    ║
║  │      Kelly + Markowitz                                               │    ║
║  │    EdgeValidator            engines/v11/validation/edge_validator.py │    ║
║  │      Binomial + Wilson CI                                            │    ║
║  │                                                                      │    ║
║  │  Governance: config/v11.yaml · master switch                        │    ║
║  │  Latency budget: 100 ms · L12 authority always preserved            │    ║
║  └──────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  Phase 8 — L14 JSON Export + Final Assembly                                  ║
║    PipelineResult(schema="v8.0", pair, synthesis, l12_verdict,               ║
║      v11, reflective, sovereignty, execution_map, latency_ms, errors)        ║
║                                                                              ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │  PipelineResult
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE F  OUTPUT DISTRIBUTION  (7-Channel Fan-Out)                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. Journal  J1–J4  (journal/)                                               ║
║       ContextJournal · DecisionJournal · ExecutionJournal                    ║
║       ReflectiveJournal · atomic file write · GPT bridge                     ║
║                                                                              ║
║  2. Redis State                                                              ║
║       wolf15:latest_tick:* · candle history · macro state                    ║
║                                                                              ║
║  3. Dashboard WebSocket  (9+ channels — see api/ws_routes.py)                ║
║       /ws · /ws/prices · /ws/trades · /ws/candles · /ws/risk                 ║
║       /ws/equity · /ws/verdict · /ws/signals · /ws/pipeline                  ║
║                                                                              ║
║  4. Telegram Alerts  (alerts/telegram_notifier.py)                           ║
║       L12 verdict · order events · violations                                ║
║                                                                              ║
║  5. Prometheus Metrics  (core/metrics.py)                                    ║
║       15+ gauges/counters: pipeline_latency · signal_total                   ║
║       warmup_blocked · (and more)                                            ║
║                                                                              ║
║  6. EA Bridge  (ea_interface/mt5_bridge.py)                                  ║
║       file-based JSON protocol · command JSON written by engine              ║
║                                                                              ║
║  7. OpenTelemetry  (core/tracing.py)                                         ║
║       per-layer spans · tick→verdict end-to-end trace                        ║
║                                                                              ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │  via EA Bridge
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE G  EXECUTION PATH                                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ExecutionStateMachine  (execution/state_machine.py)                         ║
║    IDLE → PENDING_ACTIVE → FILLED | CANCELLED                                ║
║        │                                                                     ║
║        ├── PendingEngine  (execution/pending_engine.py)                      ║
║        │     multi-mode: DRY / PAPER / LIVE · idempotent · J3 journal        ║
║        ├── CancelEngine  (execution/cancel_engine.py)                        ║
║        │     M15 candle invalidation trigger                                 ║
║        ├── ExpiryEngine                                                      ║
║        │     H1 count-based expiry                                           ║
║        └── ExecutionGuard                                                    ║
║              structural safety pre-check                                     ║
║        │                                                                     ║
║        ▼                                                                     ║
║  FileBasedMT5Bridge  (ea_interface/mt5_bridge.py)                            ║
║    writes command JSON → EA polls on disk → writes report JSON               ║
║        │                                                                     ║
║        ▼                                                                     ║
║  TuyulFX_Bridge_EA  (ea_interface/TuyulFX_Bridge_EA.mq5)                     ║
║    MQL5 · DUMB EXECUTOR · magic 151515 · 500 ms poll interval                ║
║        │                                                                     ║
║        ▼                                                                     ║
║                         BROKER                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════════════╗
║  ZONE H  DEPLOYMENT TOPOLOGY  (⚠ see deployment-classification.md)           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Docker Compose — HYBRID TRANSITIONAL TOPOLOGY:                              ║
║                                                                              ║
║  Monolith-compatible stack:                                                  ║
║    app              :8000   — main Wolf-15 engine (ASGI)                     ║
║    wolf-allocation  :9102   — allocation manager worker                      ║
║    wolf-execution   :9103   — execution worker                               ║
║    wolf-dashboard   :3000   — Next.js dashboard                              ║
║                                                                              ║
║  Per-service builds (service-oriented):                                      ║
║    wolf-api         :8000   — dedicated API (services/api/Dockerfile)        ║
║    wolf-engine              — dedicated engine (services/engine/Dockerfile)   ║
║    wolf-ingest              — dedicated ingest (services/ingest/Dockerfile)   ║
║    wolf-orchestrator        — orchestrator (services/orchestrator/Dockerfile) ║
║                                                                              ║
║  Infrastructure / Observability:                                             ║
║    redis 7          :6379   — cache + pubsub                                 ║
║    postgresql 16    :5432   — persistence                                    ║
║    prometheus       :9090   — metrics                                        ║
║    grafana          :3001   — dashboards                                     ║
║    tempo            :4317   — distributed tracing (OTLP)                     ║
║                                                                              ║
║  CONTEXT_MODE: local | redis                                                 ║
║                                                                              ║
║  Railway: 10+ toml configs (API, engine, ingest, orchestrator, workers...)   ║
║  Vercel: dashboard/nextjs/                                                   ║
║                                                                              ║
║  ⚠ This section is a snapshot. See docker-compose.yml and                    ║
║    docs/architecture/deployment-classification.md for current truth.          ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 4. Component Inventory

| Zone | Component | File Path | Key Features | Status |
| ------ | ----------- | ----------- | -------------- | -------- |
| A | FinnhubWebSocket | `ingest/finnhub_ws.py` | leader election, backoff, key rotation | ✅ |
| A | SpikeFilter | `analysis/tick_filter.py` | per-symbol % threshold, staleness reset | ✅ |
| A | DedupCache | `analysis/tick_filter.py` | TTL OrderedDict, thread-safe | ✅ |
| A | DLQ | `ingest/tick_dlq.py` | Redis Stream (maxlen 50k), async push, audit trail | ✅ |
| A | News/Calendar | `news/` | economic calendar, news lock | ✅ |
| B | TickBuffer | `analysis/tick_pipeline.py` (shim: `analysis/candle_builder.py`) | 10,000 max, generic consumer-id, non-destructive | ✅ |
| B | MultiTimeframeCandleBuilder | `ingest/candle_builder.py` | Tick→M15→H1 chained | ✅ |
| B | CandleAccumulator | embedded in `ingest/candle_builder.py` (private `_CandleAccumulator`) | gap-aware fill; stale-OHLC guard in LiveContextBus | ✅ |
| C | LiveContextBus | `context/live_context_bus.py` | singleton, local/redis dual mode | ✅ |
| C | RedisContextBridge | `context/live_context_bus.py` | activated by CONTEXT_MODE=redis | ✅ |
| C | EventBus | `core/event_bus.py` | 19 event types, authority-gated, PermissionError enforced | ✅ |
| D | analysis_loop | `startup/analysis_loop.py` | event-driven + 60 s fallback; service entrypoints in `services/` | ✅ |
| E | Pipeline v8.0 | `pipeline/` | L1–L15 orchestration | ✅ |
| E | L12 VerdictEngine | `constitution/verdict_engine.py` | 9-gate, signal dedup, throttle | ✅ |
| E | ExhaustionDetector | `engines/v11/exhaustion_detector.py` | signal exhaustion binary | ✅ |
| E | ExhaustionDVGFusion | `engines/v11/exhaustion_dvg_fusion.py` | 45/55 weighted fusion | ✅ |
| E | LiquiditySweepScorer | `engines/v11/liquidity_sweep_scorer.py` | 5-factor quality | ✅ |
| E | RegimeService | `engines/v11/regime_ai/regime_service.py` | OnlineKMeans 4-cluster | ✅ |
| E | SniperOptimizer | `engines/v11/portfolio/sniper_optimizer.py` | Kelly + Markowitz | ✅ |
| E | EdgeValidator | `engines/v11/validation/edge_validator.py` | Binomial + Wilson CI | ✅ |
| F | ContextJournal | `journal/` | J1 context snapshot | ✅ |
| F | DecisionJournal | `journal/` | J2 decision log (all verdicts) | ✅ |
| F | ExecutionJournal | `journal/` | J3 execution details | ✅ |
| F | ReflectiveJournal | `journal/` | J4 post-trade reflection | ✅ |
| F | TelegramNotifier | `alerts/telegram_notifier.py` | L12 verdict, order events | ✅ |
| F | Metrics | `core/metrics.py` | 15+ Prometheus gauges/counters | ✅ |
| F | Tracing | `core/tracing.py` | OpenTelemetry per-layer spans | ✅ |
| F | MT5Bridge (output) | `ea_interface/mt5_bridge.py` | file-based JSON command write | ✅ |
| G | ExecutionStateMachine | `execution/state_machine.py` | IDLE→PENDING→FILLED/CANCELLED | ✅ |
| G | PendingEngine | `execution/pending_engine.py` | DRY/PAPER/LIVE, idempotent | ✅ |
| G | CancelEngine | `execution/cancel_engine.py` | M15 invalidation | ✅ |
| G | ExpiryEngine | `execution/` | H1 count expiry | ✅ |
| G | ExecutionGuard | `execution/` | structural pre-check | ✅ |
| G | FileBasedMT5Bridge | `ea_interface/mt5_bridge.py` | file-poll JSON protocol | ✅ |
| G | TuyulFX_Bridge_EA | `ea_interface/TuyulFX_Bridge_EA.mq5` | MQL5 dumb executor, magic 151515 | ✅ |
| H | Docker Compose | `docker-compose.yml` | 13 services (hybrid transitional: monolith + per-service + infra) | ✅ |
| H | Railway config | `railway.toml` + 9 `railway-*.toml` | multi-service deploy (API, engine, ingest, orchestrator, workers) | ✅ |
| H | Vercel | `dashboard/nextjs/` | dashboard frontend deployment | ✅ |

---

## 5. v1 vs v2 Assessment

| Dimension | v1 | v2 | v2.1 (Unified) | Notes |
| ----------- | :--: | :--: | :--------------: | ------- |
| Class name accuracy | 6/10 | 10/10 | 10/10 | Source-verified |
| Component completeness | 7/10 | 9.5/10 | 9.5/10 | All runtime components |
| V11 coverage | 3/10 | 10/10 | 10/10 | Full 3-layer gate + 6 sub-engines |
| Data flow traceability | 7/10 | 9/10 | 9.5/10 | Every data point traced |
| Integration points | 5/10 | 9/10 | 9.5/10 | V11 Phase 8.5 documented |
| Output distribution | 6/10 | 9/10 | 9/10 | 7 channels |
| Deployment topology | 3/10 | 8/10 | 8.5/10 | Docker + Railway + Hostinger |
| Visual clarity | 9/10 | 7/10 | 8.5/10 | v1 compact style adopted |
| Maintainability | 5/10 | 9/10 | 9.5/10 | Living reference doc |
| **WEIGHTED AVERAGE** | **5.7/10** | **9.1/10** | **9.3/10** | |

### What was adopted from v1

- Compact ASCII labeling style (shorter, scannable box descriptions)
- Design principles section placed upfront
- Clean linear flow overview before the deep-dive diagram
- Grouped phase naming (Phase 1 through Phase 8)

### What was preserved from v2

- All source-verified class names and constructor signatures
- All file paths with line references where applicable
- V11 complete architecture: 3-layer gate + decision matrix + 6 sub-engines
- Full 7-channel output fan-out with channel names
- Complete EventBus authority matrix with source ownership
- Deployment topology covering Docker services, ports, and platforms
- Component inventory table

### What is NEW in v2.1

- Merged compact clarity with verified depth in a single document
- Cross-zone flow arrows in the ASCII diagram
- Assessment scoring table with a v2.1 column
- Design principles section (v1 strength, absent in v2)
- RUN_MODE + CONTEXT_MODE deployment matrix documented together

---

## 6. Constitutional Boundaries (Locked)

```text
analysis/      → BERPIKIR    — read-only market analysis; zero side effects
constitution/  → MEMUTUSKAN  — L12 is sole verdict authority; nothing overrides it
execution/     → MENJALANKAN — blind state machine; no strategy logic
ea_interface/  → MENGEKSEKUSI — zero intelligence; polls files, reports results
dashboard/     → MEMONITOR   — owner-operated control surface; NOT verdict authority
journal/       → MENCATAT    — append-only audit; no runtime influence
```

Any module that crosses these boundaries (e.g., execution computing direction,
dashboard issuing verdicts) renders the system constitutionally invalid.

---

## 7. Changelog

```text
v1.0 — Initial diagram (compact visual style, some naming inaccuracies)
v2.0 — Source-verified rewrite (complete inventory, verbose)
v2.1 — Unified architecture (best of both; was MASTER reference)
v2.2 — Revised to Reference Architecture status (2026-04-15)
       - Downgraded from MASTER to Reference Architecture / Constitutional Worldview
       - Dashboard: "read-only monitor" → "owner-operated control surface"
       - Zone D: main.py → startup/analysis_loop.py; service entrypoints added
       - Zone E: hardcoded thresholds → references to config/constitution.yaml
       - Zone F: 5 WS channels → 9+ channels (see api/ws_routes.py)
       - Zone H: 8 services → hybrid transitional topology (13 services)
       - V11: hardcoded thresholds → references to config/v11.yaml
       - Component inventory: corrected file paths (TickBuffer, CandleAccumulator, DLQ)
       - Canonical current-state docs split to docs/architecture/
```
