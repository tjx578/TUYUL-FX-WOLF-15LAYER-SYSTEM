"use client";

import React, { useState } from "react";
import { TradesScreen } from "@/features/trades/components/TradesScreen";
import { JournalScreen } from "@/features/journal/components/JournalScreen";

const TABS = [
  { id: "active", label: "ACTIVE TRADES" },
  { id: "history", label: "HISTORY" },
  { id: "journal", label: "JOURNAL" },
  { id: "exposure", label: "EXPOSURE" },
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

function Placeholder({ title, desc }: { title: string; desc: string }) {
  return (
    <div style={{ background: "var(--bg-card,#111827)", border: "1px solid var(--border,#1e293b)", borderRadius: 12, padding: "48px 32px", textAlign: "center", minHeight: 280, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }}>
      <div style={{ fontFamily: "var(--font-mono,monospace)", fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-dim,#475569)" }}>{title}</div>
      <div style={{ fontSize: 13, color: "var(--text-muted,#64748b)", maxWidth: 400 }}>{desc}</div>
    </div>
  );
}

export default function TradesPage() {
  const [tab, setTab] = useState("active");
  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 4 }}>Trades</h1>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
          Execution · Position monitoring · Journal · Exposure
        </p>
      </div>
      <div style={{ display: "flex", borderBottom: "1px solid var(--border,#1e293b)", marginBottom: 24 }}>
        {TABS.map((t) => <button key={t.id} style={tabStyle(tab === t.id)} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      {tab === "active" && <TradesScreen />}
      {tab === "history" && <Placeholder title="TRADE HISTORY" desc="Closed trades with full audit trail — entry, exit, P&L, close reason, execution metadata." />}
      {tab === "journal" && <JournalScreen />}
      {tab === "exposure" && <Placeholder title="EXPOSURE SUMMARY" desc="Consolidated exposure by pair and account. Net long/short, lot sizing, margin utilisation." />}
    </div>
  );
}
