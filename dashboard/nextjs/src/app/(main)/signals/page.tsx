"use client";

import { useState } from "react";
import { SignalBoardScreen } from "@/features/signals/components/SignalBoardScreen";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";

const TABS: TabItem[] = [
  { id: "active", label: "ACTIVE" },
  { id: "history", label: "HISTORY" },
  { id: "pipeline", label: "PIPELINE" },
];

function Placeholder({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-10 text-center">
      <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--text-dim)]">{title}</p>
      <p className="mx-auto mt-3 max-w-xl text-sm text-[var(--text-muted)]">{desc}</p>
    </div>
  );
}

export default function SignalsPage() {
  const [tab, setTab] = useState("active");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Signals</h1>
        <p className="font-mono text-xs text-[var(--text-muted)]">
          Signal board + pipeline status in one route.
        </p>
      </div>

      <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab}>
        <TabPanel id="active" activeTab={tab}>
          <SignalBoardScreen />
        </TabPanel>
        <TabPanel id="history" activeTab={tab}>
          <Placeholder
            title="SIGNAL HISTORY"
            desc="Historical verdicts with filtering by pair, direction, and outcome."
          />
        </TabPanel>
        <TabPanel id="pipeline" activeTab={tab}>
          <Placeholder
            title="PIPELINE STATUS"
            desc="15-layer pipeline health, gate pass/fail, and latency diagnostics."
          />
        </TabPanel>
      </Tabs>
    </div>
  );
}
