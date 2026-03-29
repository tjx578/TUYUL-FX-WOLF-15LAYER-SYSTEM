# Tick Spike Filter Fix — Root Cause & Solution

## 🔍 Issue Summary

**Error**: `"Tick spike rejected"` appearing in logs at `2026-02-12T17:19:43Z`

**Impact**: Legitimate price movements were being filtered out, preventing analysis layers from receiving valid market data.

---

## 🐛 Root Cause

The tick spike filter in [`ingest/dependencies.py`](ingest/dependencies.py) was rejecting incoming price data when deviation exceeded a **flat 0.5% threshold**.

### Three Problems Identified

| Problem | Severity | Impact |
| --------- | ---------- | -------- |

| **Stale baseline after WS reconnect** | 🔴 Critical | After WebSocket disconnects/reconnects, `_last_prices` held outdated prices. First post-reconnect tick appeared as a "spike" even for legitimate market movement. |
| **XAU_USD volatility** | 🟡 High | Gold (XAU_USD) frequently moves >0.5% between ticks during normal trading. Flat 0.5% threshold was too restrictive for volatile instruments. |
| **No recovery mechanism** | 🟡 Medium | Once a spike was detected, there was no way to auto-reset the baseline for prolonged gaps (weekends, session breaks). |

### Original Code

```python
# Old implementation - flat threshold
MAX_DEVIATION_PCT: float = 0.5  # Too tight for all pairs

def _is_valid_tick(symbol: str, new_price: float) -> bool:
    last_price = _last_prices.get(symbol)
    if last_price is None:
        return True
    deviation = abs(new_price - last_price) / last_price * 100
    if deviation > MAX_DEVIATION_PCT:
        logger.warning("Tick spike rejected", ...)
        return False
    return True
```

---

## ✅ Solution Implemented

### 1. Per-Symbol Dynamic Thresholds

Different instruments have different volatility profiles. The new implementation uses symbol-specific thresholds:

```python
SPIKE_THRESHOLDS: dict[str, float] = {
    "XAUUSD": 2.0,   # Gold is volatile — 2% threshold
    "GBPJPY": 1.0,   # High-vol cross — 1% threshold
    "EURUSD": 0.5,   # Major pair — tight is fine
    "GBPUSD": 0.5,
    "USDJPY": 0.5,
    "AUDUSD": 0.5,
}
_DEFAULT_SPIKE_THRESHOLD: float = 0.5
```

### 2. Staleness-Based Auto-Reset

Tracks the **time** of last tick per symbol using `time.monotonic()`. If no tick received for **60 seconds**, the next tick is automatically accepted as a fresh baseline:

```python
_STALENESS_THRESHOLD_SECONDS: float = 60.0
_last_timestamps: dict[str, float] = {}

def _is_valid_tick(symbol: str, new_price: float) -> bool:
    now = time.monotonic()
    last_ts = _last_timestamps.get(symbol)
    
    # Auto-reset on staleness
    if last_price is None or (
        last_ts is not None and (now - last_ts) > _STALENESS_THRESHOLD_SECONDS
    ):
        logger.info("Tick baseline reset", extra={"reason": "stale_baseline"})
        _last_prices[symbol] = new_price
        _last_timestamps[symbol] = now
        return True
    
    # Normal spike check with dynamic threshold
    threshold = _get_spike_threshold(symbol)
    deviation = abs(new_price - last_price) / last_price * 100
    
    if deviation > threshold:
        logger.warning("Tick spike rejected", extra={"threshold_pct": threshold})
        return False
    
    _last_timestamps[symbol] = now
    return True
```

### 3. Enhanced Logging

Rejections now include:

- `deviation_pct` (rounded to 4 decimals)
- `threshold_pct` (the symbol-specific threshold that was exceeded)

Baseline resets now log:

- `reason`: `"first_tick"` or `"stale_baseline"`

---

## 🧪 Test Coverage

Added 7 new test cases in [`tests/test_tick_spike_filter.py`](tests/test_tick_spike_filter.py):

| Test | Validates |
| ------ | ----------- |

| `test_xauusd_wider_threshold` | XAU_USD accepts 1.5% moves but rejects 2.1% |
| `test_gbpjpy_medium_threshold` | GBP/JPY uses 1% threshold |
| `test_staleness_triggers_baseline_reset` | 60s gap → next tick always accepted |
| `test_no_staleness_within_threshold` | Recent tick (< 60s) still enforces spike filter |
| `test_first_tick_sets_baseline_and_timestamp` | First tick initializes both price and timestamp |
| `test_timestamp_updates_on_valid_tick` | Timestamp refreshed on accepted ticks |
| `test_timestamp_not_updated_on_rejected_tick` | Timestamp unchanged on rejection |

