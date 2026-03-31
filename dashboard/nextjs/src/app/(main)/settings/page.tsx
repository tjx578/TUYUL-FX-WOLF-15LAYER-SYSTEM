"use client";

import { useMemo, useState } from "react";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";
import { AgentManagerScreen } from "@/features/agent-manager/components/AgentManagerScreen";
import { SettingsScreen } from "@/features/settings/components/SettingsScreen";
import { hasRole } from "@/lib/auth";
import { useAuthStore } from "@/store/useAuthStore";

function AuditPlaceholder() {
  return (
    <div style={{ background: "#0b0f15", border: "1px solid #232834", borderRadius: 14, padding: 40, textAlign: "center" }}>
      <p style={{ fontFamily: "monospace", fontSize: 11, letterSpacing: "0.12em", color: "#717886" }}>AUDIT LOG</p>
      <p style={{ marginTop: 12, maxWidth: 520, marginInline: "auto", fontSize: 14, color: "#9aa3b2" }}>
        Full audit trail for privileged operations and system events.
      </p>
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState("general");
  const user = useAuthStore((s) => s.user);
  const isAdmin =
    user != null &&
    hasRole(user.role, ["risk_admin", "config_admin", "approver", "owner"] as const);

  const tabs = useMemo<TabItem[]>(() => {
    const base: TabItem[] = [
      { id: "general", label: "General" },
      { id: "agents", label: "Agents" },
    ];
    if (isAdmin) {
      base.push({ id: "audit", label: "Audit Log" });
    }
    return base;
  }, [isAdmin]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Tabs tabs={tabs} activeTab={tab} onTabChange={setTab} columns={isAdmin ? 3 : 2}>
        <></>
      </Tabs>

      <div style={{ background: "#05070a", border: "1px solid #1a1f2b", borderRadius: 16, padding: 14, minHeight: 400 }}>
        {tab === "general" && <SettingsScreen />}
        {tab === "agents" && <AgentManagerScreen />}
        {tab === "audit" && isAdmin && <AuditPlaceholder />}
      </div>
    </div>
  );
}
