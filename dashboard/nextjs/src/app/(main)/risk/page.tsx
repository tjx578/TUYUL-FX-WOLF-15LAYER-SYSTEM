"use client";

import { useState } from "react";
import { TabPanel, Tabs, type TabItem } from "@/components/ui/Tabs";
import { AccountsScreen } from "@/features/accounts/components/AccountsScreen";
import { PropFirmScreen } from "@/features/prop-firm/components/PropFirmScreen";
import { RiskScreen } from "@/features/risk/components/RiskScreen";

const TABS: TabItem[] = [
  { id: "overview", label: "OVERVIEW" },
  { id: "accounts", label: "ACCOUNTS" },
  { id: "compliance", label: "COMPLIANCE" },
];

export default function RiskPage() {
  const [tab, setTab] = useState("overview");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Risk &amp; Compliance</h1>
        <p className="font-mono text-xs text-[var(--text-muted)]">
          Drawdown, account health, and prop-firm compliance in one route.
        </p>
      </div>

      <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab}>
        <TabPanel id="overview" activeTab={tab}>
          <RiskScreen />
        </TabPanel>
        <TabPanel id="accounts" activeTab={tab}>
          <AccountsScreen />
        </TabPanel>
        <TabPanel id="compliance" activeTab={tab}>
          <PropFirmScreen />
        </TabPanel>
      </Tabs>
    </div>
  );
}
