"use client";

// ============================================================
// TUYUL FX Wolf-15 — Capital Accounts Page (/accounts)
// Capital deployment view with readiness score, usable capital,
// eligibility flags, lock/compliance inheritance, account cards.
// ============================================================

import { useState } from "react";
import { useCapitalDeployment, useAccountsRiskSnapshot } from "@/lib/api";
import { AccountCard } from "@/components/AccountPanel";
import AccountReadinessBadge from "@/components/AccountReadinessBadge";
import AccountDetailDrawer from "@/components/AccountDetailDrawer";
import CreateAccountModal from "@/components/CreateAccountModal";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import type { Account } from "@/types";

// ── Portfolio Summary Strip ───────────────────────────────────

function PortfolioSummaryStrip({
  accounts,
  totalUsable,
  avgReadiness,
}: {
  accounts: Account[];
  totalUsable: number;
  avgReadiness: number;
}) {
  const totalBalance = accounts.reduce((s, a) => s + (a.balance ?? 0), 0);
  const totalEquity = accounts.reduce((s, a) => s + (a.equity ?? 0), 0);
  const propCount = accounts.filter((a) => a.prop_firm).length;
  const eaCount = accounts.filter((a) => a.data_source === "EA").length;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
      <KpiCard label="TOTAL BALANCE" value={`$${totalBalance.toLocaleString()}`} />
      <KpiCard
        label="TOTAL EQUITY"
        value={`$${totalEquity.toLocaleString()}`}
        color={totalEquity >= totalBalance ? "var(--green)" : "var(--red)"}
      />
      <KpiCard
        label="USABLE CAPITAL"
        value={`$${totalUsable.toLocaleString()}`}
        color="var(--green)"
      />
      <KpiCard
        label="AVG READINESS"
        value={`${Math.round(avgReadiness * 100)}%`}
        color={avgReadiness >= 0.7 ? "var(--green)" : avgReadiness >= 0.4 ? "var(--yellow)" : "var(--red)"}
      />
      <KpiCard label="ACCOUNTS" value={String(accounts.length)} color="var(--blue)" />
      <KpiCard
        label="PROP / EA"
        value={`${propCount} / ${eaCount}`}
        color={propCount > 0 ? "var(--accent, var(--yellow))" : "var(--text-muted)"}
      />
    </div>
  );
}

function KpiCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      className="card"
      style={{ display: "flex", flexDirection: "column", gap: 4, padding: "12px 15px" }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: "0.12em",
          color: "var(--text-muted)",
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{ fontSize: 18, fontWeight: 700, color: color ?? "var(--text-primary)" }}
      >
        {value}
      </div>
    </div>
  );
}

// ── Account Grid Card (enhanced) ─────────────────────────────

function AccountGridCard({
  account,
  riskSnap,
  onClick,
}: {
  account: Account;
  riskSnap?: { status: string; circuit_breaker: boolean };
  onClick: () => void;
}) {
  const readiness = account.readiness_score ?? 0;
  const usable = account.usable_capital ?? 0;

  return (
    <div
      role="listitem"
      tabIndex={0}
      className="card cursor-pointer transition-all duration-200 hover:border-[var(--blue)]"
      style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
      aria-label={`Account ${account.account_name}, ${account.broker}, balance $${account.balance?.toLocaleString()}`}
    >
      {/* Top row: name + readiness */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
            {account.account_name}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2, display: "flex", gap: 6, alignItems: "center" }}>
            <span>{account.broker}</span>
            <span>·</span>
            <span>{account.currency}</span>
            {account.data_source === "EA" && (
              <span
                style={{
                  fontSize: 8,
                  fontWeight: 700,
                  padding: "1px 4px",
                  borderRadius: 3,
                  background: "rgba(26, 110, 255, 0.08)",
                  color: "var(--blue)",
                }}
              >
                EA
              </span>
            )}
          </div>
        </div>
        <AccountReadinessBadge score={readiness} />
      </div>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
        <Stat label="BALANCE" value={`$${account.balance?.toLocaleString()}`} />
        <Stat label="EQUITY" value={`$${account.equity?.toLocaleString()}`} />
        <Stat
          label="USABLE CAPITAL"
          value={`$${usable.toLocaleString()}`}
          color="var(--green)"
        />
        <Stat
          label="OPEN"
          value={`${account.open_trades}/${account.max_concurrent_trades}`}
        />
      </div>

      {/* Bottom row: prop + locks */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {account.prop_firm && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 9999,
              background: "rgba(26, 110, 255, 0.07)",
              color: "var(--accent, var(--yellow))",
              border: "1px solid rgba(26, 110, 255, 0.12)",
            }}
          >
            {account.prop_firm_code?.toUpperCase() ?? "PROP"}
          </span>
        )}
        {riskSnap?.status === "CRITICAL" && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 9999,
              background: "rgba(255, 61, 87, 0.07)",
              color: "var(--red)",
              border: "1px solid rgba(255, 61, 87, 0.12)",
            }}
          >
            CRITICAL
          </span>
        )}
        {riskSnap?.status === "WARNING" && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 9999,
              background: "rgba(255, 215, 64, 0.07)",
              color: "var(--yellow)",
              border: "1px solid rgba(255, 215, 64, 0.12)",
            }}
          >
            WARNING
          </span>
        )}
        {(account.lock_reasons?.length ?? 0) > 0 && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 9999,
              background: "rgba(255, 61, 87, 0.03)",
              color: "var(--red)",
            }}
          >
            🔒 {account.lock_reasons?.length} lock{(account.lock_reasons?.length ?? 0) > 1 ? "s" : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  color = "var(--text-primary)",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: 2 }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 13, fontWeight: 600, color }}>
        {value}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────

