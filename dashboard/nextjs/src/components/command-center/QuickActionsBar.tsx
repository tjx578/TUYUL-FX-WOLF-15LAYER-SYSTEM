"use client";

// ============================================================
// TUYUL FX Wolf-15 — QuickActionsBar
// PRD: Command Center — quick action links + account readiness
// ============================================================

import Link from "next/link";
import type { Account } from "@/types";
import type { AccountRiskSnapshot } from "@/lib/api";

interface QuickActionsBarProps {
  accounts: Account[];
  snapshotList: AccountRiskSnapshot[];
}

const ACTIONS = [
  {
    label: "SIGNAL BOARD",
    href: "/trades/signals",
    primary: true,
    description: "View all actionable signals",
  },
  {
    label: "RISK COMMAND",
    href: "/risk",
    primary: false,
    description: "Drawdown & circuit breakers",
  },
  {
    label: "TRADE DESK",
    href: "/trades",
    primary: false,
    description: "Active positions",
  },
  {
    label: "PIPELINE",
    href: "/pipeline",
    primary: false,
    description: "L1–L12 analysis DAG",
  },
  {
    label: "JOURNAL",
    href: "/journal",
    primary: false,
    description: "Trade log & metrics",
  },
] as const;

export default function QuickActionsBar({ accounts, snapshotList }: QuickActionsBarProps) {
  return (
    <div
      className="panel"
      style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}
    >
      {/* Header */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.12em",
          color: "var(--text-muted)",
        }}
      >
        QUICK ACTIONS
      </span>

      {/* Action buttons */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {ACTIONS.map((action) => (
          <Link
            key={action.href}
            href={action.href}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 11px",
              borderRadius: "var(--radius-sm)",
              border: action.primary
                ? "1px solid var(--border-accent)"
                : "1px solid var(--border-default)",
              background: action.primary ? "rgba(26,110,255,0.06)" : "transparent",
              color: action.primary ? "var(--accent)" : "var(--text-secondary)",
              fontSize: 11,
              fontWeight: action.primary ? 700 : 500,
              fontFamily: "var(--font-mono)",
              textDecoration: "none",
              letterSpacing: "0.04em",
              transition: "background 0.1s",
            }}
          >
            <span>{action.label}</span>
            <span
              style={{
                fontSize: 9,
                color: "var(--text-faint)",
                fontWeight: 400,
                fontFamily: "var(--font-body)",
                letterSpacing: 0,
              }}
            >
              {action.description}
            </span>
          </Link>
        ))}
      </div>

      {/* Account readiness */}
      {accounts.length > 0 && (
        <>
          <div style={{ borderTop: "1px solid var(--border-default)" }} />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.12em",
              color: "var(--text-muted)",
            }}
          >
            ACCOUNT READINESS
          </span>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {accounts.slice(0, 4).map((acc) => {
              const snap = snapshotList.find((s) => s.account_id === acc.account_id);
              const ready = !snap || (snap.status === "SAFE" && !snap.circuit_breaker);
              return (
                <div
                  key={acc.account_id}
                  style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      background: ready ? "var(--green)" : "var(--red)",
                      boxShadow: ready ? "0 0 6px rgba(0,230,118,0.5)" : "none",
                      flexShrink: 0,
                    }}
                    aria-hidden="true"
                  />
                  <span
                    style={{
                      flex: 1,
                      color: "var(--text-secondary)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 10,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {acc.account_name ?? acc.account_id}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 9,
                      color: ready ? "var(--green)" : "var(--red)",
                      fontWeight: 700,
                    }}
                  >
                    {ready ? "READY" : snap?.status ?? "BLOCKED"}
                  </span>
                </div>
              );
            })}
            {accounts.length > 4 && (
              <Link
                href="/accounts"
                style={{
                  fontSize: 10,
                  color: "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                  textDecoration: "none",
                }}
              >
                +{accounts.length - 4} more → ACCOUNTS
              </Link>
            )}
          </div>
        </>
      )}
    </div>
  );
}
