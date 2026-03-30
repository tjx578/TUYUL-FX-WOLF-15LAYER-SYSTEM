# 🐺 TUYUL Trading Swarm v3.0

**Production-grade multi-agent AI trading decision system — Tuyul Exception v.3**

> *"Trade BETTER, not MORE. One valid disqualifier = REJECT. No exceptions."*

---

## Arsitektur

```
                    [Orchestrator Agent #1]
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
   PRE-QUAL LAYER    ANALYSIS LAYER     CONTROL LAYER
   ┌──────────────┐  ┌─────────────┐  ┌──────────────┐
   │ Scanner  #2  │  │ Technical#3 │  │ Psychology#8 │
   │ MktCond  #6  │  │ SmartMny #4 │  │ Execution #9 │
   │ NewsRisk #7  │  │ RiskRwd  #5 │  │              │
   └──────────────┘  └─────────────┘  └──────────────┘
                            │
               ┌────────────┴────────────┐
         REVIEW LAYER             MEMORY LAYER
         ┌─────────────┐          ┌─────────────┐
         │ Journal #10 │          │ Handoff #12 │
         │ Audit   #11 │          │             │
         └─────────────┘          └─────────────┘
```

## 12 Agent Spesialis

| # | Agent | Domain | Role |
|---|-------|--------|------|
| 1 | Trading Orchestrator | Coordination | Central coordinator |
| 2 | Market Scanner | Scanning | Pre-filter & noise removal |
| 3 | Technical Structure | Technical | TWMS 12-point checklist (min 11/12) |
| 4 | Smart Money | Technical | Institutional footprint (min 80%) |
| 5 | Risk-Reward | Risk | RR validation (min 1:2.0) |
| 6 | Market Condition | Environment | Trend/chop/range detection |
| 7 | News & Event Risk | Environment | Calendar risk gating |
| 8 | Psychology & Discipline | Psychology | HALT authority — absolute override |
| 9 | Trade Execution | Execution | Pre-flight & packet preparation |
| 10 | Journal & Review | Review | Decision logging & daily reports |
| 11 | Audit & Governance | Governance | Integrity check & breach detection |
| 12 | Memory & Handoff | Infrastructure | Shift continuity & memory fabric |

## Shift Rotation 24/5

| Shift | UTC | Agents Aktif |
|-------|-----|--------------|
| MONITORING | 00:00-06:00 | Scanner, NewsRisk, MarketCondition |
| ANALYSIS | 06:00-12:00 | Technical, SmartMoney, RiskReward |
| CONTROL | 12:00-18:00 | Orchestrator, Psychology, Execution |
| REVIEW | 18:00-24:00 | Journal, Audit, MemoryHandoff |

## Quick Start

```bash
# 1. Setup
cp .env.example .env
# Edit .env — minimal: DASHBOARD_JWT_SECRET, REDIS_URL

# 2. Docker (recommended)
docker-compose up -d

# 3. Manual
pip install -e ".[dev]"
python main.py

# 4. Dashboard
open http://localhost:8000/dashboard

# 5. API Docs
open http://localhost:8000/api/docs
```

## API Endpoints

```
POST /api/v1/decisions/evaluate   — Submit trade candidate
GET  /api/v1/decisions/today      — Decision history hari ini
GET  /api/v1/decisions/watchlist  — Active watchlist
POST /api/v1/decisions/handoff/produce — Produksi shift handoff

GET  /api/v1/agents/status        — Status semua 12 agent
GET  /api/v1/agents/shift         — Shift aktif saat ini

GET  /api/v1/memory/context       — Full memory fabric
GET  /api/v1/memory/open-trades   — Open trades
GET  /api/v1/memory/psychology-warnings — Psychology alerts

GET  /api/v1/governance/report    — Audit & governance report

GET  /health                      — Health check
GET  /dashboard                   — Dashboard HTML
```

## Tuyul Exception v.3 Rules

1. **TWMS minimum 11/12** — struktur teknikal harus EXCELLENT atau PERFECT
2. **Smart money min 80%** — institutional footprint wajib teridentifikasi
3. **RR minimum 1:2.0** — matematika harus viable
4. **Market state TRENDING/RANGING only** — CHOPPY/EXTREME = REJECT
5. **No news danger window** — 30 menit sebelum/sesudah high-impact event
6. **Psychology HALT = absolute** — tidak bisa di-override oleh siapapun
7. **Satu disqualifier = REJECT** — tidak ada negosiasi
8. **Semua keputusan di-journal + di-audit** — mandatory tanpa exception

## Test

```bash
pytest tests/ -v
# Expected: 18 passed
```
