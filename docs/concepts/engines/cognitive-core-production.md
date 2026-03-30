# Core Cognitive Unified - Production Implementation

## Summary

Replaced `/core/core_cognitive_unified.py` with production-ready implementation.

**File Statistics:**
- Size: 44,142 bytes (~43KB)
- Lines: 1,471
- Exports: 61 items

---

## Exception Hierarchy (12 exceptions)

```python
CognitiveError (base)
├── RiskCalculationError
├── ValidationError  
├── InvalidInputError
├── TradingError
│   └── RiskLimitExceeded
├── VaultError
│   ├── VaultPathError
│   └── VaultPersistenceError
├── CalibrationError
├── EmotionFeedbackError
└── TWMSCalculationError
```

---

## Enums (11 enums)

1. **CognitiveBias**: BULLISH, BEARISH, NEUTRAL, SIDEWAYS
2. **MarketRegimeType** (IntEnum): RANGE=0, TREND=1, EXPANSION=2, REVERSAL=3
3. **MarketRegime**: trending_up, trending_down, ranging_high, ranging_mid, ranging_low, transition_bull, transition_bear, volatile, quiet
4. **TrendStrength**: STRONG, MODERATE, WEAK, NONE
5. **ReflexState**: SYNCED, DESYNCED, LOCKOUT, REVIEW
6. **ConfidenceLevel**: VERY_HIGH, HIGH, MEDIUM, LOW, VERY_LOW
7. **FusionMode**: STRICT, MODERATE, LENIENT, ADAPTIVE
8. **ReflectivePhase**: ANALYZING, SYNTHESIZING, VALIDATING, COMPLETE
9. **LayerID**: L0 through L13
10. **SmartMoneySignal**: ACCUMULATION, DISTRIBUTION, NEUTRAL, SWEEP, **MANIPULATION**
11. **InstitutionalBias**: BULLISH, BEARISH, NEUTRAL
12. **Timeframe**: W1, D1, H4, H1, M15

---

## Constants

```python
COHERENCE_THRESHOLD = 0.90
INTEGRITY_MINIMUM = 0.88
REFLEX_GATE_PASS = 0.80

TWMS_WEIGHT_D1 = 0.30
TWMS_WEIGHT_H4 = 0.40
TWMS_WEIGHT_H1 = 0.30

META_LEARNING_RATE = 0.015
META_RESILIENCE_INDEX = 0.93
META_RESONANCE_LIMIT = 0.95
```

---

## Dataclasses (10 dataclasses)

| Dataclass | Decorator | Purpose |
| ----------- | ----------- | --------- |
| `CognitiveState` | `@dataclass` | L0 cognitive snapshot with timestamp, twms_score, risk_level, emotion_index, discipline_score, confluence_count |
| `EmotionFeedbackCycle` | `@dataclass(frozen=True)` | L11 emotion feedback output |
| `ReflexEmotionResult` | `@dataclass(frozen=True)` | L1 reflex-emotion result with gate and state |
| `RegimeAnalysis` | `@dataclass` | L0 regime classification output |
| `CalibrationSummary` | `@dataclass` | Calibration statistics |
| `RiskAssessment` | `@dataclass(slots=True)` | Risk assessment with slots optimization |
| `AdaptiveRiskResult` | `@dataclass` | L13 adaptive risk output |
| `CalibrationResult` | `@dataclass` | Risk calibration output |
| `SmartMoneyAnalysis` | `@dataclass` | L7 smart money detection output |
| `TWMSInput` | `@dataclass` | TWMS input container |
| `TWMSResult` | `@dataclass` | L7/L8 TWMS v2.2 output |

---

## Working Classes (8 production-ready classes)

### 1. RegimeClassifier
**L0 — Cognitive Snapshot**

Real regime detection based on:
- ATR thresholds (low: 0.0005, high: 0.0015)
- Price change analysis
- Trend strength classification

Returns `RegimeAnalysis` with regime, confidence, volatility level.

### 2. ReflexEmotionCore
**L1 — Reflex Context**

Computes reflex-emotion coherence:
- Combines volatility, momentum, volume ratio
- Maintains coherence history (rolling 100 samples)
- State machine: SYNCED, REVIEW, DESYNCED, LOCKOUT
- Gate logic based on REFLEX_GATE_PASS threshold

### 3. IntegrityEngine
**L5 — RGO Governance**

System state verification:
- `evaluate_coherence()` - weighted component scoring
- `validate_integrity()` - threshold checking
- `save_snapshot()` - state persistence (max 1000, prune to 500)
- `is_stable()` - stability ratio check

### 4. SmartMoneyDetector
**L7 — Structural Judgement**

Institutional activity detection:
- Volume spike analysis (threshold: 1.5x)
- Liquidity sweep detection (0.3% threshold)
- Manipulation detection
- Signal: ACCUMULATION, DISTRIBUTION, SWEEP, MANIPULATION, NEUTRAL

