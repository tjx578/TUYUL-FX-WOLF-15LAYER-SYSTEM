"use client";

import React, { useState } from "react";
import { useCapitalDeployment, useAccountsRiskSnapshot } from "../api/accounts.api";
import type { Account } from "@/types";
import OrchestratorReadinessStrip from "@/components/OrchestratorReadinessStrip";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { useAccountFocusContract } from "../hooks/useAccountFocusContract";
import { AccountsBridgeBanner } from "./AccountsBridgeBanner";
import { PortfolioSummaryStrip } from "./PortfolioSummaryStrip";
import { AccountGridCard } from "./AccountGridCard";
import AccountDetailDrawer from "./AccountDetailDrawer";
import CreateAccountModal from "./CreateAccountModal";

export function AccountsScreen() {
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

  const focus = useAccountFocusContract();

  const safeAccounts = accounts ?? [];
  const criticalCount = (riskSnapshots ?? []).filter((s) => s.status === "CRITICAL").length;
  const drawerAccount = drawerAccountId
    ? safeAccounts.find((a) => a.account_id === drawerAccountId) ?? null
    : null;

  const handleCreated = () => {
    setShowCreate(false);
    mutate();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="accounts" />

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

      <AccountsBridgeBanner focus={focus} />

      <OrchestratorReadinessStrip />

      {!isLoading && !isError && safeAccounts.length > 0 && (
        <PortfolioSummaryStrip
          accounts={safeAccounts}
          totalUsable={totalUsableCapital}
          avgReadiness={avgReadinessScore}
        />
      )}

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
          <strong style={{ color: "var(--red)" }}>
            {criticalCount} account{criticalCount > 1 ? "s" : ""} in CRITICAL state
          </strong>
          <span style={{ color: "var(--text-muted)" }}>— review drawdown limits immediately.</span>
        </div>
      )}

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

      {isError && !isLoading && (
        <div role="alert" className="panel" style={{ padding: "28px 20px", textAlign: "center" }}>
          <div style={{ fontSize: 13, color: "var(--red)", marginBottom: 6 }}>
            Failed to load capital accounts
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Check the backend connection. Endpoint: /api/v1/accounts/capital-deployment
          </div>
        </div>
      )}

      {!isLoading && !isError && safeAccounts.length === 0 && (
        <div className="panel" style={{ padding: "40px 20px", textAlign: "center" }}>
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

      {!isLoading && !isError && safeAccounts.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
            gap: 14,
          }}
          role="list"
          aria-label="Capital account cards"
        >
          {safeAccounts.map((account: Account) => {
            const snap = riskSnapshots?.find((s) => s.account_id === account.account_id);
            return (
              <AccountGridCard
                key={account.account_id}
                account={account}
                riskSnap={snap}
                onClick={() => setDrawerAccountId(account.account_id)}
                highlighted={focus?.accountId === account.account_id}
              />
            );
          })}
        </div>
      )}

      {showCreate && (
        <CreateAccountModal
          onCreated={handleCreated}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {drawerAccount && (
        <AccountDetailDrawer
          account={drawerAccount}
          onClose={() => setDrawerAccountId(null)}
        />
      )}
    </div>
  );
}
