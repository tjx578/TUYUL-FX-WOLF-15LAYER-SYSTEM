# 🔄 END-TO-END SIMULATION  
## TUYUL FX — WOLF 15-LAYER SYSTEM

---

## SCENARIO
- Pair: GBPJPY
- Session: London
- Market: Trending bullish
- News: None

---

## STEP 1 — INGEST
- Tick masuk dari Twelve Data
- CandleBuilder membentuk M15 & H1
- Context diperbarui

---

## STEP 2 — ANALYSIS (L1–L11)

- L1: Context valid, no news lock
- L2: H1 ↔ M15 aligned
- L3: Structure bullish, demand zone
- L4: Score 82/100
- L5: Psychology stable
- L6: Risk feasible
- L7: Win prob 65%
- L8: TII 0.94 | Integrity 0.96
- L9: Liquidity sweep valid
- L10: Position OK
- L11: RR 1:2.6

➡️ Candidate dikirim ke L12

---

## STEP 3 — CONSTITUTION (L12)

9-GATE CHECK:
- Integrity ✅
- TII ✅
- Probability ✅
- RR ✅
- Position ✅
- Market law ✅
- Timeframe law ✅
- Execution rule ✅
- Completeness ✅

➡️ **VERDICT: EXECUTE_BUY**

---

## STEP 4 — EXECUTION

- PendingEngine.place()
- State → PENDING_ACTIVE
- EA menerima command

---

## STEP 5 — MONITORING M15

### Case A — Harga valid
- Pending tetap aktif

### Case B — Invalidation
- CancelEngine.cancel()
- State → CANCELLED

### Case C — Expiry
- ExpiryEngine → CANCELLED

---

## STEP 6 — EA & BROKER

- Pending terisi
- State → FILLED
- TradeJournal & Snapshot L14 tersimpan

---

## SIMULATION RESULT

```

FLOW        : PASS
OVERRIDE    : NONE
RACE ISSUE  : NONE

```

---

Dokumen ini untuk **validasi logika & training**, bukan eksekusi.
