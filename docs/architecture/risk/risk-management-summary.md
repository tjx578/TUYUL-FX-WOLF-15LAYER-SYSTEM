# 📊 Risk Management Summary — Wolf-15 Layer System

> **Last Updated:** February 15, 2026
> **Version:** 2.0 — Dynamic Position Sizing Engine (Kelly+CVaR Hybrid)
> **Authority:** Document is informational only. Layer-12 Constitution is sole decision authority.

---

## Table of Contents

1. [Architecture Overview](#-architecture-overview)
2. [Dynamic Position Sizing Engine]
(#-dynamic-position-sizing-engine)

3. [Kelly Criterion Component]
(#1%EF%B8%8F%E2%83%A3-kelly-criterion-growth-optimizer)
4. [CVaR Tail Risk Component]
(#2%EF%B8%8F%E2%83%A3-cvar-tail-risk-protection)

5. [Volatility Clustering Component]
(#3%EF%B8%8F%E2%83%A3-volatility-clustering-adjustment)
6. [Bayesian Posterior Component]
(#4%EF%B8%8F%E2%83%A3-bayesian-posterior-confidence)

7. [Risk Multiplier Aggregator]
(#%EF%B8%8F-risk-multiplier-aggregator)

8. [Risk Manager] (#-risk-manager)

9. [Gate 11: Kelly Edge Gate]
(#-gate-11-kelly-edge-gate)
10. [Integration Flow](#-integration-flow)
11. [Configuration Reference](#-configuration-reference)
12. [File Map](#-file-map)
13. [Authority Boundaries](#-authority-boundaries)
14. [Prop Firm Compliance](#-prop-firm-compliance)
15. [Testing Coverage](#-testing-coverage)

---

## 🏗 Architecture Overview

The Wolf-15 risk management system uses a **multi-layer hybrid approach** that
combines four independent risk-adjustment factors into a single position-sizing
recommendation. No single component has execution authority.

┌──────────────────────────────────────────────────────────────────┐
│                    RISK MANAGEMENT DATA FLOW                      │
│                                                                   │
│  L7 Monte Carlo ──→ win_probability, avg_win, avg_loss           │
│  L7 Bayesian    ──→ posterior_win_probability                    │
│  Vol Clustering ──→ risk_multiplier                              │
│  Trade History  ──→ returns_history (for CVaR)                   │
│         │                                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────┐                         │
│  │ RiskMultiplierAggregator            │                         │
│  │   macro × session × regime ×        │                         │
│  │   vol_clustering × correlation      │                         │
│  │   → composite_multiplier            │                         │
│  └────────────┬────────────────────────┘                         │
│               │                                                   │
│               ▼                                                   │
│  ┌─────────────────────────────────────┐                         │
│  │ DynamicPositionSizingEngine         │                         │
│  │   Kelly × CVaR × Vol × Bayesian    │                         │
│  │   → final_fraction (0.0 – 0.03)    │                         │
│  │   → risk_percent (0.0% – 3.0%)     │                         │
│  └────────────┬────────────────────────┘                         │
│               │                                                   │
│               ├──→ RiskManager.evaluate(                         │
│               │      dynamic_risk_percent=final_fraction)        │
│               │      → trade_allowed, recommended_lot            │
│               │                                                   │
│               ├──→ L10 Position Analyzer                         │
│               │      → Geometry validation, pip calc, lot_size   │
│               │                                                   │
│               └──→ VerdictEngine Gate 11                         │
│                      → Kelly edge check (constitutional)         │
│                                                                   │
│  ┌─────────────────────────────────────┐                         │
│  │ L12 Verdict Engine (10+1 gates)     │                         │
│  │   → SOLE decision authority         │                         │
│  │   → EXECUTE / HOLD / NO_TRADE       │                         │
│  └─────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘

``

---

## 🧠 Dynamic Position Sizing Engine

**File:** `engines/dynamic_position_sizing_engine.py`
**Class:** `DynamicPositionSizingEngine`

### Purpose

Compute the optimal risk fraction per trade by combining four independent
adjustment factors:

``

f_final = Kelly × CVaR_adj × Vol_adj × Posterior_adj
f_final = min(f_final, max_risk_cap)

``

### Why Not Kelly Alone?

| Problem with Pure Kelly | Our Solution |

|---|---|
| Over-aggressive (full Kelly) | Half-Kelly default (configurable) |
| Ignores tail risk | CVaR (Expected Shortfall) dampening |
| Not volatility-aware | Volatility clustering adjustment |
| Assumes known probabilities | Bayesian posterior confidence scaling |
| No absolute ceiling | max_risk_cap (default 3%) |
| Mutable output | Frozen dataclass |
| No edge detection | `edge_negative` flag |

### Constructor Parameters

| Parameter | Type | Default | Description |

|---|---|---|---|
| `max_risk_cap` | float | 0.03 | Absolute maximum risk fraction per trade |
| `kelly_fraction_multiplier` | float | 0.5 | Fraction of full Kelly (1.0 = full, 0.5 = half) |
| `cvar_confidence` | float | 0.95 | CVaR confidence level |
| `cvar_sensitivity` | float | 5.0 | CVaR dampening coefficient |
| `min_returns` | int | 10 | Minimum trade history for CVaR |

### Output: `PositionSizingResult`

| Field | Type | Description |

|---|---|---|
| `kelly_raw` | float | Raw full-Kelly fraction (can be negative) |
| `kelly_fraction` | float | Fractional Kelly after clamp [0, 1] |
| `cvar_adjustment` | float | CVaR dampening factor (0, 1] |
| `volatility_adjustment` | float | Volatility dampening factor (0, 1] |
| `posterior_adjustment` | float | Bayesian posterior scaling [0, 1] |
| `final_fraction` | float | Recommended risk fraction [0, max_risk_cap] |
| `risk_percent` | float | final_fraction × 100 for display |
| `max_risk_cap` | float | Applied cap value |
| `edge_negative` | bool | True if Kelly raw ≤ 0 (no edge) |
| `cvar_value` | float | Computed CVaR (Expected Shortfall) |
| `var_value` | float | Computed VaR at confidence level |
| `payoff_ratio` | float | avg_win / abs(avg_loss) |

---

## 1️⃣ Kelly Criterion (Growth Optimizer)

**Formula:**

``

b = avg_win / |avg_loss|        (payoff ratio)
q = 1 - win_probability

f*= (b × p - q) / b           (raw Kelly fraction)
f_kelly = f* × kelly_fraction_multiplier
f_kelly = clamp(f_kelly, 0, 1)

``

**What it does:**

- Computes the mathematically optimal betting fraction for maximum geometric growth
- Accounts for both win probability AND payoff asymmetry
- Negative Kelly = no statistical edge → size 0

**Institutional practice:**

- Full Kelly is theoretically optimal but practically dangerous
- Half-Kelly (default) sacrifices ~25% growth for ~50% variance reduction
- Quarter-Kelly used by ultra-conservative funds

---

## 2️⃣ CVaR Tail Risk Protection

**Formula:**

``

VaR_95 = percentile(returns, 5%)               5th percentile
CVaR   = mean(returns where returns ≤ VaR_95)  Expected Shortfall

cvar_adjustment = 1 / (1 + |CVaR| × cvar_sensitivity)

``

**What it does:**

- Measures the average loss in the worst 5% of trades
- Larger tail losses → stronger dampening → smaller position
- Never amplifies beyond Kelly (adjustment ∈ (0, 1])

**Bug guards:**

- Empty tail slice → falls back to VaR as CVaR
- Minimum return history enforced (default 10)

---

## 3️⃣ Volatility Clustering Adjustment

**Formula:**

``

volatility_adjustment = 1 / max(0.01, volatility_multiplier)
volatility_adjustment = clamp(adjustment, 0, 1)

``
**What it does:**

- When VolatilityClusteringModel detects persistence (multiplier > 1), position shrinks
- Prevents concentration of risk during volatility regimes
- multiplier = 1.0 → neutral (no clustering)

**Source:** `engines/volatility_clustering_model.py` → `.risk_multiplier`

---

## 4️⃣ Bayesian Posterior Confidence

**Formula:**

``
posterior_adjustment = clamp(posterior_probability, 0, 1)

``
**What it does:**

- When Bayesian updating indicates lower confidence, position shrinks
- posterior = 1.0 → full pass-through
- posterior = 0.0 → zero position (no confidence = no trade)
- Never amplifies beyond Kelly (clamped to 1.0)

**Source:** `engines/bayesian_update_engine.py` → `.posterior_probability`

---

## ⚖️ Risk Multiplier Aggregator

**File:** `risk/risk_multiplier.py`
**Class:** `RiskMultiplierAggregator`

### Purpose — Risk Multiplier Aggregation

Combines multiple risk-scaling sources into a single composite multiplier.

``

composite = macro × session × regime × vol_clustering × correlation
composite = clamp(composite, floor, cap)

``

### Sources

| Source | Engine | Meaning of > 1.0 |

|---|---|---

| `macro_multiplier` | Macro volatility / VIX | Elevated macro risk |
| `session_multiplier` | Session/time analysis | Unfavorable trading session |
| `regime_multiplier` | RegimeClassifier | Uncertain market regime |
| `vol_clustering_multiplier` | VolatilityClusteringModel | Volatility persistence |
| `correlation_multiplier` | CorrelationRiskEngine | Correlated pair exposure |

### Parameters

| Parameter | Default | Description

|---|---|---|

| `floor` | 0.1 | Minimum composite (prevents over-compression) |
| `cap` | 3.0 | Maximum composite (prevents over-amplification) |

### Output: `RiskMultiplierResult`

| Field | Type | Description |

|---|---|---|
| `macro_multiplier` | float | Individual source value |
| `session_multiplier` | float | Individual source value |
| `regime_multiplier` | float | Individual source value |
| `vol_clustering_multiplier` | float | Individual source value |
| `correlation_multiplier` | float | Individual source value |
| `composite` | float | Product of all sources, clamped |
| `clamped` | bool | True if composite was clamped |

---

## 🛡 Risk Manager

**File:** `risk/risk_manager.py`
**Class:** `RiskManager`

Purpose

Account-level risk governor that accepts dynamic sizing from DynamicPSE.

### Key Behavior: Dynamic Risk Resolution

``

if dynamic_risk_percent is None:
    effective = static_max_risk_percent         → "STATIC"
elif dynamic_risk_percent ≤ 0:
    effective = 0                                → "DYNAMIC_PSE" + BLOCK
elif dynamic_risk_percent < static_max:
    effective = dynamic_risk_percent             → "DYNAMIC_PSE"
else:
    effective = static_max_risk_percent          → "DYNAMIC_CLAMPED"

``

**Critical rule:** Dynamic can only REDUCE risk, never amplify beyond static maximum.

### Violation Codes

| Code | Blocking | Description |

|---|---|---|
| `DAILY_LOSS_LIMIT_REACHED` | ✅ | Daily P&L exceeds limit |
| `DAILY_LOSS_LIMIT_WARNING` | ❌ | Approaching 80% of daily limit |
| `MAX_OPEN_TRADES_REACHED` | ✅ | Too many concurrent positions |
| `EQUITY_DEPLETED` | ✅ | Account equity ≤ 0 |
| `BALANCE_DEPLETED` | ✅ | Account balance ≤ 0 |
| `DYNAMIC_RISK_ZERO_EDGE` | ✅ | DynamicPSE says no edge |
| `INVALID_STOP_LOSS` | ✅ | Stop loss ≤ 0 pips |
| `INVALID_PIP_VALUE` | ✅ | Pip value ≤ 0 |
| `BELOW_MIN_LOT` | ✅ | Computed lot < min_lot |

### Output: `RiskDecision`

| Field | Type | Description |

|---|---|---|
| `trade_allowed` | bool | True if no blocking violations |
| `recommended_lot` | float | Safe lot size (rounded down) |
| `max_safe_lot` | float | Maximum safe lot before min_lot check |
| `effective_risk_percent` | float | Actual risk % used |
| `risk_source` | str | "STATIC" \| "DYNAMIC_PSE" \| "DYNAMIC_CLAMPED" |
| `risk_amount` | float | Dollar amount at risk |
| `reason` | str | Human-readable decision summary |
| `violations` | tuple[str] | All triggered violation codes |

---

## 🚪 Gate 11: Kelly Edge Gate

**File:** `constitution/verdict_engine.py`
**Method:** `VerdictEngine._evaluate_kelly_edge_gate()`
**Type:** Optional constitutional hard gate

Purpose

When DynamicPSE reports `edge_negative=True` (Kelly raw ≤ 0), this gate
forces a **NO_TRADE** verdict regardless of all other gate scores.

### Rationale

This is a **mathematical safety gate**, not a market opinion:

> "Given the observed win rate and payoff ratio, risking capital
> has negative expected geometric growth."

### Configuration

```yaml
# config/constitution.yaml
kelly_edge_gate:
  enabled: true   # Set false to disable Gate 11
```

### Gate Result Schema

| Field | Type | Description |

|---|---|---|
| `passed` | bool | True if edge is positive |
| `gate` | str | "GATE_11_KELLY_EDGE" |
| `reason` | str | Mathematical explanation |
| `kelly_raw` | float | Raw Kelly fraction |
| `final_fraction` | float | DynamicPSE final fraction |
| `severity` | str | "HARD_BLOCK" or "NONE" |

---

## 🔗 Integration Flow

### Example: Positive Edge (EXECUTE Path)

``
Input:
    MC Win Prob     = 0.63
    Avg Win         = $45
    Avg Loss        = -$25  (PF = 1.8)
    Bayes Posterior = 0.66
    Vol Multiplier  = 1.25

Step 1 — Kelly:
    b = 45/25 = 1.8
    f* = (1.8 × 0.63 - 0.37) / 1.8 = 0.4244
    half-Kelly = 0.2122

Step 2 — CVaR:
    cvar_adj ≈ 0.65  (moderate tail)

Step 3 — Volatility:
    vol_adj = 1/1.25 = 0.80

Step 4 — Posterior:
    post_adj = 0.66

Step 5 — Hybrid:
    final = 0.2122 × 0.65 × 0.80 × 0.66
          = 0.0728
    cap(0.03) → final = 0.03 → 3.0%

But with real CVaR moderate ≈ 0.018 → 1.8%

Result:
    risk_percent = 1.8%
    edge_negative = false
    → RiskManager: APPROVED, lot = f(equity, SL)
    → Gate 11: PASSED
    → L12 can proceed to EXECUTE verdict
``

### Example: Negative Edge (NO_TRADE Path)

``
Input:
    MC Win Prob     = 0.25
    Avg Win         = $15
    Avg Loss        = -$50

Step 1 — Kelly:
    b = 15/50 = 0.3
    f* = (0.3 × 0.25 - 0.75) / 0.3 = -2.25
    kelly_fraction = 0.0

Result:
    final_fraction = 0.0
    edge_negative = true
    → RiskManager: BLOCKED (DYNAMIC_RISK_ZERO_EDGE)
    → Gate 11: HARD_BLOCK
    → L12 forced to NO_TRADE
``

---

## ⚙ Configuration Reference

```yaml
# config/constitution.yaml

position_sizing:
  max_kelly_risk_cap: 0.03          # 3% absolute max risk per trade
  kelly_fraction_multiplier: 0.5    # Half-Kelly (institutional conservative)
  cvar_confidence: 0.95             # 95% CVaR → 5th percentile tail
  cvar_sensitivity: 5.0             # CVaR dampening coefficient
  min_returns_history: 10           # Min trade history for CVaR
  enable_dynamic_sizing: true       # Master switch

kelly_edge_gate:
  enabled: true                     # Gate 11 on/off

risk_multiplier:
  floor: 0.1                        # Minimum composite multiplier
  cap: 3.0                          # Maximum composite multiplier
  sources:
    - macro_volatility
    - session_quality
    - regime_classifier
    - volatility_clustering
    - correlation_risk
```

---

## 📁 File Map

### Engines (Analysis Zone — No Execution)

| File | Class | Purpose |

|---|---|---|
| `engines/dynamic_position_sizing_engine.py` | `DynamicPositionSizingEngine` | Kelly+CVaR+Vol+Bayesian hybrid sizing |
| `engines/monte_carlo_engine.py` | `MonteCarloEngine` | Win probability simulation |
| `engines/bayesian_update_engine.py` | `BayesianProbabilityEngine` | Posterior probability updating |
| `engines/volatility_clustering_model.py` | `VolatilityClusteringModel` | GARCH-style volatility persistence |
| `engines/correlation_risk_engine.py` | `CorrelationRiskEngine` | Multi-pair correlation risk |
| `engines/regime_classifier_ml.py` | `RegimeClassifier` | Hurst-based regime detection |
| `engines/walk_forward_validation_engine.py` | `WalkForwardValidator` | Anti-overfitting validation |
| `engines/__init__.py` | — | Central engine exports |

### Risk Zone (Account-Level Governance)

| File | Class | Purpose |

|---|---|---|
| `risk/risk_multiplier.py` | `RiskMultiplierAggregator` | Composite risk multiplier |
| `risk/risk_manager.py` | `RiskManager` | Account-level risk evaluation |
| `risk/position_sizer.py` | — | Execution-layer lot formula (not enrichment) |
| `risk/prop_firm.py` | — | Prop firm guard (binding) |

### Constitution Zone (Decision Authority)

| File | Class | Purpose |

|---|---|---|
| `constitution/verdict_engine.py` | `VerdictEngine` | L12 verdict + Gate 11 |

### Pipeline Zone (Wiring)

| File | Purpose |

|---|---|
| `pipeline/wolf_constitutional_pipeline.py` | Wires MC→Bayesian→VolCluster→PSE→L10→L12 |

Configuration

| File | Purpose |

|---|---|
| `config/constitution.yaml` | All Risk Management configuration |

---

## 🔒 Authority Boundaries

| Zone | Authority | Cannot Do |

|---|---|---|
| **Engines** (`engines/`) | Compute metrics, sizing recommendations | Execute trades, decide market direction |
| **Risk** (`risk/`) | Evaluate account limits, compute lot sizes | Decide market direction, override L12 |
| **Constitution** (`constitution/`) | SOLE decision authority (EXECUTE/HOLD/NO_TRADE) | Execute trades directly |
| **Execution** (`execution/`) | Execute orders as instructed | Think, analyze, override, decide |
| **Dashboard** (`dashboard/`) | Account governance, risk UI, ledger | Override L12, compute direction |
| **Journal** (`journal/`) | Immutable audit trail | Modify past entries, make decisions |

### Non-Negotiable Rules

1. ❌ **Never** add execution authority to analysis or engines
2. ❌ **Never** allow dashboard or EA to override Layer-12 verdict
3. ❌ **Never** compute market direction in execution/dashboard/risk
4. ❌ **Never** mutate journal entries (append-only)
5. ✅ Dynamic sizing can only REDUCE risk, never amplify beyond static max
6. ✅ Gate 11 is constitutional (can be disabled in config, but cannot be bypassed by engines)

---

## 💼 Prop Firm Compliance

The Dynamic Position Sizing Engine is designed for prop firm safety:

| Constraint | Enforcement | Location |

|---|---|---|
| Max 3% risk per trade | `max_risk_cap=0.03` | DynamicPSE |
| Max 5% daily drawdown | `max_daily_loss_percent=0.05` | RiskManager |
| Max open trades | `max_open_trades=5` | RiskManager |
| Minimum lot size | `min_lot=0.01` | RiskManager |
| No trade without edge | `edge_negative=True → block` | Gate 11 + RiskManager |
| Lot rounds DOWN | `_round_lot_down()` | RiskManager |

### Worst-Case Scenario Protection

``
Even if all systems report maximum confidence:
    Kelly raw = 1.0 (100% win rate)
    CVaR adj  = 1.0 (no tail risk)
    Vol adj   = 1.0 (no clustering)
    Posterior = 1.0 (full confidence)

final = 1.0 × 1.0 × 1.0 × 1.0 = 1.0
    cap(0.03) → 3.0%

Maximum possible risk: 3.0% ✅ Prop-firm safe
``

---

## 🧪 Testing Coverage

### Unit Tests

| File | Tests | Coverage |

|---|---|---|
| `tests/test_dynamic_position_sizing.py` | 42 | Kelly formula, CVaR, volatility, posterior, hybrid, validation, serialization, edge cases |
| `tests/test_risk_multiplier.py` | 11 | All sources, clamping, backward compat, immutability |
| `tests/test_risk_manager.py` | 16 | Static/dynamic risk, violations, lot rounding, edge cases |
| `tests/test_verdict_gate11.py` | 8 | Gate pass/block, backward compat, authority boundary |

### Integration Tests

| File | Tests | Coverage |

|---|---|---|
| `tests/test_l10_kelly_integration.py` | 15 | VolCluster→PSE, PSE→RiskManager, PSE→Gate11, full pipeline, authority, determinism |

### Running Tests

```bash
# All risk management tests
python -m pytest tests/test_dynamic_position_sizing.py tests/test_risk_multiplier.py tests/test_risk_manager.py tests/test_verdict_gate11.py tests/test_l10_kelly_integration.py -v

# Just unit tests
python -m pytest tests/test_dynamic_position_sizing.py -v

# Just integration tests
python -m pytest tests/test_l10_kelly_integration.py -v

# With coverage
python -m pytest tests/test_dynamic_position_sizing.py tests/test_l10_kelly_integration.py --cov=engines --cov=risk --cov=constitution --cov-report=term-missing
```

### Key Test Invariants

1. **`final_fraction` ∈ [0, max_risk_cap]`** — always, under all inputs
2. **`risk_percent == final_fraction × 100`** — exact identity
3. **Negative Kelly → `edge_negative=True` → size 0** — cascade guarantee
4. **Dynamic ≤ Static** — dynamic sizing never exceeds static maximum
5. **Deterministic** — same inputs → identical output, every time
6. **No execution methods** — engine classes have no execute/order/trade attrs
7. **No market direction** — no buy/sell/long/short in any risk component

---

## 📝 Changelog

### v2.0 (February 15, 2026)

**New Files:**

- `engines/dynamic_position_sizing_engine.py` — Kelly+CVaR+Vol+Bayesian hybrid
- `risk/risk_multiplier.py` — Composite risk multiplier aggregator
- `tests/test_dynamic_position_sizing.py` — 42 unit tests
- `tests/test_l10_kelly_integration.py` — 15 integration tests
- `tests/test_risk_multiplier.py` — 11 unit tests
- `tests/test_risk_manager.py` — 16 unit tests
- `tests/test_verdict_gate11.py` — 8 unit tests

**Modified Files:**

- `engines/__init__.py` — Added DynamicPSE exports
- `risk/risk_manager.py` — Added `dynamic_risk_percent` parameter
- `constitution/verdict_engine.py` — Added Gate 11 (Kelly Edge Gate)
- `config/constitution.yaml` — Added `position_sizing`, `kelly_edge_gate`, `risk_multiplier` sections

**Bug Fixes Over Initial Draft:**

- ✅ `avg_loss` sign-agnostic (accepts negative, uses abs)
- ✅ Empty `returns_history` guard (minimum 10 observations)
- ✅ Empty tail slice guard (CVaR NaN prevention)
- ✅ `volatility_multiplier == 0` → clamped to 0.01 (no ZeroDivisionError)
- ✅ `posterior_probability > 1.0` → clamped to 1.0 (no amplification)
- ✅ `win_probability` validated [0, 1]
- ✅ `avg_win ≤ 0` guard (payoff ratio undefined)
- ✅ Fractional Kelly support (default half-Kelly)
- ✅ CVaR sensitivity configurable (no magic constant)
- ✅ Negative Kelly detection flagged (`edge_negative`)
- ✅ Frozen dataclass results with `to_dict()` serialization