**All 14 tests passing** ✅

---

## 🏛️ Architecture Compliance

| Boundary | Status | Notes |
| ---------- | -------- | ------- |

| **Analysis Zone** | ✅ Clean | Changes confined to `ingest/dependencies.py` (data ingestion layer). |
| **Constitution (L12)** | ✅ No conflict | No decision authority added. Spike filter is still a data quality guard only. |
| **Execution** | ✅ No coupling | EA/execution layers unaffected. |
| **Dashboard** | ✅ No coupling | Receives cleaner data, no interface changes. |
| **Journal** | ✅ No coupling | Immutability preserved. |

---

## 🔧 Configuration

To adjust thresholds, edit `SPIKE_THRESHOLDS` in [`ingest/dependencies.py`](ingest/dependencies.py):

```python
SPIKE_THRESHOLDS: dict[str, float] = {
    "XAUUSD": 2.0,   # Increase if gold still gets false rejections
    "GBPJPY": 1.0,   # Adjust based on observed GBP/JPY volatility
    # ... add new pairs as needed
}
```

To adjust staleness window:

```python
_STALENESS_THRESHOLD_SECONDS: float = 60.0  # Increase to 120.0 for weekend gaps
```

---

## 📊 Expected Behavior Post-Fix

### Scenario 1: Normal Trading (EUR/USD)

- Price moves from 1.0850 → 1.0855 (0.46%) → ✅ **Accepted**
- Price moves from 1.0850 → 1.0960 (1.01%) → ❌ **Rejected** (exceeds 0.5% threshold)

### Scenario 2: Volatile Instrument (XAU_USD)

- Price moves from 2000.0 → 2015.0 (0.75%) → ✅ **Accepted** (within 2% threshold)
- Price moves from 2000.0 → 2042.0 (2.1%) → ❌ **Rejected** (exceeds 2% threshold)

### Scenario 3: WebSocket Reconnect

- Last tick at 1.0850, WS disconnects for 90 seconds
- Market moves to 1.1050 during gap
- WS reconnects, receives tick at 1.1050 → ✅ **Accepted** (staleness reset)
- Logs: `"Tick baseline reset"` with `"reason": "stale_baseline"`

### Scenario 4: Weekend Gap

- Friday close: 1.0850
- Monday open: 1.0900 (0.46% gap)
- First tick after 2+ days → ✅ **Accepted** (staleness > 60s)

---

## 🚀 Deployment Notes

1. **No schema changes** — backward compatible with existing data contracts.
2. **No config file changes** — thresholds are code-level constants (intentional for safety).
3. **Logs will show new fields**:
   - `"Tick baseline reset"` messages (info level) on staleness events
   - `"threshold_pct"` in spike rejection logs
4. **Monitor XAU_USD specifically** — if you still see frequent rejections, increase `SPIKE_THRESHOLDS["XAUUSD"]` to `3.0`.

---

## 📝 Git Commit Reference

**Branch**: `fix/tick-spike-filter`  
**Files Changed**:

- [`ingest/dependencies.py`](ingest/dependencies.py) — Core logic update
- [`tests/test_tick_spike_filter.py`](tests/test_tick_spike_filter.py) — New test coverage

**Backwards Compatibility**:

- ✅ `MAX_DEVIATION_PCT` exported for legacy test compatibility
- ✅ `_is_valid_tick()` signature unchanged

---

## 🔮 Future Enhancements (Optional)

1. **Adaptive thresholds** — Auto-adjust based on recent ATR (Average True Range).
2. **Config-driven thresholds** — Move `SPIKE_THRESHOLDS` to `config/pairs.yaml`.
3. **Metrics dashboard** — Track spike rejection rate per symbol in dashboard.
4. **Alert on excessive rejections** — If >10% of ticks rejected for a symbol in 5 minutes, alert via Telegram.

---

## ✅ Definition of Done

- [x] Per-symbol dynamic thresholds implemented
- [x] Staleness-based auto-reset implemented
- [x] Enhanced logging with threshold details
- [x] 7 new test cases added (all passing)
- [x] Backwards compatibility preserved
- [x] No constitutional boundary violations
- [x] Documentation created

**Status**: ✅ **Production-Ready**
