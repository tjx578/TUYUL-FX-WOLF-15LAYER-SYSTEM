"use client";

import type { ExposureEntry } from "@/hooks/useTradeDeskState";

interface ExposureSummaryPanelProps {
  byPair: ExposureEntry[];
  byAccount: ExposureEntry[];
}

function ExposureRow({ entry }: { entry: ExposureEntry }) {
  const dirColor =
    entry.direction === "BUY"
      ? "var(--green)"
      : entry.direction === "SELL"
      ? "var(--red)"
      : "var(--yellow)";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "6px 0",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <span
        className="num"
        style={{ fontWeight: 700, color: "var(--text-primary)", fontSize: 11, minWidth: 70 }}
      >
        {entry.key}
      </span>
      <span
        style={{
          fontSize: 9,
          fontWeight: 800,
          color: dirColor,
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.06em",
        }}
      >
        {entry.direction}
      </span>
      <span
        className="num"
        style={{ color: "var(--text-secondary)", fontSize: 10, marginLeft: "auto" }}
      >
        {entry.openCount} trade{entry.openCount !== 1 ? "s" : ""}
      </span>
      <span className="num" style={{ color: "var(--text-primary)", fontSize: 11, fontWeight: 700 }}>
        {entry.totalLot.toFixed(2)} lot
      </span>
      <span
        className="num"
        style={{
          color: entry.unrealizedPnl >= 0 ? "var(--green)" : "var(--red)",
          fontSize: 11,
          fontWeight: 700,
          minWidth: 52,
          textAlign: "right",
        }}
      >
        {entry.unrealizedPnl >= 0 ? "+" : ""}
        {entry.unrealizedPnl.toFixed(2)}
      </span>
    </div>
  );
}

export function ExposureSummaryPanel({ byPair, byAccount }: ExposureSummaryPanelProps) {
  if (byPair.length === 0 && byAccount.length === 0) {
    return (
      <div
        className="card"
        style={{ padding: "14px 16px", fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}
      >
        No open exposure
      </div>
    );
  }

  const totalLot = byPair.reduce((s, e) => s + e.totalLot, 0);
  const totalPnl = byPair.reduce((s, e) => s + e.unrealizedPnl, 0);
  const totalRisk = byAccount.reduce((s, e) => s + e.totalRiskPercent, 0);

  return (
    <div className="card" style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Summary strip */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 8, color: "var(--text-muted)", letterSpacing: "0.1em", fontFamily: "var(--font-mono)", marginBottom: 2 }}>
            TOTAL LOT
          </div>
          <div className="num" style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
            {totalLot.toFixed(2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 8, color: "var(--text-muted)", letterSpacing: "0.1em", fontFamily: "var(--font-mono)", marginBottom: 2 }}>
            OPEN RISK
          </div>
          <div className="num" style={{ fontSize: 16, fontWeight: 700, color: totalRisk > 4 ? "var(--red)" : "var(--text-primary)" }}>
            {totalRisk.toFixed(1)}%
          </div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <div style={{ fontSize: 8, color: "var(--text-muted)", letterSpacing: "0.1em", fontFamily: "var(--font-mono)", marginBottom: 2 }}>
            UNREALIZED PNL
          </div>
          <div
            className="num"
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: totalPnl >= 0 ? "var(--green)" : "var(--red)",
            }}
          >
            {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}
          </div>
        </div>
      </div>

      {/* By pair */}
      {byPair.length > 0 && (
        <div>
          <div style={{ fontSize: 8, color: "var(--text-muted)", letterSpacing: "0.1em", fontFamily: "var(--font-mono)", marginBottom: 6, fontWeight: 700 }}>
            EXPOSURE BY PAIR
          </div>
          {byPair.map((e) => (
            <ExposureRow key={e.key} entry={e} />
          ))}
        </div>
      )}

      {/* By account */}
      {byAccount.length > 0 && (
        <div>
          <div style={{ fontSize: 8, color: "var(--text-muted)", letterSpacing: "0.1em", fontFamily: "var(--font-mono)", marginBottom: 6, fontWeight: 700 }}>
            EXPOSURE BY ACCOUNT
          </div>
          {byAccount.map((e) => (
            <ExposureRow key={e.key} entry={e} />
          ))}
        </div>
      )}
    </div>
  );
}
