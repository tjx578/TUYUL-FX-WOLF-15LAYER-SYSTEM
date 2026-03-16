"use client";

// ============================================================
// TUYUL FX Wolf-15 — Navigation Authority (PR-1)
// Blueprint: 3-tier nav + foldable advanced section + admin
// Single source of truth — no competing navigators.
// ============================================================

import Link from "next/link";
import clsx from "clsx";
import { usePathname } from "next/navigation";
import { useState } from "react";
import AccountSwitcher from "./AccountSwitcher";
import { useAuthStore } from "@/store/useAuthStore";
import { hasRole } from "@/lib/auth";
import type { UserRole } from "@/contracts/auth";
import { useActiveTrades, useHealth } from "@/lib/api";
import { useMemo } from "react";

// ── Icon ──────────────────────────────────────────────────────

function Icon({ d, size = 14 }: { d: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, opacity: 0.9 }}
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width={10}
      height={10}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{
        flexShrink: 0,
        transition: "transform 0.2s ease",
        transform: open ? "rotate(180deg)" : "rotate(0deg)",
        opacity: 0.5,
      }}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

// ── Icon paths ────────────────────────────────────────────────

const ICONS: Record<string, string> = {
  // Tier-1: COMMAND
  "/": "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z",
  "/trades/signals": "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  "/trades": "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  "/risk": "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  // Tier-2: OPERATIONS
  "/accounts": "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z",
  "/ea-manager": "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17H3a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2h-2",
  "/prop-firm": "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
  "/news": "M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zM9 7h6M9 11h6M9 15h4",
  "/journal": "M4 6h16M4 10h16M4 14h8",
  // Tier-3: CONTROL
  "/settings": "M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z",
  // Analytics & Engineering (advanced/foldable)
  "/pipeline": "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  "/probability": "M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-2-2 2 2 0 00-2 2v7h-4v-7a6 6 0 016-6zM2 9h4v12H2z",
  "/prices": "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  "/cockpit": "M12 2a10 10 0 110 20A10 10 0 0112 2zm0 0v10m0 0l4-4m-4 4l-4-4",
  "/signals": "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
  // Admin
  "/audit": "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
  "/architecture-audit": "M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2",
};

// ── Nav model ─────────────────────────────────────────────────

type NavRole = "viewer" | "operator" | "risk_admin" | "config_admin" | "approver";

type NavItem = {
  href: string;
  label: string;
  roles?: readonly NavRole[];
};

// Tier-1: Live operator pages — must be reachable in 1 click at all times
const TIER1_COMMAND: NavItem[] = [
  { href: "/", label: "Command Center" },
  { href: "/trades/signals", label: "Signal Board" },
  { href: "/trades", label: "Trade Desk" },
  { href: "/risk", label: "Risk Command" },
];

// Tier-2: Operational context — important but not every-minute
const TIER2_OPERATIONS: NavItem[] = [
  { href: "/accounts", label: "Capital Accounts" },
  { href: "/ea-manager", label: "Agent Control" },
  { href: "/prop-firm", label: "Compliance Hub" },
  { href: "/news", label: "Market Events" },
  { href: "/journal", label: "Operator Journal" },
];

// Tier-3: Control plane
const TIER3_CONTROL: NavItem[] = [
  { href: "/settings", label: "System Constitution" },
];

// Advanced section (foldable) — analytics, engineering, deep diagnosis
const ADVANCED_ITEMS: NavItem[] = [
  { href: "/pipeline", label: "Pipeline Monitor" },
  { href: "/probability", label: "Probability Monitor" },
  { href: "/prices", label: "Price Feed Monitor" },
  { href: "/cockpit", label: "Supervisory Cockpit" },
  { href: "/signals", label: "Signal Explorer" },
];

// Admin only
const ADMIN_ITEMS: NavItem[] = [
  { href: "/audit", label: "Audit Console", roles: ["risk_admin", "config_admin", "approver"] },
  { href: "/architecture-audit", label: "Arch Audit", roles: ["risk_admin", "config_admin", "approver"] },
];

// ── SystemPulse ───────────────────────────────────────────────

function SystemPulse() {
  const { data: health, isLoading } = useHealth();
  const isOk = health?.status === "ok";

  if (isLoading) {
    return (
      <div className="sidebar-status" style={{ gap: 6 }}>
        <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--text-muted)", display: "inline-block" }} />
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em" }}>
          CHECKING…
        </span>
      </div>
    );
  }

  return (
    <div className="sidebar-status">
      <span
        aria-hidden="true"
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: isOk ? "var(--green)" : "var(--red)",
          display: "inline-block",
          flexShrink: 0,
          animation: isOk ? "pulse-dot 1.5s ease-in-out infinite" : "none",
        }}
      />
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: isOk ? "var(--green)" : "var(--red)", letterSpacing: "0.08em", fontWeight: 700 }}>
        {isOk ? "BACKEND ONLINE" : "BACKEND OFFLINE"}
      </span>
      {health?.version && (
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 8, color: "var(--text-faint)" }}>
          v{health.version}
        </span>
      )}
    </div>
  );
}

// ── NavSection ────────────────────────────────────────────────

