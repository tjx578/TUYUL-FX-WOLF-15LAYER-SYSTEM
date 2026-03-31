"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useSystemStore } from "@/store/useSystemStore";
import { useAuthStore } from "@/store/useAuthStore";

/* ─── SVG Icon Components ─────────────────────────────────── */

function IconHome() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

function IconSignals() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

function IconTrades() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="1" x2="12" y2="23" />
      <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  );
}

function IconAccounts() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function IconRisk() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function IconNews() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2" />
      <line x1="10" y1="6" x2="18" y2="6" />
      <line x1="10" y1="10" x2="18" y2="10" />
      <line x1="10" y1="14" x2="14" y2="14" />
    </svg>
  );
}

function IconJournal() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  );
}

function IconUtilities() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
      <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
    </svg>
  );
}

function IconMarket() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function IconLeaderboard() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
      <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
      <path d="M4 22h16" />
      <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20 17 22" />
      <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
    </svg>
  );
}

/* ─── Icons mapping ───────────────────────────────────────── */
const ICONS: Record<string, React.FC> = {
  Home: IconHome,
  Signals: IconSignals,
  Trades: IconTrades,
  Accounts: IconAccounts,
  "Risk Monitor": IconRisk,
  News: IconNews,
  Journal: IconJournal,
  Utilities: IconUtilities,
  "Market Tools": IconMarket,
  Settings: IconSettings,
  Leaderboard: IconLeaderboard,
};

/* ─── Navigation structure ────────────────────────────────── */

interface NavGroup {
  title: string;
  items: { label: string; href: string; badge?: string }[];
}

const NAV: NavGroup[] = [
  {
    title: "",
    items: [
      { label: "Home", href: "/" },
      { label: "Signals", href: "/signals" },
      { label: "Trades", href: "/trades" },
      { label: "Accounts", href: "/accounts" },
      { label: "Risk Monitor", href: "/risk" },
    ],
  },
  {
    title: "Market",
    items: [
      { label: "News", href: "/news" },
      { label: "Market Tools", href: "/market" },
      { label: "Leaderboard", href: "/journal" },
    ],
  },
  {
    title: "System",
    items: [
      { label: "Utilities", href: "/utilities" },
      { label: "Settings", href: "/settings" },
    ],
  },
];

export function SidebarV2() {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const mode = useSystemStore((s) => s.mode);
  const isLive = mode === "NORMAL" || mode === "SSE";
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    setMounted(true);
    document.documentElement.style.setProperty("--sidebar-w", "240px");
  }, []);

  if (!mounted) return null;

  const isActive = (href: string): boolean => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <aside
      style={{
        width: 240,
        position: "fixed",
        top: 0,
        left: 0,
        height: "100vh",
        background: "#0c0d0f",
        borderRight: "1px solid rgba(255,255,255,0.06)",
        display: "flex",
        flexDirection: "column",
        padding: "0",
        zIndex: 50,
        fontFamily: "var(--font-body, Inter, sans-serif)",
      }}
    >
      {/* Brand Header */}
      <div
        style={{
          padding: "20px 20px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: "linear-gradient(135deg, #C8FF1A, #7acc00)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 900,
              fontSize: 14,
              color: "#0A0B0D",
              letterSpacing: "-0.02em",
            }}
          >
            W15
          </div>
          <div>
            <div
              style={{
                fontWeight: 700,
                fontSize: 15,
                color: "#F5F7FA",
                letterSpacing: "-0.01em",
                lineHeight: 1.2,
              }}
            >
              TUYUL FX
            </div>
            <div
              style={{
                color: "#717886",
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: "0.04em",
              }}
            >
              Wolf-15 System
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 10px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {NAV.map((group, gi) => (
          <div key={gi}>
            {group.title && (
              <div
                style={{
                  color: "#505662",
                  fontSize: 10,
                  textTransform: "uppercase",
                  letterSpacing: "0.12em",
                  fontWeight: 600,
                  padding: "14px 12px 6px",
                }}
              >
                {group.title}
              </div>
            )}
            <nav style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              {group.items.map((item) => {
                const active = isActive(item.href);
                const Icon = ICONS[item.label];
                return (
                  <Link
                    key={item.href + item.label}
                    href={item.href}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 12px",
                      color: active ? "#C8FF1A" : "#9ca3af",
                      textDecoration: "none",
                      borderRadius: 8,
                      fontSize: 13.5,
                      fontWeight: active ? 600 : 450,
                      background: active
                        ? "rgba(200, 255, 26, 0.08)"
                        : "transparent",
                      borderLeft: active
                        ? "3px solid #C8FF1A"
                        : "3px solid transparent",
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (!active) {
                        e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                        e.currentTarget.style.color = "#d1d5db";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!active) {
                        e.currentTarget.style.background = "transparent";
                        e.currentTarget.style.color = "#9ca3af";
                      }
                    }}
                  >
                    {Icon && <Icon />}
                    <span>{item.label}</span>
                    {item.badge && (
                      <span
                        style={{
                          marginLeft: "auto",
                          background: "#C8FF1A",
                          color: "#0A0B0D",
                          fontSize: 10,
                          fontWeight: 700,
                          padding: "2px 7px",
                          borderRadius: 999,
                        }}
                      >
                        {item.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </nav>
          </div>
        ))}
      </div>

      {/* Footer — User Info */}
      <div
        style={{
          borderTop: "1px solid rgba(255,255,255,0.06)",
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: "#1f2937",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 13,
            fontWeight: 700,
            color: "#C8FF1A",
          }}
        >
          {(user?.email?.charAt(0) ?? "O").toUpperCase()}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 600,
              color: "#e5e7eb",
              fontSize: 13,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {user?.email?.split("@")[0] ?? "Operator"}
          </div>
          <div style={{ color: "#6b7280", fontSize: 11 }}>
            {(user?.role ?? "operator").charAt(0).toUpperCase() + (user?.role ?? "operator").slice(1)}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <div
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: isLive ? "#22c55e" : "#ef4444",
              boxShadow: isLive ? "0 0 6px #22c55e" : "none",
            }}
          />
          <span style={{ fontSize: 10, color: "#6b7280", fontWeight: 600, letterSpacing: "0.05em" }}>
            {isLive ? "LIVE" : "OFF"}
          </span>
        </div>
      </div>
    </aside>
  );
}
