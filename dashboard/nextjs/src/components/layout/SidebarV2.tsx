"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useSystemStore } from "@/store/useSystemStore";

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Dashboard",
    href: "/",
    icon: (
      <svg
        className="w-[18px] h-[18px]"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
        <polyline points="13 2 13 9 20 9" />
      </svg>
    ),
  },
  {
    label: "Signals",
    href: "/signals",
    icon: (
      <svg
        className="w-[18px] h-[18px]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 20.5a10 10 0 0 1-18.8 4.2" />
      </svg>
    ),
  },
  {
    label: "Trades",
    href: "/trades",
    icon: (
      <svg
        className="w-[18px] h-[18px]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
        <polyline points="17 6 23 6 23 12" />
      </svg>
    ),
  },
  {
    label: "Risk",
    href: "/risk",
    icon: (
      <svg
        className="w-[18px] h-[18px]"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
      </svg>
    ),
  },
  {
    label: "Market",
    href: "/market",
    icon: (
      <svg
        className="w-[18px] h-[18px]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 6v6l4 2" />
      </svg>
    ),
  },
  {
    label: "Settings",
    href: "/settings",
    icon: (
      <svg
        className="w-[18px] h-[18px]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1v6m0 6v6M4.22 4.22l4.24 4.24m3.08 3.08l4.24 4.24M1 12h6m6 0h6m-15.78 7.78l4.24-4.24m3.08-3.08l4.24-4.24" />
      </svg>
    ),
  },
];

export function SidebarV2() {
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(true);
  const [mounted, setMounted] = useState(false);
  const mode = useSystemStore((s) => s.mode);
  const isLive = mode === "NORMAL" || mode === "SSE";

  // Set CSS variable and handle hydration
  useEffect(() => {
    setMounted(true);
    updateSidebarWidth();
  }, []);

  useEffect(() => {
    updateSidebarWidth();
  }, [isCollapsed]);

  const updateSidebarWidth = () => {
    const width = isCollapsed ? "56px" : "220px";
    document.documentElement.style.setProperty("--sidebar-w", width);
  };

  if (!mounted) {
    return null;
  }

  const isActive = (href: string): boolean => {
    if (href === "/") {
      return pathname === "/";
    }
    return pathname.startsWith(href);
  };

  return (
    <aside
      className="fixed left-0 top-0 h-screen bg-[#080c14] border-r border-[var(--border)] transition-all duration-200 ease-out flex flex-col z-50"
      style={{ width: isCollapsed ? "56px" : "220px" }}
    >
      {/* Header / Logo */}
      <div className="flex items-center justify-center h-16 border-b border-[var(--border)] flex-shrink-0">
        <div className="text-center">
          {isCollapsed ? (
            <div className="text-lg font-bold text-[var(--accent)]">T</div>
          ) : (
            <div className="text-sm font-bold text-[var(--accent)] whitespace-nowrap px-2">
              TUYUL FX
            </div>
          )}
        </div>
      </div>

      {/* Navigation Items */}
      <nav className="flex-1 flex flex-col gap-1 p-2 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`
                relative flex items-center gap-3 h-10 px-3 rounded-lg
                transition-all duration-200 ease-out
                ${
                  active
                    ? "bg-[rgba(59,130,246,0.12)] border-l-4 border-l-[var(--accent)] text-[var(--accent)]"
                    : "text-[#8fa3af] hover:bg-[var(--bg-elevated)]"
                }
              `}
              title={isCollapsed ? item.label : undefined}
            >
              <div className="flex-shrink-0 flex items-center justify-center">
                {item.icon}
              </div>

              {!isCollapsed && (
                <span className="text-xs font-medium whitespace-nowrap truncate">
                  {item.label}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* System Status */}
      <div className="border-t border-[var(--border)] p-2 flex-shrink-0">
        <div
          className="flex items-center gap-2 h-10 px-3 rounded-lg bg-[var(--bg-elevated)] justify-center hover:bg-opacity-80 transition-all duration-200"
          title={isLive ? "System Live" : "System Offline"}
        >
          <div
            className={`w-2 h-2 rounded-full flex-shrink-0 ${
              isLive ? "bg-green-500" : "bg-red-500"
            }`}
          />
          {!isCollapsed && (
            <span className="text-xs font-medium text-[#8fa3af] whitespace-nowrap">
              {isLive ? "LIVE" : "OFFLINE"}
            </span>
          )}
        </div>
      </div>

      {/* Collapse Toggle Button */}
      <div className="border-t border-[var(--border)] p-2 flex-shrink-0">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="w-full h-10 flex items-center justify-center rounded-lg text-[#8fa3af] hover:bg-[var(--bg-elevated)] transition-all duration-200"
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <svg
            className={`w-4 h-4 transition-transform duration-200 ${
              isCollapsed ? "rotate-180" : ""
            }`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>
    </aside>
  );
}