export default function CapitalAccountsPage() {
  const {
    data: accounts,
    totalUsableCapital,
    avgReadinessScore,
    isLoading,
    isError,
    mutate,
  } = useCapitalDeployment();
  const { data: riskSnapshots } = useAccountsRiskSnapshot();
  const [showCreate, setShowCreate] = useState(false);
  const [drawerAccountId, setDrawerAccountId] = useState<string | null>(null);

  const criticalCount = (riskSnapshots ?? []).filter((s) => s.status === "CRITICAL").length;
  const drawerAccount = drawerAccountId
    ? accounts.find((a) => a.account_id === drawerAccountId) ?? null
    : null;

  const handleCreated = () => {
    setShowCreate(false);
    mutate();
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
            CAPITAL ACCOUNTS
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Capital deployment view — readiness, usable capital, lock state
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

      {/* ── Portfolio Summary Strip ── */}
      {!isLoading && !isError && accounts.length > 0 && (
        <PortfolioSummaryStrip
          accounts={accounts}
          totalUsable={totalUsableCapital}
          avgReadiness={avgReadinessScore}
        />
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
          <strong style={{ color: "var(--red)" }}>
            {criticalCount} account{criticalCount > 1 ? "s" : ""} in CRITICAL state
          </strong>
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
            <div key={i} className="skeleton card" style={{ height: 200 }} />
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
            Failed to load capital accounts
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Check the backend connection. Endpoint: /api/v1/accounts/capital-deployment
          </div>
        </div>
      )}

      {/* ── Empty state ── */}
      {!isLoading && !isError && accounts.length === 0 && (
        <div
          className="panel"
          style={{ padding: "40px 20px", textAlign: "center" }}
        >
          <div style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 8 }}>
            No capital accounts found
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 16 }}>
            Add your first trading account to start tracking capital deployment.
          </div>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            + ADD FIRST ACCOUNT
          </button>
        </div>
      )}

      {/* ── Account grid ── */}
      {!isLoading && !isError && accounts.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
            gap: 14,
          }}
          role="list"
          aria-label="Capital account cards"
        >
          {accounts.map((account: Account) => {
            const snap = riskSnapshots?.find((s) => s.account_id === account.account_id);
            return (
              <AccountGridCard
                key={account.account_id}
                account={account}
                riskSnap={snap}
                onClick={() => setDrawerAccountId(account.account_id)}
              />
            );
          })}
        </div>
      )}

      {/* ── Create account modal ── */}
      {showCreate && (
        <CreateAccountModal
          onCreated={handleCreated}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {/* ── Account detail drawer ── */}
      {drawerAccount && (
        <AccountDetailDrawer
          account={drawerAccount}
          onClose={() => setDrawerAccountId(null)}
        />
      )}
    </div>
  );
}
