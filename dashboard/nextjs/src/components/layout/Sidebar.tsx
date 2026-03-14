"use client";

// ============================================================
// TUYUL FX Wolf-15 — Production Sidebar
// Features: nav icons, active state, system health pulse,
//           account switcher, live trade count badge
// ============================================================

import Link from "next/link";
import clsx from "clsx";
import { usePathname } from "next/navigation";
import AccountSwitcher from "./AccountSwitcher";
import { useAuthStore } from "@/store/useAuthStore";
import { hasRole } from "@/lib/auth";
import { useActiveTrades, useHealth } from "@/lib/api";
import { useMemo } from "react";

// ── Icon components (pure SVG, no external dep) ──────────────

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
      style={{ flexShrink: 0, opacity: 0.85 }}
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}

const ICONS: Record<string, string> = {
  "/":           "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z",
  "/pipeline":   "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  "/trades":     "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  "/accounts":   "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z",
  "/risk":       "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  "/news":       "M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zM9 7h6M9 11h6M9 15h4",
  "/journal":    "M4 6h16M4 10h16M4 14h8",
  "/signals":    "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  "/cockpit":    "M12 2a10 10 0 110 20A10 10 0 0112 2zm0 0v10m0 0l4-4m-4 4l-4-4",
  "/probability":"M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-2-2 2 2 0 00-2 2v7h-4v-7a6 6 0 016-6zM2 9h4v12H2z",
  "/prices":     "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  "/settings":   "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z",
  "/ea-manager": "M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18",
  "/prop-firm":  "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  "/calendar":   "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  "/audit":      "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
};

type NavItem = {
  href: string;
  label: string;
  roles?: readonly ("viewer" | "operator" | "risk_admin" | "config_admin" | "approver")[];
  section?: string;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/",           label: "Overview",    section: "CORE" },
  { href: "/cockpit",    label: "Cockpit",     section: "CORE" },
  { href: "/pipeline",   label: "Pipeline",    section: "CORE" },
  { href: "/trades",     label: "Trades",      section: "EXECUTION" },
  { href: "/signals",    label: "Signals",     section: "EXECUTION" },
  { href: "/accounts",   label: "Accounts",    section: "EXECUTION" },
  { href: "/risk",       label: "Risk",        section: "EXECUTION" },
  { href: "/prop-firm",  label: "Prop Firm",   section: "EXECUTION" },
  { href: "/news",       label: "News",        section: "ANALYSIS" },
  { href: "/journal",    label: "Journal",     section: "ANALYSIS" },
  { href: "/probability",label: "Probability", section: "ANALYSIS" },
  { href: "/prices",     label: "Prices",      section: "ANALYSIS" },
  { href: "/ea-manager", label: "EA Manager",  section: "SYSTEM"  },
  { href: "/settings",   label: "Settings",    section: "SYSTEM"  },
  {
    href: "/audit",
    label: "Audit",
    section: "SYSTEM",
    roles: ["risk_admin", "config_admin", "approver"],
  },
];

function SystemPulse() {
  const { data: health, isLoading } = useHealth();
  const isOk = health?.status === "ok";

  if (isLoading) {
    return (
      <div className="sidebar-status" style={{ gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--text-muted)", display: "inline-block" }} />
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em" }}>
          CHECKING…
        </span>
      </div>
    );
  }

  return (
    <div className="sidebar-status">
      <span
        className={isOk ? "live-dot" : ""}
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

export default function Sidebar() {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const { data: activeTrades } = useActiveTrades();

  const tradeCount = useMemo(() => {
    if (!activeTrades) return 0;
    if (Array.isArray(activeTrades)) return activeTrades.length;
    return (activeTrades as { trades?: unknown[] }).trades?.length ?? 0;
  }, [activeTrades]);

  const filteredNav = NAV_ITEMS.filter(
    (item) => !item.roles || hasRole(user?.role, item.roles)
  );

  // Group by section
  const sections = filteredNav.reduce<Record<string, NavItem[]>>((acc, item) => {
    const s = item.section ?? "CORE";
    if (!acc[s]) acc[s] = [];
    acc[s].push(item);
    return acc;
  }, {});

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
        {Object.entries(sections).map(([section, items]) => (
          <div key={section} className="mb-1">
            <div className="sidebar-section-label">{section}</div>
            {items.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
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
                </Link>
              );
            })}
          </div>
        ))}
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
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)", truncate: true, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
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
