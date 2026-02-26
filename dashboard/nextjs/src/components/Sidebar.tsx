"use client";

// ============================================================
// TUYUL FX Wolf-15 — Sidebar Navigation
// ============================================================

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useHealth, useActiveTrades } from "@/lib/api";
import { TimezoneDisplay } from "./TimezoneDisplay";

interface NavItem {
  href: string;
  label: string;
  icon: string;
  badge?: () => string | number | null;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/",                  label: "OVERVIEW",     icon: "⬡" },
  { href: "/trades/signals",    label: "SIGNALS",      icon: "◈" },
  { href: "/trades",            label: "TRADES",       icon: "◆" },
  { href: "/risk",              label: "RISK",         icon: "⬡" },
  { href: "/accounts",          label: "ACCOUNTS",     icon: "◉" },
  { href: "/journal",           label: "JOURNAL",      icon: "◧" },
  { href: "/probability",       label: "PROBABILITY",  icon: "◫" },
  { href: "/prices",            label: "PRICES",       icon: "◭" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { data: health } = useHealth();
  const { data: trades } = useActiveTrades();

  const activeCount = trades?.length ?? 0;
  const isHealthy = health?.status === "ok";

  return (
    <aside
      style={{
        width: "var(--sidebar-w)",
        minHeight: "100vh",
        background: "var(--bg-panel)",
        borderRight: "1px solid var(--bg-border)",
        display: "flex",
        flexDirection: "column",
        position: "fixed",
        top: 0,
        left: 0,
        zIndex: 50,
      }}
    >
      {/* ── Logo ── */}
      <div
        style={{
          padding: "20px 16px 16px",
          borderBottom: "1px solid var(--bg-border)",
        }}
      >
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 700,
            fontSize: 18,
            letterSpacing: "0.08em",
            color: "var(--accent)",
          }}
        >
          🐺 TUYUL FX
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
            marginTop: 2,
            letterSpacing: "0.12em",
          }}
        >
          WOLF-15 PIPELINE
        </div>
      </div>

      {/* ── System status ── */}
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--bg-border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: isHealthy ? "var(--green)" : "var(--red)",
            boxShadow: isHealthy
              ? "0 0 6px var(--green)"
              : "0 0 6px var(--red)",
            animation: isHealthy
              ? "pulse-dot 1.5s ease-in-out infinite"
              : "none",
          }}
        />
        <span
          style={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: isHealthy ? "var(--green)" : "var(--red)",
            letterSpacing: "0.06em",
          }}
        >
          {health?.status?.toUpperCase() ?? "CONNECTING"}
        </span>
        {activeCount > 0 && (
          <span
            className="badge badge-gold"
            style={{ marginLeft: "auto", fontSize: 10 }}
          >
            {activeCount} OPEN
          </span>
        )}
      </div>

      {/* ── Nav links ── */}
      <nav style={{ flex: 1, padding: "8px 0" }}>
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "9px 16px",
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: "0.06em",
                textDecoration: "none",
                color: isActive ? "var(--accent)" : "var(--text-secondary)",
                background: isActive ? "var(--accent-glow)" : "transparent",
                borderLeft: isActive
                  ? "2px solid var(--accent)"
                  : "2px solid transparent",
                transition: "all 0.12s ease",
              }}
            >
              <span
                style={{
                  fontSize: 15,
                  opacity: isActive ? 1 : 0.5,
                }}
              >
                {item.icon}
              </span>
              {item.label}
              {item.href === "/trades" && activeCount > 0 && (
                <span
                  style={{
                    marginLeft: "auto",
                    minWidth: 18,
                    height: 18,
                    borderRadius: "50%",
                    background: "var(--accent)",
                    color: "#000",
                    fontSize: 10,
                    fontWeight: 700,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {activeCount}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* ── Clock ── */}
      <div
        style={{
          padding: "12px 16px",
          borderTop: "1px solid var(--bg-border)",
        }}
      >
        <TimezoneDisplay compact />
      </div>
    </aside>
  );
}
