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
    <div
      style={{
        background: "#1A1C1F",
        border: "1px solid #2E333B",
        borderRadius: 14,
        padding: "40px 20px",
        textAlign: "center",
      }}
    >
      <div style={{ color: "#717886", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.12em", fontWeight: 700 }}>{title}</div>
      <p style={{ color: "#A4ACB9", fontSize: 14, marginTop: 12, maxWidth: 500, marginInline: "auto" }}>{desc}</p>
    </div>
  );
}

export default function SignalsPage() {
  const [tab, setTab] = useState("active");

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
        {tab === "active" && <SignalBoardScreen />}
        {tab === "history" && (
          <Placeholder
            title="SIGNAL HISTORY"
            desc="Historical verdicts with filtering by pair, direction, and outcome."
          />
        )}
        {tab === "pipeline" && (
          <Placeholder
            title="PIPELINE STATUS"
            desc="15-layer pipeline health, gate pass/fail, and latency diagnostics."
          />
        )}
      </div>
    </div>
  );
}