### 5. TWMSCalculator v2.2
**L7/L8 — Time-Weighted Multi-Score**

Production weighting:
- D1: 30% contribution
- H4: 40% contribution
- H1: 30% contribution

Validates input ranges [0.0, 1.0], raises `TWMSCalculationError` on invalid input.

### 6. EmotionFeedbackEngine
**L11 — Wolf Discipline**

Emotion feedback cycle:
- Processes win_rate, recent_pnl, consecutive_losses
- Maintains emotion memory (rolling 50 samples)
- Gate states: OPEN, CONDITIONAL, CLOSED
- Returns `EmotionFeedbackCycle` with coherence, delta, gate, confidence

### 7. RiskFeedbackCalibrator
**L11 — Risk Calibration**

Performance-based risk adjustment:
- Learning rate: 0.015 (META_LEARNING_RATE)
- Performance score from win_rate, profit_factor, sharpe
- Recommendations: INCREASE_EXPOSURE, REDUCE_EXPOSURE, MAINTAIN
- Calibration history persistence

### 8. AdaptiveRiskCalculator
**L13 — Adaptive Risk**

5-tier drawdown system:
| Drawdown Range | Multiplier | Tier |
| ---------------- | ------------ | ------ |
| 0-5% | 100% (1.00) | TIER_0 |
| 5-10% | 80% (0.80) | TIER_1 |
| 10-15% | 60% (0.60) | TIER_2 |
| 15-20% | 40% (0.40) | TIER_3 |
| >20% | 20% (0.20) | TIER_4 |

Returns `AdaptiveRiskResult` with recommended_lot, risk_amount, position_value, tier.

---

## Additional Components

### VaultRiskSync
**L13 — Vault Persistence**

Risk configuration persistence:
- Default path: `~/.wolf15/vault/risk/`
- JSON format with datetime serialization
- Methods: `save_risk_config()`, `load_risk_config()`
- Raises `VaultPathError`, `VaultPersistenceError`

### montecarlo_validate()
**L9 — Monte Carlo Probability**

Production Monte Carlo simulation:
- Deterministic bootstrap (seed=42)
- Default: 5000 iterations
- Returns metrics:
  - `mean_return`
  - `sharpe_ratio`
  - `max_drawdown`
  - `win_probability`
  - `value_at_risk` (VaR at confidence_level)
  - `expected_shortfall` (CVaR/ES)

### Helper Functions (8)

1. `compute_reflex_emotion(volatility, momentum, volume_ratio)` → float
2. `reflex_check(coherence, threshold)` → bool
3. `calculate_risk(balance, risk_percent, entry, stop)` → float
4. `calibrate_risk(base_risk, win_rate, profit_factor)` → float
5. `calculate_confluence_score(signals, weights)` → float
6. `validate_cognitive_thresholds(coherence, integrity)` → bool
7. `calculate_risk_adjusted_score(base_score, risk_factor, confidence)` → float

---

## Code Quality

✅ **Python 3.11+ type hints** throughout  
✅ **No bare except blocks**  
✅ **Pathlib** for file operations  
✅ **Proper exception handling** with custom exceptions  
✅ **Deterministic** where appropriate (Monte Carlo seed)  
✅ **Production-ready** - no stubs or NotImplementedError  

---

## Testing

All components tested and verified:
- Exception hierarchy propagation
- Enum member counts
- Dataclass instantiation
- All 8 classes with real data
- Monte Carlo simulation
- 5-tier drawdown system
- Helper functions
- Import/export integrity

---

## Usage Example

```python
from core.core_cognitive_unified import (
    RegimeClassifier,
    TWMSCalculator,
    AdaptiveRiskCalculator,
    montecarlo_validate
)

# Regime classification
classifier = RegimeClassifier()
regime = classifier.classify("EURUSD", "H1", market_data)

# TWMS calculation
twms = TWMSCalculator()
result = twms.calculate("EURUSD", component_scores={"D1": 0.8, "H4": 0.75, "H1": 0.85})

# Adaptive risk
risk_calc = AdaptiveRiskCalculator()
risk_result = risk_calc.calculate(
    base_risk=0.02,
    drawdown=0.08,  # 8% drawdown → TIER_1 (80% multiplier)
    balance=10000,
    entry_price=1.1000,
    stop_loss=1.0950
)

# Monte Carlo validation
mc_result = montecarlo_validate(returns_history, iterations=5000)
print(f"Sharpe: {mc_result['sharpe_ratio']:.2f}")
print(f"VaR 95%: {mc_result['value_at_risk']:.4f}")
```

---

## Files Modified

1. **`core/core_cognitive_unified.py`** - 1,471 lines, 44KB, production implementation
2. **`scripts/generate_cognitive_core.py`** - generator script for reproducibility

---

**Status:** ✅ Complete - Production-ready with all requirements met  
**Commit:** `23563b4`
