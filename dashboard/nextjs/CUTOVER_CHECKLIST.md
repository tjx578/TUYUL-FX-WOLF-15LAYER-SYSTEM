# Patch 8 — Cutover Checklist: `(root)` → `(control)`

> Generated: 2026-03-26
> Status: IN PROGRESS — Route group migration active

---

## A. Route Layer — `app/(control)/` Pages

- [x] `app/(control)/layout.tsx` — Active (auth-gated DashboardShell)
- [x] `app/(control)/page.tsx` — Active → `CommandCenterScreen`
- [x] `app/(control)/signals/page.tsx` — Active → `SignalBoardScreen`
- [x] `app/(control)/trades/page.tsx` — Active → `TradesScreen`
- [x] `app/(control)/accounts/page.tsx` — Active → `AccountsScreen`
- [x] `app/(control)/journal/page.tsx` — Active → `JournalScreen`
- [x] `app/(control)/news/page.tsx` — Active → `NewsScreen`

---

## B. Feature Screens — Source of Truth

- [x] `features/signals/components/SignalBoardScreen.tsx` — Source of truth
- [x] `features/trades/components/TradesScreen.tsx` — Source of truth
- [x] `features/accounts/components/AccountsScreen.tsx` — Source of truth
- [x] `features/journal/components/JournalScreen.tsx` — Source of truth
- [x] `features/news/components/NewsScreen.tsx` — Source of truth (NEW)
- [x] `features/command/components/CommandCenterScreen.tsx` — Source of truth (NEW)

---

## C. Legacy Wrapper Redirects — `app/(root)/`

- [x] `app/(root)/page.tsx` — Wrapper → `CommandCenterScreen` (will redirect after cutover)
- [x] `app/(root)/trades/page.tsx` — Redirect → `/trades`
- [x] `app/(root)/accounts/page.tsx` — Redirect → `/accounts`
- [x] `app/(root)/journal/page.tsx` — Redirect → `/journal`
- [x] `app/(root)/news/page.tsx` — Redirect → `/news`
- [x] `app/(root)/trades/signals/page.tsx` — Redirect → `/signals`

---

## D. Files to DELETE After Full Cutover

Once all bookmarks/links are updated and no traffic routes through `(root)`:

```text
app/(root)/trades/page.tsx
app/(root)/accounts/page.tsx
app/(root)/journal/page.tsx
app/(root)/news/page.tsx
app/(root)/trades/signals/page.tsx
app/(root)/trades/signals/layout.tsx
app/(root)/trades/signals/error.tsx
app/(root)/page.tsx
app/(root)/layout.tsx          (last — only after ALL root routes retired)
app/(root)/error.tsx
```

Subdirectories still ACTIVE in `(root)` (NOT migrated yet):

```text
app/(root)/charts/
app/(root)/cockpit/
app/(root)/dashboard/
app/(root)/ea-manager/
app/(root)/pipeline/
app/(root)/prices/
app/(root)/probability/
app/(root)/prop-firm/
app/(root)/risk/
app/(root)/settings/
app/(root)/architecture-audit/
app/(root)/calendar/
```

These remain under `(root)` until their respective feature screens are built.

---

## E. Shared Contracts (Cross-Domain)

- [x] `shared/contracts/lifecycleNavigation.ts` — Used by signals, trades, journal, accounts
- [x] `shared/hooks/useLifecycleNavigationContext.ts` — Used by feature screens
- [x] `shared/api/invalidation.ts` — Source helper for cache refresh
- [x] `shared/api/queryKeys.ts` — Centralized query keys
- [x] `shared/ui/toastBus.ts` — Used by take-signal flow

---

## F. Import Cleanup Status

- [x] `(root)/trades/page.tsx` — All imports removed (redirect only)
- [x] `(root)/accounts/page.tsx` — All imports removed (redirect only)
- [x] `(root)/journal/page.tsx` — All imports removed (redirect only)
- [x] `(root)/news/page.tsx` — All imports removed (redirect only)
- [x] `(root)/trades/signals/page.tsx` — All imports removed (redirect only)
- [x] `(root)/page.tsx` — Imports reduced to single feature screen import
- [ ] Sidebar navigation links — Update `/trades/signals` → `/signals` (when ready)

---

## G. Production Behavior Verification

- [ ] `/signals` route renders `SignalBoardScreen` correctly
- [ ] `/trades` route renders `TradesScreen` correctly
- [ ] `/accounts` route renders `AccountsScreen` correctly
- [ ] `/journal` route renders `JournalScreen` correctly
- [ ] `/news` route renders `NewsScreen` correctly
- [ ] `/` (home) renders `CommandCenterScreen` correctly
- [ ] Take-signal success triggers cross-domain invalidation
- [ ] Success/failure toasts display properly
- [ ] Route transitions between domains work
- [ ] Trades receive bridge context from signals
- [ ] Journal receives focus context
- [ ] Accounts receive focus context

---

## H. When is Cutover "Official"?

1. ✅ `(control)` route pages are active and serving users
2. ✅ `features/*/components/*Screen.tsx` are the source of truth
3. ✅ Legacy `(root)` pages are redirect wrappers only
4. ⬜ Sidebar links point to `(control)` routes
5. ⬜ No traffic through `(root)` routes (monitor for 1 week)
6. ⬜ Delete legacy files (housekeeping)
