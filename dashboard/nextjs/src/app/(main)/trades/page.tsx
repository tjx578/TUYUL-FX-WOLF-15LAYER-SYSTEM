"use client";

import { useState } from "react";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";
import { JournalScreen } from "@/features/journal/components/JournalScreen";
import { TradesScreen } from "@/features/trades/components/TradesScreen";

const TABS: TabItem[] = [
  { id: "active", label: "ACTIVE" },
  { id: "history", label: "HISTORY" },
  { id: "journal", label: "JOURNAL" },
  { id: "exposure", label: "EXPOSURE" },
];

function Placeholder({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-10 text-center">
      <p className="font-mono text-[11px] tracking-[0.12em] text-[var(--text-dim)]">{title}</p>
      <p className="mx-auto mt-3 max-w-xl text-sm text-[var(--text-muted)]">{desc}</p>
    </div>
  );
}

export default function TradesPage() {
  const [tab, setTab] = useState("active");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Trades</h1>
        <p className="font-mono text-xs text-[var(--text-muted)]">
          Trade desk + journal + exposure in one workflow.
        </p>
      </div>

      <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab}>
        <TabPanel id="active" activeTab={tab}>
          <TradesScreen />
        </TabPanel>
        <TabPanel id="history" activeTab={tab}>
          <Placeholder
            title="TRADE HISTORY"
            desc="Closed trades with sorting, filters, and execution metadata."
          />
        </TabPanel>
        <TabPanel id="journal" activeTab={tab}>
          <JournalScreen />
        </TabPanel>
        <TabPanel id="exposure" activeTab={tab}>
          <Placeholder
            title="EXPOSURE SUMMARY"
            desc="Net long/short and concentration by pair and account."
          />
        </TabPanel>
      </Tabs>
    </div>
  );
}
