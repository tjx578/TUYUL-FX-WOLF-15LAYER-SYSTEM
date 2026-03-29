# V11 Hyper-Precision Sniper Engine Suite

## Overview

The V11 suite is a **post-pipeline overlay** that applies extreme selectivity filtering to trade signals from the existing Wolf 15-Layer Constitutional Pipeline. It acts as an additional quality gate that can **ONLY block trades** (veto EXECUTE decisions), never override HOLD decisions.

**L12 Constitutional Authority is PRESERVED.**

## Architecture

```
Existing Pipeline (UNTOUCHED) → PipelineResult
        ↓
V11PipelineHook.evaluate()
        ↓
V11DataAdapter.collect()  →  Runs v11 engines (Exhaustion, DVG, Sweep)
        ↓
ExtremeSelectivityGateV11.evaluate()  →  9 VETO → SCORING → 5 EXEC thresholds
        ↓
V11Overlay { should_trade: bool, gate_result, ... }
```

## Decision Matrix

| L12 Verdict | V11 Gate | Final Decision | Reasoning |
| ------------- | ---------- | ---------------- | ----------- |
| EXECUTE | ALLOW | ✅ TRADE | Both approve (Sniper Entry) |
| EXECUTE | BLOCK | ❌ NO TRADE | V11 veto |
| HOLD/NO_TRADE | * | ❌ NO TRADE | L12 authority preserved |

## Components

### 1. Configuration (`config/v11.yaml`)

Consolidated configuration with all thresholds:

```yaml
enabled: true

selectivity:
  score_min: 0.78
  monte_carlo_win_min: 0.70
  posterior_min: 0.72
  mc_pf_min: 1.8
  vol_expansion_min: 1.4

veto:
  regime_confidence_floor: 0.65
  discipline_min: 0.90
  eaf_min: 0.75
  cluster_exposure_max: 0.75
  correlation_max: 0.90
```

### 2. Exhaustion Detector (`exhaustion_detector.py`)

Detects structural exhaustion states:
- **BUY_EXHAUSTION**: Price overextended upward
- **SELL_EXHAUSTION**: Price overextended downward
- **NEUTRAL**: Normal conditions

**Metrics:**
- Distance from rolling mean (normalized)
- Impulse strength (price displacement / ATR)
- Wick pressure ratio (upper vs lower wicks)

### 3. Exhaustion-Divergence Fusion (`exhaustion_dvg_fusion.py`)

Combines exhaustion signals with multi-timeframe divergence:
- Exhaustion weight: 0.45
- Divergence weight: 0.55 (split across H1, H4, D1)

### 4. Liquidity Sweep Scorer (`liquidity_sweep_scorer.py`)