function NavSection({
  label,
  items,
  pathname,
  tradeCount,
  user,
}: {
  label: string;
  items: NavItem[];
  pathname: string;
  tradeCount: number;
  user: { role?: UserRole; email?: string } | null;
}) {
  const visible = items.filter(
    (item) => !item.roles || hasRole(user?.role, item.roles)
  );
  if (visible.length === 0) return null;

  return (
    <div className="mb-1">
      <div className="sidebar-section-label">{label}</div>
      {visible.map((item) => {
        const active =
          item.href === "/"
            ? pathname === "/"
            : pathname === item.href || pathname.startsWith(item.href + "/");
        const iconPath = ICONS[item.href] ?? ICONS["/"];
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={clsx("sidebar-link", active && "sidebar-link--active")}
          >
            <Icon d={iconPath} size={14} />
            <span style={{ flex: 1 }}>{item.label}</span>
            {item.href === "/trades" && tradeCount > 0 && (
              <span className="sidebar-badge-count" aria-label={`${tradeCount} active trades`}>
                {tradeCount > 99 ? "99+" : tradeCount}
              </span>
            )}
            {item.href === "/trades/signals" && tradeCount > 0 && (
              <span
                className="sidebar-badge-count"
                aria-label={`${tradeCount} active signals`}
                style={{ background: "var(--accent)", color: "var(--bg-primary)" }}
              >
                {tradeCount > 99 ? "99+" : tradeCount}
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}

// ── AdvancedSection (foldable) ────────────────────────────────

function AdvancedSection({
  pathname,
  user,
}: {
  pathname: string;
  user: { role?: UserRole; email?: string } | null;
}) {
  // Auto-open if current path is inside advanced section
  const isInsideAdvanced = ADVANCED_ITEMS.some(
    (item) => pathname === item.href || pathname.startsWith(item.href + "/")
  );
  const [open, setOpen] = useState(isInsideAdvanced);

  return (
    <div className="mb-1">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          width: "100%",
          padding: "5px 10px",
          background: "none",
          border: "none",
          cursor: "pointer",
          borderRadius: "var(--radius-sm)",
          transition: "background 0.15s",
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.03)"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 8,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "var(--text-faint)",
            flex: 1,
            textAlign: "left",
          }}
        >
          ANALYTICS &amp; ENGINEERING
        </span>
        <ChevronIcon open={open} />
      </button>

      {open && (
        <div>
          {ADVANCED_ITEMS.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(item.href + "/");
            const iconPath = ICONS[item.href] ?? ICONS["/"];
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={clsx("sidebar-link", active && "sidebar-link--active")}
                style={{ opacity: 0.8 }}
              >
                <Icon d={iconPath} size={13} />
                <span style={{ flex: 1 }}>{item.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────

export default function Sidebar() {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const { data: activeTrades } = useActiveTrades();

  const tradeCount = useMemo(() => {
    if (!activeTrades) return 0;
    if (Array.isArray(activeTrades)) return activeTrades.length;
    return (activeTrades as { trades?: unknown[] }).trades?.length ?? 0;
  }, [activeTrades]);

  const visibleAdminItems = ADMIN_ITEMS.filter(
    (item) => !item.roles || hasRole(user?.role, item.roles)
  );

  return (
    <aside className="sidebar-root" aria-label="Primary navigation">
      {/* ── Logo ── */}
      <div className="sidebar-logo">
        <div className="sidebar-logo-mark" aria-hidden="true">W</div>
        <div>
          <div className="sidebar-logo-name">TUYUL FX</div>
          <div className="sidebar-logo-sub">WOLF-15 TERMINAL</div>
        </div>
      </div>

      {/* ── System pulse ── */}
      <SystemPulse />

      {/* ── Account switcher ── */}
      <div style={{ padding: "8px 12px", borderBottom: "1px solid rgba(255,255,255,0.04)", flexShrink: 0 }}>
        <AccountSwitcher />
      </div>

      {/* ── Navigation ── */}
      <nav className="sidebar-nav" role="navigation" aria-label="Main menu">

        {/* Tier-1 */}
        <NavSection
          label="COMMAND"
          items={TIER1_COMMAND}
          pathname={pathname}
          tradeCount={tradeCount}
          user={user}
        />

        {/* Tier-2 */}
        <NavSection
          label="OPERATIONS"
          items={TIER2_OPERATIONS}
          pathname={pathname}
          tradeCount={tradeCount}
          user={user}
        />

        {/* Tier-3 */}
        <NavSection
          label="CONTROL"
          items={TIER3_CONTROL}
          pathname={pathname}
          tradeCount={tradeCount}
          user={user}
        />

        {/* Advanced / foldable */}
        <AdvancedSection pathname={pathname} user={user} />

        {/* Admin */}
        {visibleAdminItems.length > 0 && (
          <div className="mb-1">
            <div className="sidebar-section-label">ADMIN</div>
            {visibleAdminItems.map((item) => {
              const active =
                pathname === item.href || pathname.startsWith(item.href + "/");
              const iconPath = ICONS[item.href] ?? ICONS["/"];
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={clsx("sidebar-link", active && "sidebar-link--active")}
                  style={{ opacity: 0.75 }}
                >
                  <Icon d={iconPath} size={13} />
                  <span style={{ flex: 1 }}>{item.label}</span>
                </Link>
              );
            })}
          </div>
        )}

      </nav>

      {/* ── Footer ── */}
      <div className="sidebar-footer">
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: "50%",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-default)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 10,
              fontWeight: 700,
              color: "var(--accent)",
              fontFamily: "var(--font-display)",
              flexShrink: 0,
            }}
            aria-hidden="true"
          >
            {user?.email?.[0]?.toUpperCase() ?? "U"}
          </div>
          <div style={{ overflow: "hidden", flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {user?.email ?? "Unknown"}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.06em" }}>
              {(user?.role ?? "viewer").toUpperCase()}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
