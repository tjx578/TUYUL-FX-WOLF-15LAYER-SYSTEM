"use client";

// ============================================================
// TUYUL FX Wolf-15 — Sidebar Navigation (Institutional Rebuild)
// ============================================================

import Link from "next/link";
import clsx from "clsx";
import { usePathname } from "next/navigation";
import { useHealth, useActiveTrades } from "@/lib/api";
import { TimezoneDisplay } from "./TimezoneDisplay";

interface NavItem {
  href: string;
  label: string;
  section?: string;
}

// ── Nav groups for visual hierarchy ──
const NAV_ITEMS: NavItem[] = [
  // Core
  { href: "/",              label: "Overview",      section: "core" },
  { href: "/trades/signals",label: "Signal Queue",   section: "core" },
  { href: "/trades",        label: "Active Trades",  section: "core" },
  { href: "/accounts",      label: "Accounts",       section: "core" },
  // Risk
  { href: "/risk",          label: "Risk Monitor",   section: "risk" },
  { href: "/prop-firm",     label: "Prop Firm",       section: "risk" },
  // Ops
  { href: "/journal",       label: "Journal",        section: "ops" },
  { href: "/ea-manager",    label: "EA Manager",      section: "ops" },
  { href: "/calendar",      label: "News Calendar",  section: "ops" },
  { href: "/settings",      label: "Settings",       section: "ops" },
];

const SECTION_LABELS: Record<string, string> = {
  core: "TRADING",
  risk: "RISK & PROP",
  ops:  "OPERATIONS",
};

export function Sidebar() {
  const pathname = usePathname();
  const { data: health } = useHealth();
  const { data: trades } = useActiveTrades();

  const activeCount = trades?.length ?? 0;
  const isHealthy = health?.status === "ok";

  // Group nav items by section, preserving order
  const sections = ["core", "risk", "ops"] as const;

  return (
    <aside className="sidebar-root">

      {/* ── Logo ── */}
      <div className="sidebar-logo">
        <div className="sidebar-logo-mark" />
        <div>
          <div className="sidebar-logo-name">TUYUL FX</div>
          <div className="sidebar-logo-sub">WOLF-15 TERMINAL</div>
        </div>
      </div>

      {/* ── System Status Bar ── */}
      <div className="sidebar-status">
        <span
          className="live-dot"
          style={{
            background: isHealthy ? "var(--green)" : "var(--red)",
            boxShadow: isHealthy ? "0 0 6px var(--green)" : "0 0 6px var(--red)",
            animation: isHealthy ? "pulse-dot 1.5s ease-in-out infinite" : "none",
          }}
        />
        <span className="sidebar-status-text" style={{ color: isHealthy ? "var(--green)" : "var(--red)" }}>
          {health?.status?.toUpperCase() ?? "CONNECTING"}
        </span>
        {activeCount > 0 && (
          <span className="badge badge-gold" style={{ marginLeft: "auto", fontSize: 10 }}>
            {activeCount} OPEN
          </span>
        )}
      </div>

      {/* ── Nav ── */}
      <nav className="sidebar-nav">
        {sections.map((section) => {
          const items = NAV_ITEMS.filter((i) => i.section === section);
          return (
            <div key={section} className="sidebar-section">
              <div className="sidebar-section-label">{SECTION_LABELS[section]}</div>
              {items.map((item) => {
                const isActive =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx("sidebar-link", isActive && "sidebar-link--active")}
                  >
                    <span className="sidebar-link-dot" />
                    {item.label}
                    {item.href === "/trades" && activeCount > 0 && (
                      <span className="sidebar-badge-count">{activeCount}</span>
                    )}
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      {/* ── Footer ── */}
      <div className="sidebar-footer">
        <TimezoneDisplay compact />
      </div>

    </aside>
  );
}