5-factor sweep quality assessment:
1. Equal high/low detection
2. Wick rejection strength
3. Volume confirmation
4. Failed breakout (didn't close beyond level)
5. Multi-bar pattern

### 5. Extreme Selectivity Gate (`extreme_selectivity_gate.py`)

**3-Layer Filter:**

#### Layer 1: VETO (9 binary conditions)
Any TRUE = instant BLOCK:
1. Regime == "SHOCK"
2. Regime confidence < 0.65
3. Regime transition risk > 0.40
4. Vol state not in allowed set
5. Cluster exposure >= 0.75
6. Rolling correlation >= 0.90
7. Emotion delta > 0.25
8. Discipline score < 0.90
9. EAF score < 0.75

#### Layer 2: SCORING (weighted composite)
```
score = 0.20×regime_conf + 0.15×liquidity + 0.15×exhaustion
      + 0.10×dvg + 0.15×mc_win + 0.15×posterior + 0.10×(1-cluster_exposure)
```

#### Layer 3: EXECUTION (5 simultaneous thresholds)
ALL must pass:
- score >= 0.78
- mc_win >= 0.70
- posterior >= 0.72
- mc_pf >= 1.8
- vol_expansion >= 1.4

### 6. Data Adapter (`data_adapter.py`)

Bridges existing pipeline to v11 gate:
- Extracts regime, volatility, emotion data from synthesis
- Runs v11-specific engines (exhaustion, DVG, sweep)
- Reuses existing CorrelationRiskEngine
- Assembles ExtremeGateInput

### 7. Pipeline Hook (`pipeline_hook.py`)

Integration point with existing pipeline:
- Master switch: `enabled`
- Lazy engine loading (prevents circular imports)
- Timing/latency tracking
- Structured logging

### 8. Regime AI (`regime_ai/`)

Online K-Means clustering:
- Persistent state (JSON)
- Exponential confidence decay
- 6-feature extraction from OHLCV
- Label mapping: TRENDING, RANGING, EXPANSION, SHOCK

### 9. Portfolio Optimizer (`portfolio/`)

Markowitz + Kelly:
- Kelly fraction: `(b×p - q) / b`
- Shrinkage covariance (Ledoit-Wolf)
- Analytical 2×2 matrix inverse
- Confidence power scaling

### 10. Edge Validator (`validation/`)

Statistical significance testing:
- One-sided binomial test
- Wilson score confidence interval
- Expected value: `EV = WR × RR - (1-WR)`
- Minimum trades estimator

## Usage

### Basic Usage

```python
from engines.v11 import V11PipelineHook

# Initialize hook
hook = V11PipelineHook()

# Evaluate pipeline result
overlay = hook.evaluate(
    pipeline_result=result,
    symbol="EURUSD",
    timeframe="H1"
)

# Check final decision
if overlay.should_trade:
    # Execute trade
    execute_trade(...)
else:
    # No trade (L12 reject or v11 veto)
    if overlay.skipped_reason:
        logger.info(f"Skipped: {overlay.skipped_reason}")
    elif overlay.gate_result:
        logger.info(f"V11 veto: {overlay.gate_result['veto_reasons']}")
```

### Configuration

Enable/disable v11:
```yaml
# config/v11.yaml
enabled: true  # or false
```

Adjust thresholds:
```yaml
selectivity:
  score_min: 0.80  # More selective
  monte_carlo_win_min: 0.75
```

### Governance Mode

```yaml
governance:
  mode: "ANALYSIS_ONLY_UNTIL_APPROVED"  # v11 runs but doesn't block
  # mode: "PRODUCTION"  # v11 veto is enforced
```

## Testing

Run v11 tests:
```bash
pytest tests/test_v11_*.py -v
```

All 51 tests should pass:
- `test_v11_config.py` - Configuration accessor
- `test_v11_exhaustion.py` - Exhaustion detector
- `test_v11_gate.py` - Extreme selectivity gate
- `test_v11_sweep.py` - Liquidity sweep scorer
- `test_v11_edge_validator.py` - Edge validator

## Monitoring

### Latency

V11 tracks latency:
```python
overlay = hook.evaluate(...)
print(f"V11 latency: {overlay.latency_ms:.2f}ms")
```

Default budget: 100ms (configurable)

### Logging

Structured decision logging:
```
V11 Decision: symbol=EURUSD L12=EXECUTE v11=ALLOW final=True score=0.825 latency=45.23ms
V11 VETO: symbol=GBPUSD reasons=('regime_shock', 'discipline_low:0.850<0.900')
```

## Constraints Met

✅ **ZERO modifications to existing files** - All code in `engines/v11/` and `config/v11.yaml`
✅ **ZERO new dependencies** - Uses numpy only (already in repo)
✅ **No scipy** - All statistical functions from scratch
✅ **All dataclasses frozen=True with to_dict()** - Immutable results
✅ **All engines ANALYSIS-ONLY** - No execution side-effects
✅ **L12 Constitutional Authority PRESERVED** - v11 can only BLOCK
✅ **Existing engines REUSED** - CorrelationRiskEngine, LiveContextBus
✅ **Config follows pattern** - YAML + dot-path accessor

## Performance

- **Typical latency**: 20-50ms
- **Memory overhead**: Minimal (streaming computation)
- **Storage**: Regime AI state (~10KB JSON)

## Security

- No external API calls
- No credential storage
- No file system writes (except regime AI state)
- Passed CodeQL security scan (0 vulnerabilities)

## Future Enhancements

1. **Walk-forward optimization** - All gate thresholds are constructor params
2. **Multi-timeframe analysis** - Currently uses H1, can extend to M15/H4
3. **Regime strategy routing** - Map regime labels to different strategies
4. **Edge tracking dashboard** - Real-time edge validation monitoring
5. **A/B testing framework** - Compare v11 enabled/disabled performance

## References

- Constitution: `config/constitution.yaml`
- Pipeline: `pipeline/wolf_constitutional_pipeline.py`
- L12 Verdict: `constitution/verdict_engine.py`
- Context Bus: `context/live_context_bus.py`

## License

Part of TUYUL-FX-WOLF-15LAYER-SYSTEM
