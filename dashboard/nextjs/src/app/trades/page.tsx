"use client";

import { useMemo } from "react";
import NavTabs from "@/components/NavTabs";
import TradesTable from "@/components/TradesTable";
import { useAccountsRiskSnapshot, useActiveTrades } from "@/lib/api";
import type { Trade } from "@/types";

export default function TradesPage() {
  const { data, isLoading, mutate } = useActiveTrades();
  const { data: snapshots, isLoading: snapshotLoading } = useAccountsRiskSnapshot();

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

      <div>
        <div style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--text-muted)", marginBottom: 8 }}>
          ACCOUNT RISK SNAPSHOT
        </div>
        {snapshotLoading ? (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Loading account risk…</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
            {(snapshots ?? []).map((s) => (
              <div
                key={s.account_id}
                style={{
                  borderRadius: 12,
                  border: `1px solid ${
                    s.status === "CRITICAL"
                      ? "rgba(255,61,87,0.45)"
                      : s.status === "WARNING"
                        ? "rgba(255,184,77,0.45)"
                        : "rgba(86,214,138,0.45)"
                  }`,
                  background: "var(--bg-card)",
                  padding: 12,
                  display: "grid",
                  gap: 5,
                }}
              >
                <div style={{ fontWeight: 800, letterSpacing: "0.05em" }}>{s.account_id}</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  DD {s.daily_dd_percent.toFixed(2)}% • Total {s.total_dd_percent.toFixed(2)}%
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Open Risk {s.open_risk_percent.toFixed(2)}% • Open Trades {s.open_trades}/{s.max_concurrent}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 800,
                    color:
                      s.status === "CRITICAL"
                        ? "var(--red)"
                        : s.status === "WARNING"
                          ? "var(--yellow)"
                          : "var(--green)",
                  }}
                >
                  STATUS {s.status}{s.circuit_breaker ? " • CIRCUIT OPEN" : ""}
                </div>
              </div>
            ))}
          </div>
        )}
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
