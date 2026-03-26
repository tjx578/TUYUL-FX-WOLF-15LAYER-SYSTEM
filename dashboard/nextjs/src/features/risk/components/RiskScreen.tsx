"use client";

import { useState } from "react";
import { useAccounts } from "@/features/accounts/api/accounts.api";
import PageComplianceBanner from "@/components/feedback/PageComplianceBanner";
import { RiskContent } from "./RiskContent";
import type { Account } from "@/types";

export function RiskScreen() {
  const { data: accounts, isLoading } = useAccounts();
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");
  const activeAccountId = selectedAccountId || accounts?.[0]?.account_id || "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <PageComplianceBanner page="risk" />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
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
            RISK MONITOR
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            Drawdown tracking, circuit breaker status, real-time WebSocket feed
          </p>
        </div>

        {accounts && accounts.length > 1 && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>ACCOUNT</span>
            <select
              name="account_select"
              value={activeAccountId}
              onChange={(e) => setSelectedAccountId(e.target.value)}
              style={{ fontSize: 12 }}
              aria-label="Select account"
            >
              {accounts.map((a: Account) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.account_name} ({a.currency})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 20 }}>
          <div className="skeleton card" style={{ height: 340 }} />
          <div className="skeleton card" style={{ height: 340 }} />
        </div>
      ) : (accounts ?? []).length === 0 ? (
        <div className="panel" style={{ padding: "32px 20px", textAlign: "center", fontSize: 12, color: "var(--text-muted)" }}>
          No accounts found. Add an account first from the Accounts page.
        </div>
      ) : (
        <RiskContent accountId={activeAccountId} />
      )}
    </div>
  );
}
