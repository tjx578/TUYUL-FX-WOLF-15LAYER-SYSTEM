# Mapping V3 → Next.js Hybrid per Domain

## 1. Shell

- `index.html` sidebar → `src/components/layout/SidebarV2.tsx`
- `index.html` topbar → `src/components/layout/Topbar.tsx`
- wrapper utama → `src/components/layout/DashboardShell.tsx`
- route shell → `src/app/(main)/layout.tsx`

## 2. Styles

- `styles.css` → `src/shared/styles/tokens.css` + `src/app/globals.css`
- gold theme via CSS custom properties

## 3. Domain pages

### Signals

- `src/app/(main)/signals/page.tsx` (existing, uses features/signals)
- `src/hooks/useSignalsData.ts` (hybrid hook, reads mock)
- `src/lib/mock/signals.ts`

### Trades

- `src/app/(main)/trades/page.tsx` (existing, uses features/trades)
- `src/hooks/useTradesData.ts`
- `src/lib/mock/trades.ts`

### Accounts

- `src/app/(main)/accounts/page.tsx` (NEW)
- `src/components/accounts/AccountsPage.tsx`
- `src/hooks/useAccountsData.ts`
- `src/lib/mock/accounts.ts`

### Risk Monitor

- `src/app/(main)/risk/page.tsx` (existing, uses features/risk)
- `src/hooks/useRiskData.ts`
- `src/lib/mock/risk.ts`

### News

- `src/app/(main)/news/page.tsx` (NEW)
- `src/components/news/NewsPage.tsx`
- `src/hooks/useNewsData.ts`
- `src/lib/mock/news.ts`

### Journal

- `src/app/(main)/journal/page.tsx` (NEW)
- `src/components/journal/JournalPage.tsx`
- `src/hooks/useJournalData.ts`
- `src/lib/mock/journal.ts`

### Utilities

- `src/app/(main)/utilities/page.tsx` (NEW)
- `src/components/utilities/UtilitiesPage.tsx`
- `src/hooks/useUtilitiesData.ts`
- `src/lib/mock/utilities.ts`

## 4. Mock layer

- `data/*.json` → `src/lib/mock/*.ts`

## 5. Hook layer

- `app.js` runtime → `src/hooks/use*Data.ts`

## 6. Adapter plan (transition to real backend)

1. Mock dari `src/lib/mock/*.ts`
2. Ganti hooks agar baca `src/lib/adapters/*`
3. Adapter panggil backend nyata di `src/lib/api/*`
4. Action `alert()` diganti command POST

## 7. Yang belum dipecah

- Modal Take Signal
- Filters granular per domain
- Websocket live state
- Auth per-domain
- Audit trail
- Command API real

Alasan: sebaiknya dipasang setelah shell domain stabil.
