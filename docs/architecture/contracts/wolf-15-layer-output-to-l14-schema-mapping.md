# 🔗 WOLF 15-LAYER OUTPUT ↔ L14 JSON SCHEMA MAPPING
## TUYUL FX AGI ULTIMATE HYBRID — v7.4r∞

---

## 🎯 PURPOSE

Dokumen ini mendefinisikan **hubungan 1-banding-1** antara:

- **WOLF 15-Layer Output Template (Human / Analysis View)**
- **L14 JSON Output (`schemas/l14_schema.json`) (Machine / System View)**

⚠️ Jika terjadi konflik:
> **Schema + Constitution menang.**

---

## 🧠 MAPPING PRINSIP

| Layer | Status di JSON | Catatan |
| ------ | --------------- | --------- |
| L1–L11 | Aggregated | Disimpan sebagai nilai numerik / ringkas |
| L12 | Mandatory | Verdict final (authority) |
| L13 | Aggregated | Field energy & reflective metrics |
| L14 | JSON | Output resmi sistem |
| L15 | ❌ Not serialized | Meta-awareness only |

---

## 🟢 CORE IDENTIFIERS

| TEMPLATE FIELD | L14 JSON FIELD |
| --------------- | --------------- |
| Instrument / Pair | `pair` |
| Analysis Time | `timestamp` |
| Final Verdict | `verdict` |
| Confidence | `confidence` |
| Wolf Status | `wolf_status` |

---

## 📊 SCORE & DISCIPLINE MAPPING

| TEMPLATE (L4 / L5 / L7 / L8) | JSON FIELD |
| ----------------------------- | ----------- |
| Wolf 30-Point Score | `scores.wolf_30_point` |
| F-Score | `scores.f_score` |
| T-Score | `scores.t_score` |
| FTA Score % | `scores.fta_score` |
| FTA Multiplier | `scores.fta_multiplier` |
| Psychology Score | `scores.psychology_score` |
| Technical Score | `scores.technical_score` |

---

## 🌍 CONTEXT & COGNITIVE (L1)

| TEMPLATE FIELD | JSON FIELD |
| --------------- | ----------- |
| Market Regime | `cognitive.regime` |
| Dominant Force | `cognitive.dominant_force` |
| Cognitive Bias | `cognitive.cbv` |
| CSI | `cognitive.csi` |

---

## 🎲 PROBABILITY & VALIDATION (L7)

| TEMPLATE FIELD | JSON FIELD |
| --------------- | ----------- |
| Win Probability | `layers.L7_monte_carlo_win` |
| CONF₁₂ | `fusion_frpc.conf12` |

---

## 🧮 TII & INTEGRITY (L8)

| TEMPLATE FIELD | JSON FIELD |
| --------------- | ----------- |
| TIIₛᵧₘ | `layers.L8_tii_sym` |
| Integrity Index | `layers.L8_integrity_index` |

---

## 🏦 SMC & LIQUIDITY (L9)

| TEMPLATE FIELD | JSON FIELD |
| --------------- | ----------- |
| Liquidity Score | `layers.L9_liquidity_score` |
| DVG Confidence | `layers.L9_dvg_confidence` |
| Market Structure | `smc.structure` |
| OB Present | `smc.ob_present` |
| FVG Present | `smc.fvg_present` |
| Sweep Detected | `smc.sweep_detected` |
| SMC Bias | `smc.bias` |

---

## ⚖️ EXECUTION & RR (L10–L11)

| TEMPLATE FIELD | JSON FIELD |
| --------------- | ----------- |
| Entry Zone | `execution.entry_zone` |
| Entry Price | `execution.entry_price` |
| Stop Loss | `execution.stop_loss` |
| Take Profit 1 | `execution.take_profit_1` |
| Execution Mode | `execution.execution_mode` |
| RR Ratio | `execution.rr_ratio` |
| Lot Size | `execution.lot_size` |
| Risk % | `execution.risk_percent` |
| Risk Amount | `execution.risk_amount` |

---

## 🚪 CONSTITUTIONAL GATES (L12)

| TEMPLATE GATE | JSON FIELD |
| -------------- | ----------- |
| Gate 1 – TII | `gates.gate_1_tii` |
| Gate 2 – FRPC | `gates.gate_2_frpc` |
| Gate 3 – RR | `gates.gate_3_rr` |
| Gate 4 – Integrity | `gates.gate_4_integrity` |
| Gate 5 – Monte Carlo | `gates.gate_5_montecarlo` |
| Gate 6 – Prop Firm | `gates.gate_6_propfirm` |
| Gate 7 – Drawdown | `gates.gate_7_drawdown` |
| Gate 8 – Latency | `gates.gate_8_latency` |
| Gate 9 – CONF₁₂ | `gates.gate_9_conf12` |
| Gates Passed | `gates.total_passed` |
| Final Gate Result | `final_gate` |

---

## 🧬 REFLECTIVE & META (L13–L15)

| TEMPLATE FIELD | JSON FIELD |
| --------------- | ----------- |
| α β γ | `trq3d.alpha / beta / gamma` |
| Drift | `trq3d.drift` |
| Mean Energy | `trq3d.mean_energy` |
| LRCE | `lfs.lrce` |
| FRPC Energy | `fusion_frpc.frpc_energy` |
| Meta Integrity | `meta16.meta_integrity` |
| Reflective Coherence | `meta16.reflective_coherence` |

⚠️ **L15 tidak menentukan eksekusi**, hanya audit & evolution.

---

## 🔒 CONSTITUTIONAL NOTICE

- JSON schema adalah **kontrak mesin**
- Template adalah **kontrak manusia**
- L12 adalah **otoritas tunggal**

Jika field tidak ada di schema:
→ **tidak boleh diekspor**

Jika field ada di schema:
→ **wajib diisi atau eksplisit null**

---

## ✅ FINAL STATUS

```

TEMPLATE ↔ SCHEMA : FULLY SYNCED
AMBIGUITY         : ZERO
RUNTIME IMPACT    : NONE
VERSION           : v7.4r∞

```

---
