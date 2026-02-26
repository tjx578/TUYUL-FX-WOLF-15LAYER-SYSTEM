"use client";

// ============================================================
// TUYUL FX Wolf-15 — Account Manager Page (/accounts)
// ============================================================

import { useState } from "react";
import { useAccounts } from "@/lib/api";
import { AccountCard, CreateAccountForm } from "@/components/AccountPanel";

export default function AccountsPage() {
  const { data: accounts, isLoading, mutate } = useAccounts();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = accounts?.find((a) => a.account_id === selectedId);

  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              letterSpacing: "0.04em",
              color: "var(--text-primary)",
              margin: 0,
            }}
          >
            ACCOUNT MANAGER
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Multi-account management with prop firm tracking
          </p>
        </div>

        <button
          className="btn btn-primary"
          style={{ marginLeft: "auto", fontSize: 12 }}
          onClick={() => setShowCreate(true)}
        >
          + NEW ACCOUNT
        </button>
      </div>

      {/* ── Main grid ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: selected ? "1fr 420px" : "1fr",
          gap: 20,
          alignItems: "start",
        }}
      >
        {/* ── Account cards ── */}
        <div>
          {isLoading ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Loading accounts...
            </div>
          ) : (accounts ?? []).length === 0 ? (
            <div
              style={{
                padding: "48px 0",
                textAlign: "center",
                fontSize: 12,
                color: "var(--text-muted)",
                background: "var(--bg-panel)",
                borderRadius: 8,
              }}
            >
              No accounts yet. Click "NEW ACCOUNT" to add one.
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
                gap: 14,
              }}
            >
              {accounts!.map((a) => (
                <AccountCard
                  key={a.account_id}
                  account={a}
                  selected={selectedId === a.account_id}
                  onClick={() =>
                    setSelectedId(
                      selectedId === a.account_id ? null : a.account_id
                    )
                  }
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Detail panel ── */}
        {selected && (
          <div className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: "0.08em",
                color: "var(--accent)",
              }}
            >
              {selected.account_name}
            </div>

            <table>
              <tbody>
                {[
                  { k: "Account ID",    v: selected.account_id.slice(0, 16) + "..." },
                  { k: "Broker",        v: selected.broker },
                  { k: "Currency",      v: selected.currency },
                  { k: "Balance",       v: `$${selected.balance?.toLocaleString()}` },
                  { k: "Equity",        v: `$${selected.equity?.toLocaleString()}` },
                  { k: "Equity High",   v: `$${selected.equity_high?.toLocaleString()}` },
                  { k: "Prop Firm",     v: selected.prop_firm ? (selected.prop_firm_code ?? "YES") : "NO" },
                  { k: "Daily DD Limit",v: `${selected.max_daily_dd_percent}%` },
                  { k: "Total DD Limit",v: `${selected.max_total_dd_percent}%` },
                  { k: "Max Trades",    v: selected.max_concurrent_trades },
                  { k: "Open Trades",   v: selected.open_trades },
                  { k: "Risk State",    v: selected.risk_state },
                ].map(({ k, v }) => (
                  <tr key={k}>
                    <td style={{ color: "var(--text-muted)", fontSize: 11 }}>{k}</td>
                    <td
                      className="num"
                      style={{ color: "var(--text-primary)", fontSize: 12, textAlign: "right" }}
                    >
                      {String(v)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <button
              className="btn btn-ghost"
              style={{ fontSize: 11 }}
              onClick={() => setSelectedId(null)}
            >
              CLOSE
            </button>
          </div>
        )}
      </div>

      {/* ── Create form overlay ── */}
      {showCreate && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
          onClick={() => setShowCreate(false)}
        >
          <div onClick={(e) => e.stopPropagation()}>
            <CreateAccountForm
              onCreated={() => {
                setShowCreate(false);
                mutate();
              }}
              onCancel={() => setShowCreate(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
