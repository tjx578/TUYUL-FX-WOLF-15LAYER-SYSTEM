"use client";

import { useMemo } from "react";
import NavTabs from "@/components/NavTabs";
import TradesTable from "@/components/TradesTable";
import { useActiveTrades } from "@/lib/api";
import type { Trade } from "@/types";

export default function TradesPage() {
  const { data, isLoading, mutate } = useActiveTrades();

  const trades = useMemo<Trade[]>(() => {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data.trades)) return data.trades;
    return [];
  }, [data]);

  const openCount = useMemo(
    () => trades.filter((t) => t.status !== "CLOSED").length,
    [trades]
  );

  return (
    <div style={{ padding: "22px 26px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, letterSpacing: "0.06em" }}>
            TRADE DESK
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            Manage trade lifecycle: INTENDED → PENDING → OPEN → CLOSED
          </div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <NavTabs />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 12,
        }}
      >
        <Kpi label="ACTIVE" value={openCount} />
        <Kpi label="TOTAL (CACHE)" value={trades.length} />
        <Kpi label="REFRESH" value={"SWR"} />
      </div>

      {isLoading ? (
        <div style={{ padding: "30px 0", color: "var(--text-muted)" }}>LOADING…</div>
      ) : (
        <TradesTable trades={trades} onAfterAction={() => mutate()} />
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      style={{
        padding: "12px 12px",
        borderRadius: 12,
        background: "var(--bg-card)",
        border: "1px solid rgba(255,255,255,0.08)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: "0.12em",
          color: "var(--text-muted)",
          fontWeight: 900,
        }}
      >
        {label}
      </div>
      <div className="num" style={{ fontSize: 22, fontWeight: 900, color: "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}
