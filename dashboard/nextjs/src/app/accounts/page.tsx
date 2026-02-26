"use client";

// ============================================================
// TUYUL FX Wolf-15 — Accounts Page (/accounts)
// Shows all prop-firm accounts with risk snapshots
// ============================================================

import { useAccounts, useRiskSnapshot } from "@/lib/api";
import type { Account } from "@/types";

function AccountCard({ account }: { account: Account }) {
  const { data: snap } = useRiskSnapshot(account.account_id);

  const pnlColor = (account.equity - account.balance) >= 0 ? "var(--green)" : "var(--red)";
  const maxDrawdownPct =
    snap && typeof snap === "object" && "max_drawdown_pct" in snap
      ? (snap as { max_drawdown_pct?: number }).max_drawdown_pct
      : undefined;

  const dailyDrawdownPct =
    snap && typeof snap === "object" && "daily_drawdown_pct" in snap
      ? (snap as { daily_drawdown_pct?: number }).daily_drawdown_pct
      : undefined;

  return (
    <div style={{
      background: "var(--bg-card)",
      border: "1px solid var(--border)",
      borderRadius: 8,
      padding: "1.25rem",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <span style={{ fontFamily: "var(--font-display)", fontSize: "1.1rem", color: "var(--accent)" }}>
          {account.label || account.account_id}
        </span>
        {account.prop_firm && (
          <span style={{
            fontSize: "0.7rem",
            padding: "2px 8px",
            borderRadius: 4,
            background: "var(--accent)",
            color: "var(--bg-base)",
            fontWeight: 700,
          }}>
            {account.prop_firm}
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem", fontSize: "0.85rem" }}>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Balance</span>
          <p style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>${account.balance.toLocaleString()}</p>
        </div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Equity</span>
          <p style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: pnlColor }}>
            ${account.equity.toLocaleString()}
          </p>
        </div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Daily DD</span>
          <p style={{ fontFamily: "var(--font-mono)" }}>{dailyDrawdownPct?.toFixed(2) ?? "—"}%</p>
        </div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Max DD</span>
          <p style={{ fontFamily: "var(--font-mono)" }}>{maxDrawdownPct?.toFixed(2) ?? "—"}%</p>
        </div>
      </div>

      {snap && !snap.can_trade && (
        <p style={{ color: "var(--red)", fontSize: "0.8rem", marginTop: "0.75rem" }}>
          ⚠ Trading blocked: {snap.block_reason ?? "risk limit reached"}
        </p>
      )}
    </div>
  );
}

export default function AccountsPage() {
  const { data: accounts, isLoading } = useAccounts();

  return (
    <div style={{ padding: "2rem" }}>
      <h1 style={{ color: "var(--accent)", fontFamily: "var(--font-display)", fontSize: "1.5rem", marginBottom: "1.5rem" }}>
        ◉ ACCOUNTS
      </h1>

      {isLoading && <p style={{ color: "var(--text-muted)" }}>Loading accounts…</p>}

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
        gap: "1rem",
      }}>
        {(accounts ?? []).map((a) => (
          <AccountCard key={a.account_id} account={a} />
        ))}
      </div>

      {!isLoading && (accounts ?? []).length === 0 && (
        <p style={{ color: "var(--text-muted)", textAlign: "center", marginTop: "3rem" }}>
          No accounts configured
        </p>
      )}
    </div>
  );
}
