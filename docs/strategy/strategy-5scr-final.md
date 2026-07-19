# Strategy 5S-CR Final

Status: candidate baseline utama, context-resolved, block-aware, structural TP1 execution

Rule status: **FROZEN**

Validation status: **STRONG PROVISIONAL**

Out-of-sample status: **NOT YET VALIDATED**

Production-proven: **NO**

Rule version: `5scr.final.2026-07-19`

Strategy 5-S Final lama tetap disimpan sebagai benchmark sebelum Context
Resolution. Hasil delapan pair tersisa adalah pengujian out-of-sample pertama;
hasil tersebut tidak boleh dipakai untuk mengubah rule ini.

## Authority chain

```text
Pressure             -> memilih pair dan membentuk lifecycle
Context Resolution   -> menentukan skenario yang boleh dicari
H4                   -> lokasi dan structural TP1
H1                   -> authority arah
M15                  -> break, acceptance, retest, dan timing eksekusi
M1                   -> box aktual dan fill
Risk Engine          -> lot berdasarkan structural SL
```

Railway/Wolf15 memegang seluruh authority. EA MT5 hanya menerima command yang
sudah membawa proof hash 5S-CR, memeriksa binding mekanis, melakukan broker side
effect, dan melaporkan hasil. EA tidak memilih pair, arah, entry, SL, TP, lot,
atau lifecycle management.

## Hard confirmation gate

`WAIT_FOR_CONFIRMATION` hanya selesai ketika kedua tahap berikut terpenuhi:

1. struktur H1 sudah confirmed oleh candle yang closed; dan
2. candle M15 sudah closed, melakukan structural break, lalu menunjukkan
   acceptance atau failed-reclaim/retest.

Satu rejection candle atau H1 yang baru mulai melemah tidak cukup. Kondisi itu
harus tetap `NO_TRADE_CONTEXT_UNRESOLVED` dan tidak boleh menjadi SignalJSON
yang executable.

## Execution proof contract

Setiap final directional SignalJSON wajib membawa `strategy_5scr` yang mengikat:

- pair dan lifecycle hasil Pressure;
- hasil Context Resolution, allowed/selected/blocked playbook;
- H4 structural TP1 dan target room;
- arah H1, status closed candle, dan confirmation timestamp;
- M15 structural break plus acceptance atau failed-reclaim/retest;
- M1 current box dan fill;
- structural SL sebagai satu-satunya basis sizing Risk Engine;
- model, versi, frozen status, confirmation policy, dan authority chain.

Proof yang belum lengkap menghasilkan `DEFER`. Proof yang kontradiktif,
playbook terblokir, level berubah, atau M1 terinvalidasi menghasilkan `BLOCK`.
Promosi command mengulang validasi dan mengikat proof dengan SHA-256 ke signed
command, sehingga bridge/EA tidak perlu dan tidak boleh menghitung strategi.

## Locked validation record

| Metric | 5-S Final benchmark | 5S-CR Final |
| --- | ---: | ---: |
| Executed trades | 18 | **17** |
| Win | 16 | **16** |
| Loss | 2 | **1** |
| Win rate | 88.9% | **94.1%** |
| Net | +30.54R | **+31.54R** |
| Profit factor | 16.27 | **32.54** |
| Expectancy | +1.70R | **+1.86R/trade** |

Campaign record: 14 independent campaigns, 13 wins, 1 loss, 92.9% campaign
win rate. Coverage: 11 of 19 pairs and 517 of 580 logs (89.1%). This is not
out-of-sample evidence.

Three production child/add-on trades—GBPCAD, AUDJPY, and CADJPY—use `0.5R` in
the production-risk simulation. Full-risk net is `+31.54R`; production-risk
adjusted net is approximately `+28.01R`.

## Locked classification examples

- First CHFJPY SELL: `NO_TRADE_CONTEXT_UNRESOLVED`; H1 was not closed-confirmed
  and an isolated rejection candle did not satisfy the M15 gate.
- Second CHFJPY SELL: valid; closed-confirmed bearish H1, M15 support break and
  acceptance, retracement fill, valid target room; recorded `+1.87R`.
- NZDCHF BUY: `VALID_STRATEGY_LOSS`, `-1R`, with planned `3.03R`. Context
  Resolution must not remove a valid loss after observing its outcome.

## Rollout constraint

This contract is safe to deploy as a fail-closed SHADOW barrier. It is not an
authorization to enable live trading. OOS replay, MetaEditor compilation,
deterministic shadow correlation, demo execution, reconciliation, kill-switch,
and a symbol-limited live canary remain mandatory.
