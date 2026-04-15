# Component Inventory — Current

**Status:** Canonical
**Last Verified:** 2026-04-15
**Source of Truth:** This file + actual code paths

## Purpose

Operational inventory of runtime components with source-verified file paths.
Supersedes the component table in the legacy unified-architecture-v2.1 doc.

## Zone A — Data Ingestion

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| FinnhubWebSocket | `ingest/finnhub_ws.py` | Leader election (Redis lock), exponential backoff, API key rotation via FinnhubKeyManager |
| SpikeFilter | `analysis/tick_filter.py` | Per-symbol % threshold, staleness override (300s), SpikeCheckResult |
| DedupCache | `analysis/tick_filter.py` | TTL OrderedDict (60s), hard cap 5000, batch eviction, thread-safe |
| TickDeadLetterQueue | `ingest/tick_dlq.py` | Redis Stream (maxlen 50k), async push, `peek()`/`drain()` generators |
| News/Calendar | `news/blocker_engine.py`, `news/news_engine.py`, `news/news_rules.py` | Per-impact lock windows (HIGH: ±30/15min), event suppression |

## Zone B — Tick Buffer & Candle Construction

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| TickBuffer | `analysis/tick_pipeline.py` (shim: `analysis/candle_builder.py`) | 10,000 max deque, generic consumer-id tracking, non-destructive |
| CandleBuilder | `ingest/candle_builder.py` | Tick and candle aggregation modes, period alignment, callback support |
| MultiTimeframeCandleBuilder | `ingest/candle_builder.py` | Arbitrary TF chain (default: Tick→M15→H1), `on_tick()` + `flush_all()` |
| _CandleAccumulator | `ingest/candle_builder.py` (private class) | Mutable accumulator, `reset()`/`update()`/`emit()` |
| Stale-OHLC guard | `context/live_context_bus.py` | 3-bar fingerprint check, silently skips duplicate candles |

## Zone C — Live Context & Event Bus

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| LiveContextBus | `context/live_context_bus.py` | Singleton, dual-layer (data + inference), CANDLE_MAX_BUFFER=250, thread-safe Lock |
| EventBus | `core/event_bus.py` | 19 event types, authority-gated `_ALLOWED_SOURCES`, async+sync emit, PermissionError on violation |

## Zone D — Analysis Loop

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| analysis_loop() | `startup/analysis_loop.py` | CANDLE_CLOSED event-driven + 60s fallback (configurable), RQI-selective sweep, 30s per-pair timeout |
| API service | `services/api/main.py` | Dedicated ASGI entrypoint via `api.app_factory.create_app()` |
| Engine runner | `services/engine/runner.py` | Dedicated engine process, DB preflight, health probe :8081 |

## Zone E — Constitutional Pipeline

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| WolfConstitutionalPipeline | `pipeline/wolf_constitutional_pipeline.py` | v8.0, 8 execution phases, semi-parallel always-forward DAG |
| L12 VerdictEngine | `constitution/verdict_engine.py` | Sole verdict authority, 9-gate check |
| 9-Gate Check | `pipeline/phases/gates.py` | Production gates, thresholds from `config/constitution.yaml` |
| SignalDeduplicator | `constitution/signal_dedup.py` | SHA-256 (16-char hex), 600s window, optional Redis backing |
| SignalThrottle | `constitution/signal_throttle.py` | 3 signals per 300s, thread-safe, EXECUTE→HOLD on throttle |

### V11 Sniper Filter

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| V11PipelineHook | `engines/v11/pipeline_hook.py` | Post-L12 overlay, veto-only, 100ms latency budget |
| ExhaustionDetector | `engines/v11/exhaustion_detector.py` | 3-factor detection (distance/impulse/wick), 20-bar lookback |
| ExhaustionDVGFusion | `engines/v11/exhaustion_dvg_fusion.py` | 45% exhaustion / 55% divergence weighted fusion |
| LiquiditySweepScorer | `engines/v11/liquidity_sweep_scorer.py` | 5-factor quality model (equal hi/lo, wick rejection, volume spike, failed close, multi-bar) |
| RegimeService | `engines/v11/regime_ai/regime_service.py` | Online K-Means 4-cluster (TRENDING/RANGING/EXPANSION/SHOCK), LR 0.1 |
| SniperOptimizer | `engines/v11/portfolio/sniper_optimizer.py` | Kelly criterion (0.5 dampening) + Markowitz (Ledoit-Wolf shrinkage) |
| EdgeValidator | `engines/v11/validation/edge_validator.py` | Binomial z-test + Wilson CI (0.95), min 30 trades, rolling 100-trade window |
| V11 Config | `config/v11.yaml` | Master switch, governance mode, all thresholds |

