"use client";

// ============================================================
// TUYUL FX Wolf-15 — Accounts Page (/accounts)
// Features: AccountCard grid, risk indicators, create modal,
//           prop-firm badge, equity/balance display
// ============================================================

import { useState } from "react";
import { useAccounts, useAccountsRiskSnapshot } from "@/lib/api";
import { AccountCard, CreateAccountForm } from "@/components/AccountPanel";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import type { Account } from "@/types";

// ── Portfolio summary ─────────────────────────────────────────

function PortfolioKpi({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      className="card"
      style={{ display: "flex", flexDirection: "column", gap: 4, padding: "12px 15px" }}
    >
      <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "var(--text-muted)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────

export default function AccountsPage() {
  const { data: accounts, isLoading, isError, mutate } = useAccounts() as ReturnType<typeof useAccounts> & { mutate?: () => void };
  const { data: riskSnapshots } = useAccountsRiskSnapshot();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Portfolio totals
  const totalBalance = (accounts ?? []).reduce((s, a) => s + (a.balance ?? 0), 0);
  const totalEquity  = (accounts ?? []).reduce((s, a) => s + (a.equity ?? 0), 0);
  const criticalCount = (accounts ?? []).filter((a) => a.risk_state === "CRITICAL").length;
  const propCount     = (accounts ?? []).filter((a) => a.prop_firm).length;

  const handleCreated = () => {
    setShowCreate(false);
    if (typeof mutate === "function") mutate();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="accounts" />

      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 800,
              letterSpacing: "0.06em",
              color: "var(--text-primary)",
              margin: 0,
              fontFamily: "var(--font-display)",
            }}
          >
            ACCOUNTS
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Multi-account portfolio — drawdown tracking + risk state
          </p>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <button
            className="btn btn-primary"
            onClick={() => setShowCreate(true)}
            aria-label="Add new account"
          >
            + ADD ACCOUNT
          </button>
        </div>
      </div>

      {/* ── Portfolio KPIs ── */}
      {!isLoading && !isError && (accounts ?? []).length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12 }}>
          <PortfolioKpi
            label="TOTAL BALANCE"
            value={`$${totalBalance.toLocaleString()}`}
            color="var(--text-primary)"
          />
          <PortfolioKpi
            label="TOTAL EQUITY"
            value={`$${totalEquity.toLocaleString()}`}
            color={totalEquity >= totalBalance ? "var(--green)" : "var(--red)"}
          />
          <PortfolioKpi
            label="ACCOUNTS"
            value={String((accounts ?? []).length)}
            color="var(--blue)"
          />
          <PortfolioKpi
            label="PROP FIRMS"
            value={`${propCount} / ${(accounts ?? []).length}`}
            color={propCount > 0 ? "var(--accent)" : "var(--text-muted)"}
          />
        </div>
      )}

      {/* ── Risk alert banner ── */}
      {criticalCount > 0 && (
        <div
          role="alert"
          className="panel"
          style={{
            padding: "10px 14px",
            borderColor: "var(--border-danger)",
            background: "var(--red-glow)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontSize: 12,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "var(--red)",
              display: "inline-block",
              animation: "pulse-dot 1.2s ease-in-out infinite",
              flexShrink: 0,
            }}
          />
          <strong style={{ color: "var(--red)" }}>{criticalCount} account{criticalCount > 1 ? "s" : ""} in CRITICAL state</strong>
          <span style={{ color: "var(--text-muted)" }}>— review drawdown limits immediately.</span>
        </div>
      )}

      {/* ── Loading state ── */}
      {isLoading && (
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}
          aria-busy="true"
          aria-label="Loading accounts"
        >
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton card" style={{ height: 180 }} />
          ))}
        </div>
      )}

      {/* ── Error state ── */}
      {isError && !isLoading && (
        <div
          role="alert"
          className="panel"
          style={{ padding: "28px 20px", textAlign: "center" }}
        >
          <div style={{ fontSize: 13, color: "var(--red)", marginBottom: 6 }}>
            Failed to load accounts
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Check the backend connection. Endpoint: /api/v1/accounts
          </div>
        </div>
      )}

      {/* ── Empty state ── */}
      {!isLoading && !isError && (accounts ?? []).length === 0 && (
        <div
          className="panel"
          style={{ padding: "40px 20px", textAlign: "center" }}
        >
          <div style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 8 }}>
            No accounts found
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 16 }}>
            Add your first trading account to start tracking.
          </div>
          <button
            className="btn btn-primary"
            onClick={() => setShowCreate(true)}
          >
            + ADD FIRST ACCOUNT
          </button>
        </div>
      )}

      {/* ── Account grid ── */}
      {!isLoading && !isError && (accounts ?? []).length > 0 && (
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}
          role="list"
          aria-label="Account cards"
        >
          {(accounts ?? []).map((account: Account) => {
            const snap = riskSnapshots?.find((s) => s.account_id === account.account_id);
            return (
              <div key={account.account_id} role="listitem">
                <AccountCard
                  account={account}
                  selected={selectedId === account.account_id}
                  onClick={() =>
                    setSelectedId((prev) =>
                      prev === account.account_id ? null : account.account_id
                    )
                  }
                />
                {/* Expanded risk snapshot */}
                {selectedId === account.account_id && snap && (
                  <div
                    className="animate-fade-in panel"
                    style={{ marginTop: 8, padding: "12px 14px" }}
                  >
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginBottom: 10 }}>
                      RISK SNAPSHOT
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                      {[
                        { label: "DAILY DD",    value: `${snap.daily_dd_percent?.toFixed(2)}%`, color: snap.daily_dd_percent > 3 ? "var(--red)" : "var(--green)" },
                        { label: "TOTAL DD",    value: `${snap.total_dd_percent?.toFixed(2)}%`, color: snap.total_dd_percent > 5 ? "var(--red)" : "var(--text-primary)" },
                        { label: "OPEN RISK",   value: `${snap.open_risk_percent?.toFixed(2)}%`, color: "var(--text-primary)" },
                        { label: "OPEN TRADES", value: String(snap.open_trades),                 color: "var(--blue)" },
                        { label: "STATUS",      value: snap.status,                              color: snap.status === "SAFE" ? "var(--green)" : snap.status === "WARNING" ? "var(--yellow)" : "var(--red)" },
                        { label: "CIRCUIT BR.", value: snap.circuit_breaker ? "OPEN" : "CLOSED", color: snap.circuit_breaker ? "var(--red)" : "var(--green)" },
                      ].map(({ label, value, color }) => (
                        <div key={label}>
                          <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 2 }}>{label}</div>
                          <div className="num" style={{ fontSize: 12, fontWeight: 700, color }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Create account modal ── */}
      {showCreate && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Create account"
          style={{
            position: "fixed",
            inset: 0,
            background: "var(--bg-overlay)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
            backdropFilter: "blur(4px)",
          }}
          onClick={() => setShowCreate(false)}
        >
          <div
            className="animate-fade-in"
            onClick={(e) => e.stopPropagation()}
          >
            <CreateAccountForm
              onCreated={handleCreated}
              onCancel={() => setShowCreate(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
