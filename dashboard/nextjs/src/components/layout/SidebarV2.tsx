"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useSystemStore } from "@/store/useSystemStore";
import { useAuthStore } from "@/store/useAuthStore";

/* ─── Navigation structure matching HTML prototype ───────── */

interface NavGroup {
  title: string;
  items: { label: string; href: string; gold?: boolean }[];
}

const NAV: NavGroup[] = [
  {
    title: "Main",
    items: [
      { label: "Home", href: "/" },
      { label: "Signal Queue", href: "/signals" },
      { label: "Trades", href: "/trades" },
      { label: "Accounts", href: "/risk" },
    ],
  },
  {
    title: "Tools",
    items: [
      { label: "Tools", href: "/market", gold: true },
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
        background: "#000",
        borderRight: "1px solid #171a20",
        display: "flex",
        flexDirection: "column",
        padding: "18px 14px",
        gap: 14,
        zIndex: 50,
      }}
    >
      {/* Brand */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontWeight: 800, letterSpacing: "0.04em", fontSize: 18, color: "#e8eaed" }}>
          WOLF15
        </div>
        <div style={{ color: "#717886", fontSize: 11, fontWeight: 600, letterSpacing: "0.12em", marginTop: 2 }}>
          HTML CONTROL ROOM
        </div>
      </div>

      {/* Primary action */}
      <button
        style={{
          background: "#d8b35d",
          color: "#000",
          border: "none",
          borderRadius: 10,
          padding: "12px 14px",
          fontWeight: 700,
          cursor: "pointer",
          fontSize: 14,
        }}
      >
        + New Signal Review
      </button>

      {/* Nav groups */}
      {NAV.map((group) => (
        <div key={group.title}>
          <div
            style={{
              color: "#717886",
              fontSize: 12,
              textTransform: "uppercase",
              margin: "8px 6px 2px",
              letterSpacing: "0.08em",
            }}
          >
            {group.title}
          </div>
          <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {group.items.map((item) => {
              const active = isActive(item.href);
              const isGold = item.gold && active;

              return (
                <Link
                  key={item.href + item.label}
                  href={item.href}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "11px 12px",
                    color: "#e8eaed",
                    textDecoration: "none",
                    borderRadius: 10,
                    margin: "2px 0",
                    fontSize: 14,
                    fontWeight: active ? 600 : 400,
                    background: isGold
                      ? "rgba(216,179,93,0.16)"
                      : active
                        ? "#171a20"
                        : "transparent",
                    outline: isGold
                      ? "1px solid rgba(216,179,93,0.35)"
                      : active
                        ? "1px solid #222734"
                        : "none",
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      ))}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid #171a20",
          paddingTop: 12,
          color: "#9aa3b2",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div>
          <div style={{ fontWeight: 700, color: "#fff", fontSize: 14 }}>
            {user?.email?.split("@")[0] ?? "Operator"}
          </div>
          <div style={{ color: "#9aa3b2", fontSize: 12 }}>
            {(user?.role ?? "operator").charAt(0).toUpperCase() + (user?.role ?? "operator").slice(1)}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: isLive ? "#22c55e" : "#ef4444",
            }}
          />
          <span style={{ fontSize: 11, color: "#717886" }}>
            {isLive ? "LIVE" : "OFF"}
          </span>
        </div>
      </div>
    </aside>
  );
}
