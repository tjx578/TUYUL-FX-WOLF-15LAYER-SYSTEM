/**
 * widgets/ — Shell & Composition Layer
 *
 * Architecture rules (CUTOVER-PHASE-9):
 * - Widgets are cross-domain UI containers (shells, sidebars, nav, status bars).
 * - Widgets must NOT hold business logic — delegate to features/*.
 * - Widgets MAY import from: shared/*, @/components/* (legacy reusable).
 * - Widgets must NOT import route-specific code from app/*.
 * - Widgets must NOT import domain logic from features/* directly.
 *
 * Planned modules:
 * - DashboardShell (migrate from @/components/layout/DashboardShell)
 * - SidebarNav (migrate from @/components/layout/Sidebar*)
 * - StatusBar / SystemHealth strip
 */
export { };
