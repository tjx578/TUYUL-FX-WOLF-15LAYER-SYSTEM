"use client";

import React, { useState } from "react";
import { SettingsScreen } from "@/features/settings/components/SettingsScreen";
import { AgentManagerScreen } from "@/features/agent-manager/components/AgentManagerScreen";
import { useAuthStore } from "@/store/useAuthStore";
import { hasRole } from "@/lib/auth";

const BASE_TABS = [
  { id: "general", label: "GENERAL", adminOnly: false },
  { id: "agents", label: "AGENTS", adminOnly: false },
  { id: "audit", label: "AUDIT LOG", adminOnly: true },
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

function AuditPlaceholder() {
  return (
    <div style={{ background: "var(--bg-card,#111827)", border: "1px solid var(--border,#1e293b)", borderRadius: 12, padding: "48px 32px", textAlign: "center", minHeight: 280, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }}>
      <div style={{ fontFamily: "var(--font-mono,monospace)", fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-dim,#475569)" }}>AUDIT LOG</div>
      <div style={{ fontSize: 13, color: "var(--text-muted,#64748b)", maxWidth: 400 }}>Full audit trail of all system actions, config changes, and operator events. Admin access required.</div>
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState("general");
  const user = useAuthStore((s) => s.user);
  const isAdmin = user != null && hasRole(user.role, ["risk_admin", "config_admin", "approver", "owner"] as const);
  const tabs = BASE_TABS.filter((t) => !t.adminOnly || isAdmin);

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.01em", marginBottom: 4 }}>Settings &amp; Operations</h1>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
          System configuration · Agent management · Audit trail
        </p>
      </div>
      <div style={{ display: "flex", borderBottom: "1px solid var(--border,#1e293b)", marginBottom: 24 }}>
        {tabs.map((t) => (
          <button key={t.id} style={tabStyle(tab === t.id)} onClick={() => setTab(t.id)}>
            {t.label}
            {t.adminOnly && <span style={{ marginLeft: 6, fontSize: 9, padding: "1px 5px", borderRadius: 4, background: "rgba(245,158,11,0.12)", color: "#f59e0b", fontWeight: 700 }}>ADMIN</span>}
          </button>
        ))}
      </div>
      {tab === "general" && <SettingsScreen />}
      {tab === "agents" && <AgentManagerScreen />}
      {tab === "audit" && isAdmin && <AuditPlaceholder />}
    </div>
  );
}
