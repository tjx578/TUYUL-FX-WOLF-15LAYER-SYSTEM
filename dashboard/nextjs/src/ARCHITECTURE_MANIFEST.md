# Architecture Manifest — CUTOVER PHASE 9

> Single source of truth for folder ownership, import rules, and migration status.
> Generated: 2026-03-26

---

## Folder Ownership

| Folder | Role | Import Rules |
| ------ | ---- | ------------ |
| `app/(control)/*/page.tsx` | **Route entry** — thin delegation only | MAY import: `features/*/components/*Screen` only |
| `app/(control)/*/layout.tsx` | **Route metadata** — title, description | No business imports |
| `app/(root)/*` | **DEPRECATED** — legacy routes, still needed for unmigrated pages | See migration table below |
| `features/*/` | **Domain logic owner** — screens, hooks, api, model | MAY import: same-feature `./`, `shared/*`, legacy `@/components/*`, `@/lib/*` |
| `shared/` | **Cross-domain infra** — api utils, contracts, hooks, ui | MUST NOT import: `app/*`, `features/*` |
| `widgets/` | **Shell & composition** — sidebar, nav, status bars | MAY import: `shared/*`, `@/components/*`. MUST NOT import: `features/*` domain logic |
| `@/components/*` | **Legacy reusable** — progressively migrate to `features/` or `shared/ui/` | Allowed as import source until replaced |
| `@/hooks/*` | **Legacy hooks** — progressively migrate to `features/*/hooks/` | Allowed as import source until replaced |
| `@/lib/*` | **Legacy utilities** — API hooks, formatters | Allowed as import source until replaced |
| `@/schema/*` | **Legacy schemas** — progressively migrate to `features/*/model/` | Allowed as import source until replaced |

---

## Route Migration Status

### Fully migrated to `(control)` ✅

| Domain | Route | Screen | Status |
| ------ | ----- | ------ | ------ |
| Command Center | `(control)/page.tsx` | `features/command/CommandCenterScreen` | ✅ Live |
| Signals | `(control)/signals/page.tsx` | `features/signals/SignalBoardScreen` | ✅ Live |
| Trades | `(control)/trades/page.tsx` | `features/trades/TradesScreen` | ✅ Live |
| Accounts | `(control)/accounts/page.tsx` | `features/accounts/AccountsScreen` | ✅ Live |
| Journal | `(control)/journal/page.tsx` | `features/journal/JournalScreen` | ✅ Live |
| News | `(control)/news/page.tsx` | `features/news/NewsScreen` | ✅ Live |

### Still in `(root)` — not yet migrated

| Route | Status | Notes |
| ----- | ------ | ----- |
| `(root)/cockpit/page.tsx` | 🟡 Active | Operational dashboard |
| `(root)/pipeline/page.tsx` | 🟡 Active | Pipeline monitor |
| `(root)/risk/page.tsx` | 🟡 Active | Risk dashboard |
| `(root)/prop-firm/page.tsx` | 🟡 Active | Prop firm manager |
| `(root)/ea-manager/page.tsx` | 🟡 Active | EA manager |
| `(root)/settings/page.tsx` | 🟡 Active | Settings |
| `(root)/charts/page.tsx` | 🟡 Active | Chart viewer |
| `(root)/probability/page.tsx` | 🟡 Active | Probability calculator |
| `(root)/prices/page.tsx` | 🟡 Active | Live prices |
| `(root)/calendar/page.tsx` | 🟡 Active | Calendar view |
| `(root)/architecture-audit/page.tsx` | 🟡 Active | Dev tool |
| `(root)/dashboard/page.tsx` | 🔴 Deprecated | Already a redirect |

### Legacy redirect stubs

| Route                              | Redirects to | Safe to delete when                          |
| ---------------------------------- | ------------ | -------------------------------------------- |
| `(root)/trades/signals/page.tsx`   | `/signals`   | No external links point to `/trades/signals` |

### Deprecated layouts (no sub-pages, metadata moved to `(control)`)

| Path | Action |
| ---- | ------ |
| `(root)/accounts/layout.tsx` | Safe to delete now — no sub-pages |
| `(root)/journal/layout.tsx` | Safe to delete now — no sub-pages |
| `(root)/news/layout.tsx` | Safe to delete now — no sub-pages |
| `(root)/trades/layout.tsx` | Keep until `trades/signals/` redirect is removed |

---

## Import Violation Inventory

These imports in feature screens violate the target architecture. They work today but
should be progressively migrated to feature-local or `shared/` modules.

### TradesScreen.tsx — 3 violations

```text
@/components/trade-desk          → move to features/trades/components/ or shared/ui/
@/hooks/useTradeDeskHooks        → move to features/trades/hooks/
@/schema/tradeDeskSchema         → move to features/trades/model/
```

### AccountsScreen.tsx — 2 violations

```text
@/components/AccountDetailDrawer → move to features/accounts/components/
@/lib/api (useCapitalDeployment) → move to features/accounts/api/
```

### JournalScreen.tsx — 2 violations

```text
@/components/JournalMetrics      → move to features/journal/components/
@/lib/api (useJournal*)          → move to features/journal/api/
```

### NewsScreen.tsx — 1 violation

```text
@/lib/api (useCalendar*)         → move to features/news/api/
```

### SignalBoardScreen.tsx — 1 violation

```text
@/lib/api (useCapitalDeployment) → cross-domain (accounts), acceptable via shared/api/
```

### Acceptable legacy imports (no action needed yet)

These are reusable UI components with no domain logic:

```text
@/components/feedback/PageComplianceBanner   → shared/ui candidate
@/components/OrchestratorReadinessStrip      → shared/ui candidate
@/components/feedback/RouteErrorView         → shared/ui candidate
@/components/AccountReadinessBadge           → shared/ui candidate
@/components/CreateAccountModal              → features/accounts candidate
@/lib/formatters                             → shared/utils candidate
```

---

## Import Boundary Rules (enforced by lint script)

### Rule 1: Route pages must be thin

`app/(control)/*/page.tsx` — only `@/features/*/components/*Screen` imports allowed.

### Rule 2: Features don't import routes

`features/**` — must NOT import from `app/**`.

### Rule 3: Shared is neutral

`shared/**` — must NOT import from `app/**` or `features/**`.

### Rule 4: Widgets are logic-free

`widgets/**` — must NOT import from `features/**` domain hooks/api.

---

## Next Steps (Phase 10+)

1. **Migrate trade-desk components** into `features/trades/components/`
2. **Migrate journal/account UI** into respective `features/*/components/`
3. **Move `@/lib/api` hooks** to `features/*/api/` (domain-specific) or `shared/api/` (cross-domain)
4. **Populate `widgets/`** with DashboardShell, SidebarNav etc.
5. **Delete orphaned `(root)` domain layouts** (accounts, journal, news)
6. **Migrate remaining `(root)` pages** to `(control)` or dedicated route groups
