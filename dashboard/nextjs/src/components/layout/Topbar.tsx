"use client";

import { usePathname } from "next/navigation";
import { useSystemStore } from "@/store/useSystemStore";
import { TimezoneDisplay } from "@/components/TimezoneDisplay";

const ROUTE_LABELS: Record<string, string> = {
  "/": "Home",
  "/signals": "Signals",
  "/trades": "Trades",
  "/accounts": "Accounts",
  "/risk": "Risk Monitor",
  "/news": "News",
  "/journal": "Journal",
  "/utilities": "Utilities",
  "/market": "Market Tools",
  "/settings": "Settings",
};

export function Topbar() {
  const pathname = usePathname();
  const wsStatus = useSystemStore((s) => s.wsStatus);
  const complianceState = useSystemStore((s) => s.complianceState);
  const label = ROUTE_LABELS[pathname] ?? "Dashboard";

  const wsConnected = wsStatus === "LIVE";

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 12,
        background: "#0A0B0D",
        border: "1px solid #2E333B",
        borderRadius: 14,
        padding: "14px 18px",
        marginBottom: 14,
      }}
    >
      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 700 }}>
        <span>▣</span>
        <span>{label}</span>
        <span style={{ color: "#A4ACB9" }}>/ Wolf-15 Dashboard</span>
      </div>

      {/* Badges */}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <div
          style={{
            border: "1px solid #2E333B",
            background: "#1A1C1F",
            borderRadius: 10,
            padding: "8px 10px",
            color: wsConnected ? "#22c55e" : "#A4ACB9",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          WS {wsConnected ? "OK" : "—"}
        </div>
        <div
          style={{
            border: "1px solid #2E333B",
            background: "#1A1C1F",
            borderRadius: 10,
            padding: "8px 10px",
            color: complianceState === "OK" ? "#22c55e" : "#A4ACB9",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          Risk {complianceState || "SAFE"}
        </div>
        <div
          style={{
            border: "1px solid #2E333B",
            background: "#1A1C1F",
            borderRadius: 10,
            padding: "8px 10px",
            color: "#A4ACB9",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          <TimezoneDisplay />
        </div>
      </div>
    </div>
  );
}
