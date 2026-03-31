"use client";

import { useState } from "react";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
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
    <div
      style={{
        background: "#0b0f15",
        border: "1px solid #232834",
        borderRadius: 14,
        padding: "40px 20px",
        textAlign: "center",
      }}
    >
      <div style={{ color: "#717886", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.12em", fontWeight: 700 }}>{title}</div>
      <p style={{ color: "#9aa3b2", fontSize: 14, marginTop: 12, maxWidth: 500, marginInline: "auto" }}>{desc}</p>
    </div>
  );
}

export default function TradesPage() {
  const [tab, setTab] = useState("active");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab} columns={4}>
        <></>
      </Tabs>

      <div
        style={{
          background: "#05070a",
          border: "1px solid #1a1f2b",
          borderRadius: 16,
          padding: 14,
          minHeight: 540,
        }}
      >
        {tab === "active" && <TradesScreen />}
        {tab === "history" && (
          <Placeholder
            title="TRADE HISTORY"
            desc="Closed trades with sorting, filters, and execution metadata."
          />
        )}
        {tab === "journal" && <JournalScreen />}
        {tab === "exposure" && (
          <Placeholder
            title="EXPOSURE SUMMARY"
            desc="Net long/short and concentration by pair and account."
          />
        )}
      </div>
    </div>
  );
}
