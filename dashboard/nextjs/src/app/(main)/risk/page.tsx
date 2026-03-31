"use client";

import React, { useState } from "react";
import { RiskScreen } from "@/features/risk/components/RiskScreen";
import { AccountsScreen } from "@/features/accounts/components/AccountsScreen";
import { PropFirmScreen } from "@/features/prop-firm/components/PropFirmScreen";

const TABS = [
  { id: "overview", label: "RISK OVERVIEW" },
  { id: "accounts", label: "ACCOUNTS" },
  { id: "compliance", label: "COMPLIANCE" },
];

function tabStyle(active: boolean): React.CSSProperties {
  return {
    padding: "10px 20px", fontSize: 11,
    fontFamily: "var(--font-mono,'Share Tech Mono',monospace)",
    fontWeight: active ? 700 : 400, letterSpacing: "0.08em",
    color: active ? "var(--accent,#3b82f6)" : "var(--text-muted,#64748b)",
    background: "transparent", border: "none",
    borderBottom: active ? "2px solid var(--accent,#3b82f6)" : "2px solid transparent",
    marginBottom: -1, cursor: "pointer", transition: "color 0.15s",
  };
}

export default function RiskPage() {
  const [tab, setTab] = useState("overview");
  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 4 }}>Risk &amp; Compliance</h1>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
          Drawdown monitoring · Circuit breaker · Prop-firm rules · Account health
        </p>
      </div>
      <div style={{ display: "flex", borderBottom: "1px solid var(--border,#1e293b)", marginBottom: 24 }}>
        {TABS.map((t) => <button key={t.id} style={tabStyle(tab === t.id)} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      {tab === "overview" && <RiskScreen />}
      {tab === "accounts" && <AccountsScreen />}
      {tab === "compliance" && <PropFirmScreen />}
    </div>
  );
}
