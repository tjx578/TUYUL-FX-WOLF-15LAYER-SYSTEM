"use client";

import { useState } from "react";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
import { AccountsScreen } from "@/features/accounts/components/AccountsScreen";
import { PropFirmScreen } from "@/features/prop-firm/components/PropFirmScreen";
import { RiskScreen } from "@/features/risk/components/RiskScreen";

const TABS: TabItem[] = [
  { id: "overview", label: "RISK MONITOR" },
  { id: "accounts", label: "ACCOUNTS" },
  { id: "compliance", label: "COMPLIANCE" },
];

export default function RiskPage() {
  const [tab, setTab] = useState("overview");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab} columns={3}>
        <></>
      </Tabs>

      <div
        style={{
          background: "#0A0B0D",
          border: "1px solid #1A1C1F",
          borderRadius: 16,
          padding: 14,
          minHeight: 540,
        }}
      >
        {tab === "overview" && <RiskScreen />}
        {tab === "accounts" && <AccountsScreen />}
        {tab === "compliance" && <PropFirmScreen />}
      </div>
    </div>
  );
}
