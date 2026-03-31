# Architecture Manifest — Dashboard V2 (Flat 6 Pages)

Updated: March 2026.

## Route map

| Route | Role | Status |
| --- | --- | --- |
| `/` | Dashboard command center (status, signals, trades, risk, alerts) | Active |
| `/signals` | Signal board with Active / History / Pipeline tabs | Active |
| `/trades` | Trade desk with Active / History / Journal / Exposure tabs | Active |
| `/risk` | Risk and compliance with Overview / Accounts / Compliance tabs | Active |
| `/market` | Market intelligence with Chart / Calendar / News / Watchlist tabs | Active |
| `/settings` | Settings and operations with role-gated Audit tab | Active |

## Structure

- Single route group: `app/(main)`.
- Sidebar is flat with 6 items only.
- Admin functions are inline and role-gated inside `/settings`.

## Removed as non-relevant for V2

- Legacy dashboard domain: `features/command/*`.
- Legacy cockpit alias domain: `features/cockpit/*`.
- Legacy command-center aggregator hook: `hooks/useCommandCenterState.ts`.

## Guardrails

- Do not create new route groups for control/admin.
- Keep user workflows in-page with tabs before adding new routes.
- Keep real-time hooks centralized on V2 pages.
