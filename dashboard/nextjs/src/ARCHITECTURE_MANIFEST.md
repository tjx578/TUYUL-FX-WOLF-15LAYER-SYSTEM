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
| Risk | `(control)/risk/page.tsx` | `features/risk/RiskScreen` | ✅ Live |
| Settings | `(control)/settings/page.tsx` | `features/settings/SettingsScreen` | ✅ Live |
| Prop Firm | `(control)/prop-firm/page.tsx` | `features/prop-firm/PropFirmScreen` | ✅ Live |
| EA Manager | `(control)/ea-manager/page.tsx` | `features/agent-manager/AgentManagerScreen` | ✅ Live |
| Cockpit | `(control)/cockpit/page.tsx` | `features/cockpit/CockpitScreen` | ✅ Live |
| Analysis | `(control)/analysis/page.tsx` | `features/market-analysis/MarketAnalysisHubScreen` | ✅ Live |

### Legacy aliases only

| Route | Status | Notes |
| ----- | ------ | ----- |
| `(root)/calendar/page.tsx` | 🟢 Alias | Redirects to `/news` |
| `(root)/charts/page.tsx` | 🟢 Alias | Redirects to `/analysis?tab=charts` |
| `(root)/probability/page.tsx` | 🟢 Alias | Redirects to `/analysis?tab=probability` |
| `(root)/prices/page.tsx` | 🟢 Alias | Redirects to `/analysis?tab=prices` |

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

All import violations from the domain cutover (PR-005 through PR-009) have been resolved.
The deprecated compat shims (`@/components/trade-desk`, `@/hooks/useTradeDeskHooks`,
`@/schema/tradeDeskSchema`, `@/lib/api`, `@/components/EquityCurve`, `@/components/JournalMetrics`,
`@/components/RiskGauge`, `@/components/CreateAccountModal`, `@/components/AccountReadinessBadge`,
`@/components/AccountEligibilityPanel`, `@/components/AccountDetailDrawer`) were deleted in PR-013.

### Remaining deprecated paths (sunset 2026-06-01)

The agent-control → agent-manager migration is in progress. These files are all
consumed exclusively by `ea-manager/page.tsx` and will be removed once that page
is migrated to use `@/hooks/useAgentManagerState` + `@/components/agent-manager/` directly:

```text
@/hooks/useAgentControlState            → @/hooks/useAgentManagerState
@/components/agent-control/*            → @/components/agent-manager/*
@/shared/api/ea.api.ts (deprecated fns) → @/lib/agent-manager-api
@/types/index.ts (EAAgent, EALog, etc.) → @/types/agent-manager
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
