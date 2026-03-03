"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Tab = { href: string; label: string };

const TABS: Tab[] = [
  { href: "/", label: "OVERVIEW" },
  { href: "/signals", label: "SIGNALS" },
  { href: "/trades", label: "TRADE DESK" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href);
}

export default function NavTabs() {
  const pathname = usePathname();

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        padding: "10px 12px",
        borderRadius: 10,
        background: "var(--bg-card)",
        border: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      {TABS.map((t) => {
        const active = isActive(pathname, t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            style={{
              padding: "8px 10px",
              borderRadius: 8,
              textDecoration: "none",
              fontSize: 10,
              letterSpacing: "0.12em",
              fontWeight: 800,
              color: active ? "var(--text-primary)" : "var(--text-muted)",
              background: active ? "rgba(0,245,160,0.10)" : "transparent",
              border: active
                ? "1px solid rgba(0,245,160,0.25)"
                : "1px solid transparent",
            }}
          >
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}