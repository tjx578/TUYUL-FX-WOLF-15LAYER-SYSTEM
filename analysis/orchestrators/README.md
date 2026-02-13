# Wolf Sovereign Pipeline - Master Orchestrator

## Overview

The Wolf Sovereign Pipeline is the master orchestrator for the Wolf 15-Layer trading analysis system. It provides a single entry point for the complete analysis flow, fixing critical architectural issues and integrating previously orphaned L13/L15 governance layers.

## Problem Solved

This orchestrator fixes 5 critical issues in the system:

1. **Dual Pipeline Issue**: Previously, two different verdict systems existed - one in `reasoning/engine.py` (simplified) and one in `constitution/verdict_engine.py` (full cascade). The orchestrator uses `generate_l12_verdict()` as the **SOLE AUTHORITY**.

2. **VIX Multiplier**: Properly applies VIX risk multiplier to L7 win probability (no longer a self-assignment bug).

3. **L13 + L15 Orphan**: L13 (reflective) and L15 (meta-sovereignty) were well-written but never wired to any pipeline. Now integrated with a proper two-pass governance loop.

4. **No Single Entry Point**: Provides a unified orchestrator that manages the complete flow.

5. **Synthesis Contract Mismatch**: `build_l12_synthesis()` produces ALL required keys for `generate_l12_verdict()` with correct structure.

## Architecture

### 6-Phase Execution Flow

```
Phase 1: Independent Analysis (L1, L2, L3)
    ↓
Phase 2: Dependent Analysis (L4, L5, L7, L8, L9)
    ↓
Phase 3: Execution + Risk + Sizing (L11 → L6 → L10)
    ↓
Phase 4: Build Synthesis → L12 Constitutional Verdict
    ↓
Phase 5: Two-Pass Governance (L13 pass 1 → L15 → L13 pass 2)
    ↓
Phase 6: Sovereignty Enforcement (GRANTED/RESTRICTED/REVOKED)
```

### Key Components

#### 1. WolfSovereignPipeline

Master orchestrator class that:
- Lazy-loads all layer analyzers to avoid circular imports
- Executes layers in correct order (L11 BEFORE L6)
- Applies VIX multiplier properly
- Respects `proceed_to_L13` flag from L12 verdict
- Provides structured logging at each phase
- Handles errors gracefully

#### 2. build_l12_synthesis()

Contract-safe synthesis builder that produces a dict with ALL required keys:
- `scores`: wolf_30_point, f_score, t_score, fta_score, exec_score
- `layers`: L8_tii_sym, L8_integrity_index, L7_monte_carlo_win, conf12
- `execution`: rr_ratio, direction, entry_price, stop_loss, take_profit_1, entry_zone, risk_percent, risk_amount, lot_size
- `propfirm`: compliant, violations
- `risk`: current_drawdown, max_drawdown
- `bias`: fundamental, technical
- `macro_vix`: regime_state, risk_multiplier
- `system`: latency_ms, safe_mode
- `pair`: symbol

#### 3. L13ReflectiveEngine

Two-pass reflective authority that checks:
- **LRCE** (Layer Recursive Coherence): directional alignment across layers
- **FRPC** (Fusion Recursive Pattern Check): verdict/bias consistency
- **αβγ** (Alpha-Beta-Gamma) quality score: `alpha × 0.40 + beta × 0.30 + gamma × 0.30`
- **Drift ratio**: computed from meta_integrity

Pass 1 uses `meta_integrity = 1.0` (baseline), Pass 2 uses value from L15.

#### 4. L15MetaSovereigntyEngine

Meta-sovereignty and execution rights engine:
- Computes meta integrity (valid layer ratio)
- Calculates vault sync: `feed_freshness × 0.50 + redis_health × 0.30 + meta_integrity × 0.20`
- Returns execution rights:
  - **GRANTED**: Full execution with `lot_multiplier = 1.0`
  - **RESTRICTED**: Reduced lot size with `lot_multiplier = 0.5`
  - **REVOKED**: No execution, verdict downgraded to HOLD

Thresholds:
- `vault_sync_min = 0.985` (from config)
- `drift_max = 0.15` (from config)

#### 5. SovereignResult

Complete pipeline output dataclass containing:
- `symbol`: Trading pair
- `synthesis`: Full synthesis dict
- `l12_verdict`: Constitutional verdict
- `reflective_pass1`: L13 pass 1 results (if EXECUTE)
- `meta`: L15 meta-sovereignty results (if EXECUTE)
- `reflective_pass2`: L13 pass 2 results (if EXECUTE)
- `enforcement`: Sovereignty enforcement decision (if EXECUTE)
- `latency_ms`: Total pipeline execution time
- `errors`: List of errors encountered

## Usage

### Basic Usage

```python
from analysis.orchestrators.wolf_sovereign_pipeline import WolfSovereignPipeline

# Create pipeline instance
pipeline = WolfSovereignPipeline()

# Run complete analysis
result = pipeline.run(
    symbol="EURUSD",
    system_metrics={"latency_ms": 45, "safe_mode": False}
)

# Check verdict
print(f"Verdict: {result.l12_verdict['verdict']}")
print(f"Confidence: {result.l12_verdict['confidence']}")
print(f"Latency: {result.latency_ms:.2f}ms")

# Check if governance was executed
if result.enforcement:
    print(f"Execution Rights: {result.enforcement['execution_rights']}")
    print(f"Lot Multiplier: {result.enforcement['lot_multiplier']}")
```

### Early Exit

Pipeline exits early if:
1. Any layer (L1-L3) is invalid
2. L12 verdict is not EXECUTE (no L13/L15 processing)

```python
result = pipeline.run("EURUSD")

if result.errors:
    print(f"Early exit: {result.errors}")
    # result.l12_verdict will be HOLD
    # result.reflective_pass1 will be None
```