## Zone F — Output Distribution

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| ContextJournal (J1) | `journal/` | Market context snapshot at analysis time |
| DecisionJournal (J2) | `journal/` | Full decision record for every verdict |
| ExecutionJournal (J3) | `journal/` | Execution details (EXECUTE_* only) |
| ReflectiveJournal (J4) | `journal/` | Post-trade reflection |
| JournalWriter | `journal/journal_writer.py` | Immutable append-only, atomic file write (exclusive create mode) |
| GPT Bridge | `journal/journal_gpt_bridge.py` | Journal-to-GPT integration |
| TelegramNotifier | `alerts/telegram_notifier.py` | 12+ alert types: verdict, order, violation, stale feed, drawdown, kill switch, circuit breaker |
| Metrics | `core/metrics.py` | 20+ Prometheus gauges/counters/histograms, zero external dependencies |
| Tracing | `core/tracing.py` | OpenTelemetry per-layer spans, graceful degradation to NoOp |
| FileBasedMT5Bridge | `ea_interface/mt5_bridge.py` | File-based JSON protocol (commands→reports→archive) |

### WebSocket Channels (from `api/ws_routes.py`)

| Endpoint | Purpose | Update Interval |
| -------- | ------- | --------------- |
| `/ws` | General-purpose signal relay (Redis PubSub) | — |
| `/ws/prices` | Live tick-by-tick price stream | 100ms batch |
| `/ws/trades` | Trade status change events | 250ms |
| `/ws/candles` | Real-time candle aggregation (M1/M5/M15/H1) | 500ms |
| `/ws/risk` | Risk state (drawdown, circuit breaker) | 1.0s |
| `/ws/equity` | Equity curve with drawdown overlay | 2.0s |
| `/ws/verdict` | L12 verdict stream | 500ms fallback |
| `/ws/signals` | Frozen signal stream | 500ms fallback |
| `/ws/pipeline` | Pipeline panel stream | 500ms fallback |

All WebSocket endpoints require JWT token in query parameter.

## Zone G — Execution Path

| Component | File Path | Key Features |
| --------- | --------- | ------------ |
| StateMachineRegistry | `execution/state_machine.py` | Per-symbol FSM, IDLE→PENDING_ACTIVE→FILLED/CANCELLED, replay-safe, thread-safe |
| PendingEngine | `execution/pending_engine.py` | LIVE/PAPER/DRY modes, structural validation only, J3 journal integration |
| CancelEngine | `execution/cancel_engine.py` | M15 invalidation trigger, idempotent |
| ExpiryEngine | `execution/expiry_engine.py` | H1 bar count expiry (default 3 bars) |
| ExecutionGuard | `execution/execution_guard.py` | Multi-layer gating: kill switch, news lock, circuit breaker, prop compliance, feed freshness |
| FileBasedMT5Bridge | `ea_interface/mt5_bridge.py` | Write command JSON → EA polls → report JSON |
| TuyulFX_Bridge_EA | `ea_interface/TuyulFX_Bridge_EA.mq5` | MQL5, zero intelligence, magic 151515, 500ms poll |

## Zone H — Deployment

See `docs/architecture/deployment-classification.md` for the current-state
deployment topology, Docker Compose services, Railway configs, and service entrypoints.

## Threshold Source of Truth

Runtime thresholds are **not** documented here. See:

- **L12 9-gate thresholds** → `config/constitution.yaml`
- **V11 thresholds** → `config/v11.yaml`
- **Risk parameters** → `config/constitution.yaml` (L6, L10, L11 sections)
