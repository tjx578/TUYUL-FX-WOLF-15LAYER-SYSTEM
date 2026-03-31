"use client";

import { useMemo, useState } from "react";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";
import { AgentManagerScreen } from "@/features/agent-manager/components/AgentManagerScreen";
import { SettingsScreen } from "@/features/settings/components/SettingsScreen";
import { hasRole } from "@/lib/auth";
import { useAuthStore } from "@/store/useAuthStore";

function AuditPlaceholder() {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-10 text-center">
      <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--text-dim)]">AUDIT LOG</p>
      <p className="mx-auto mt-3 max-w-xl text-sm text-[var(--text-muted)]">
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
      { id: "general", label: "GENERAL" },
      { id: "agents", label: "AGENTS" },
    ];
    if (isAdmin) {
      base.push({ id: "audit", label: "AUDIT" });
    }
    return base;
  }, [isAdmin]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Settings &amp; Operations</h1>
        <p className="font-mono text-xs text-[var(--text-muted)]">
          Configuration, agents, and role-gated audit access.
        </p>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onTabChange={setTab}>
        <TabPanel id="general" activeTab={tab}>
          <SettingsScreen />
        </TabPanel>
        <TabPanel id="agents" activeTab={tab}>
          <AgentManagerScreen />
        </TabPanel>
        <TabPanel id="audit" activeTab={tab}>
          {isAdmin ? <AuditPlaceholder /> : null}
        </TabPanel>
      </Tabs>
    </div>
  );
}
