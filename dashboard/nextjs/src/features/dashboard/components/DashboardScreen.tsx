"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useSystemStore } from "@/store/useSystemStore";
import { useLiveSignals } from "@/lib/realtime/hooks/useLiveSignals";
import { useLiveTrades } from "@/lib/realtime/hooks/useLiveTrades";
import { useLiveRisk } from "@/lib/realtime/hooks/useLiveRisk";
import { useLiveAlerts } from "@/lib/realtime/hooks/useLiveAlerts";
import { useAccounts } from "@/features/accounts/api/accounts.api";

function cardStyle(accent?: string): React.CSSProperties {
  return {
    background: "var(--bg-card,#111827)",
    border: `1px solid ${accent ?? "var(--border,#1e293b)"}`,
    borderRadius: 12,
    padding: 16,
  };
}

export function DashboardScreen() {
  const mode = useSystemStore((s) => s.mode);
  const { data: signals = [] } = useLiveSignals();
  const { data: trades = [] } = useLiveTrades();
  const { data: risk } = useLiveRisk();
  const { data: alerts = [] } = useLiveAlerts();
  const { data: accounts = [] } = useAccounts();

  const pnlToday = useMemo(() => {
    return trades.reduce((acc, trade) => acc + (trade.pnl ?? 0), 0);
  }, [trades]);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Dashboard</h1>
        <p style={{ fontSize: 12, color: "var(--text-muted,#64748b)", fontFamily: "var(--font-mono,monospace)" }}>
          System status · Active signals · Open trades · Risk snapshot · Alerts
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 12 }}>
        <div style={cardStyle("rgba(34,197,94,0.35)")}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", fontFamily: "var(--font-mono,monospace)", color: "var(--text-dim,#475569)" }}>SYSTEM STATUS</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#22c55e" }}>{mode === "OFFLINE" ? "OFFLINE" : "ONLINE"}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted,#64748b)" }}>Pipeline 15-layer ready</div>
        </div>
        <div style={cardStyle("rgba(59,130,246,0.35)")}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", fontFamily: "var(--font-mono,monospace)", color: "var(--text-dim,#475569)" }}>ACTIVE SIGNALS</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#3b82f6" }}>{signals.length}</div>
          <Link href="/signals" style={{ fontSize: 11, color: "var(--text-muted,#64748b)" }}>Open Signals page →</Link>
        </div>
        <div style={cardStyle("rgba(245,158,11,0.35)")}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", fontFamily: "var(--font-mono,monospace)", color: "var(--text-dim,#475569)" }}>DRAWDOWN</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#f59e0b" }}>
            {typeof risk?.drawdown_percent === "number" ? `${risk.drawdown_percent.toFixed(2)}%` : "--"}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted,#64748b)" }}>Circuit breaker monitoring</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
        <div style={cardStyle()}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", fontFamily: "var(--font-mono,monospace)", color: "var(--text-dim,#475569)", marginBottom: 8 }}>OPEN TRADES</div>
          {trades.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted,#64748b)" }}>No active trades.</div>
          ) : (
            <div style={{ display: "grid", gap: 6 }}>
              {trades.slice(0, 5).map((trade) => (
                <div key={trade.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span>{trade.symbol} · {trade.side}</span>
                  <span style={{ color: (trade.pnl ?? 0) >= 0 ? "#22c55e" : "#ef4444" }}>${(trade.pnl ?? 0).toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted,#64748b)" }}>PnL today: <strong style={{ color: pnlToday >= 0 ? "#22c55e" : "#ef4444" }}>${pnlToday.toFixed(2)}</strong></div>
        </div>

        <div style={cardStyle()}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", fontFamily: "var(--font-mono,monospace)", color: "var(--text-dim,#475569)", marginBottom: 8 }}>ACCOUNTS</div>
          <div style={{ fontSize: 22, fontWeight: 800 }}>{accounts.length}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted,#64748b)" }}>Tracked prop-firm accounts</div>
        </div>
      </div>

      <div style={cardStyle()}>
        <div style={{ fontSize: 10, letterSpacing: "0.1em", fontFamily: "var(--font-mono,monospace)", color: "var(--text-dim,#475569)", marginBottom: 8 }}>ALERT FEED</div>
        {alerts.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted,#64748b)" }}>No recent alerts.</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {alerts.slice(0, 8).map((a, index) => (
              <div key={`${a.title}-${index}`} style={{ fontSize: 12, color: "var(--text-muted,#64748b)" }}>
                • {a.title ?? "Alert"}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