### Synthesis Building

To use the synthesis builder directly:

```python
from analysis.orchestrators.wolf_sovereign_pipeline import build_l12_synthesis

synthesis = build_l12_synthesis(
    symbol="EURUSD",
    l1=l1_output,
    l2=l2_output,
    l3=l3_output,
    # ... all layer outputs
    macro_vix_state=macro_state,
    system_metrics={"latency_ms": 50, "safe_mode": False}
)

# synthesis is now ready for generate_l12_verdict()
from constitution.verdict_engine import generate_l12_verdict
verdict = generate_l12_verdict(synthesis)
```

### L13/L15 Usage

To use reflective and meta-sovereignty engines directly:

```python
from analysis.orchestrators.wolf_sovereign_pipeline import (
    L13ReflectiveEngine,
    L15MetaSovereigntyEngine
)

# L13 two-pass analysis
l13 = L13ReflectiveEngine()
pass1 = l13.reflect(synthesis, l12_verdict, meta_integrity=1.0)
print(f"Pass 1 αβγ Score: {pass1['abg_score']:.3f}")

# L15 meta-sovereignty
l15 = L15MetaSovereigntyEngine()
meta = l15.compute_meta(synthesis, l12_verdict, pass1)
print(f"Meta Integrity: {meta['meta_integrity']:.3f}")

# L13 pass 2 with adjusted meta_integrity
pass2 = l13.reflect(synthesis, l12_verdict, meta_integrity=meta['meta_integrity'])
print(f"Pass 2 αβγ Score: {pass2['abg_score']:.3f}")
print(f"Drift Ratio: {pass2['drift_ratio']:.3f}")

# Sovereignty enforcement
enforcement = l15.enforce_sovereignty(l12_verdict, pass2, meta)
print(f"Execution Rights: {enforcement['execution_rights']}")
```

## Testing

The orchestrator has comprehensive test coverage:

```bash
# Run all orchestrator tests
pytest tests/test_wolf_sovereign_pipeline.py -v

# Run specific test class
pytest tests/test_wolf_sovereign_pipeline.py::TestWolfSovereignPipeline -v

# Run manual integration test
python tests/manual_test_orchestrator.py
```

Test coverage includes:
- ✅ Pipeline instantiation and lazy loading
- ✅ Synthesis builder produces all required L12 keys
- ✅ L13 two-pass produces different results
- ✅ L15 sovereignty returns GRANTED/RESTRICTED/REVOKED
- ✅ Early exit when L12 verdict is not EXECUTE
- ✅ VIX multiplier is properly applied
- ✅ Layer execution order (L11 before L6)

## Known Limitations

### Placeholder Values (Production TODO)

The orchestrator currently uses placeholder values for:

1. **Risk Management** (`build_l12_synthesis()`):
   - `risk_amount = 100.0` - Should come from account state
   - `lot_size = 0.01` - Should be computed by dashboard
   
2. **Vault Sync** (`L15MetaSovereigntyEngine.compute_meta()`):
   - `feed_freshness = 1.0` - Should query LiveContextBus feed age
   - `redis_health = 1.0` - Should check Redis connection health

**Before production use**, these must be replaced with real values from:
- Dashboard account manager (for risk_amount, lot_size)
- LiveContextBus (for feed_freshness)
- Redis health check (for redis_health)

## Layer Execution Order

The orchestrator ensures correct execution order:

```
L1 → L2 → L3 (independent)
    ↓
L4 (needs L1, L2, L3)
L5 (needs L2 volatility)
L7 (needs L4 technical_score)
L8 (needs L1-L7)
L9 (needs L3 structure)
    ↓
L11 (RR calculation) → L6 (needs L11 RR) → L10 (needs L6 + L9)
```

**Critical**: L11 MUST execute before L6, as L6 requires RR value from L11.

## Integration with Existing Systems

### With reasoning/engine.py

The old `Wolf15LayerEngine` in `reasoning/engine.py` should be **deprecated** in favor of `WolfSovereignPipeline`. The new orchestrator:
- Uses the same layer analyzers
- Calls the same `generate_l12_verdict()` from constitution
- Adds L13/L15 governance that was missing
- Fixes layer execution order issues

### With constitution/verdict_engine.py

The orchestrator uses `generate_l12_verdict()` as the **SOLE AUTHORITY** for verdicts. No other verdict system should be used in production.

### With Dashboard

The orchestrator output (`SovereignResult`) provides all data needed by dashboard:
- `l12_verdict`: Contains execution details (entry, stop, TP, lot_size)
- `enforcement`: Contains execution rights and lot multiplier adjustments
- Dashboard should use `enforcement.lot_multiplier` to adjust final lot size

## Configuration

Thresholds are loaded from `config/constants.py`:

```python
from config.constants import get_threshold

VAULT_SYNC_MIN = get_threshold("layers.l15.vault_sync_min", 0.985)
DRIFT_MAX = get_threshold("layers.l15.drift_max", 0.15)
```

To adjust thresholds, update `config/constitution.yaml`.

## Security

✅ CodeQL scan: **0 security alerts**

The orchestrator:
- Has no SQL injection risks (no DB queries)
- Has no command injection risks (no shell execution)
- Has no secrets in code (uses config system)
- Uses type hints for safety
- Has comprehensive error handling

## Contributing

When modifying the orchestrator:

1. Maintain the 6-phase execution order
2. Keep `generate_l12_verdict()` as sole authority
3. Add tests for new features
4. Update this README
5. Run full test suite: `pytest tests/test_wolf_sovereign_pipeline.py -v`
6. Run security scan: CodeQL should show 0 alerts

## License

Part of the Wolf-15 Layer Trading System.
