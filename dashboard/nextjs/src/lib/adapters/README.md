# Adapters

Transisi dari mock ke backend nyata.

## Pola kerja

1. Hooks saat ini membaca dari `src/lib/mock/*.ts`
2. Ganti hook agar membaca dari adapter
3. Adapter panggil backend nyata via `src/lib/api/*`
4. Action `alert()` di hooks diganti command POST

## File yang akan dibuat

- `signals.adapter.ts` → GET /api/v1/signals
- `trades.adapter.ts` → GET /api/v1/trades
- `accounts.adapter.ts` → GET /api/v1/accounts
- `risk.adapter.ts` → GET /api/v1/risk
- `news.adapter.ts` → GET /api/v1/news
- `journal.adapter.ts` → GET /api/v1/journal

## Prioritas integrasi

1. signals (pintu masuk)
2. trades (lifecycle)
3. accounts + risk (keterikatan sistem)
4. news + journal (pelengkap operasi)
