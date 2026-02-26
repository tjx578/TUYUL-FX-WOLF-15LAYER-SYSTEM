"use client";

// ============================================================
// TUYUL FX Wolf-15 — EquityCurve (SVG sparkline)
// Data: WS /ws/equity → DrawdownData[]
// ============================================================

import { useEquityHistory } from "@/lib/websocket";

interface EquityCurveProps {
  accountId?: string;
  height?: number;
  showBalance?: boolean;
}

function buildPath(
  points: number[],
  width: number,
  height: number,
  padding = 4
): string {
  if (points.length < 2) return "";
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const xStep = (width - padding * 2) / (points.length - 1);

  return points
    .map((v, i) => {
      const x = padding + i * xStep;
      const y = padding + ((max - v) / range) * (height - padding * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function buildArea(
  points: number[],
  width: number,
  height: number,
  padding = 4
): string {
  const path = buildPath(points, width, height, padding);
  if (!path) return "";
  const lastX = (padding + (points.length - 1) * ((width - padding * 2) / (points.length - 1))).toFixed(1);
  return `${path} L${lastX},${height} L${padding},${height} Z`;
}

export function EquityCurve({
  accountId,
  height = 120,
  showBalance = true,
}: EquityCurveProps) {
  const { history, connected } = useEquityHistory(accountId, 500);

  const equityPoints = history.map((p) => p.equity);
  const balancePoints = history.map((p) => p.balance);

  const latest = history[history.length - 1];
  const first = history[0];
  const equityChange = latest && first
    ? ((latest.equity - first.equity) / first.equity) * 100
    : null;
  const isUp = (equityChange ?? 0) >= 0;

  const W = 600;
  const H = height;

  const equityPath = buildPath(equityPoints, W, H);
  const equityArea = buildArea(equityPoints, W, H);

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}
        >
          EQUITY CURVE
        </span>
        {connected && <span className="live-dot" />}
        {equityChange !== null && (
          <span
            className="num"
            style={{
              marginLeft: "auto",
              fontSize: 13,
              fontWeight: 700,
              color: isUp ? "var(--green)" : "var(--red)",
            }}
          >
            {isUp ? "+" : ""}
            {equityChange.toFixed(2)}%
          </span>
        )}
        {latest && (
          <span className="num" style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
            ${latest.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        )}
      </div>

      {/* ── SVG chart ── */}
      {history.length < 2 ? (
        <div
          style={{
            height: H,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            color: "var(--text-muted)",
            background: "var(--bg-panel)",
            borderRadius: 4,
          }}
        >
          {connected ? "Waiting for data..." : "Connecting..."}
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{
            width: "100%",
            height: H,
            background: "var(--bg-panel)",
            borderRadius: 4,
          }}
          preserveAspectRatio="none"
        >
          {/* Area fill */}
          <path
            d={equityArea}
            fill={isUp ? "rgba(0,230,118,0.06)" : "rgba(255,61,87,0.06)"}
          />

          {/* Balance line (secondary) */}
          {showBalance && balancePoints.length > 1 && (
            <path
              d={buildPath(balancePoints, W, H)}
              fill="none"
              stroke="rgba(68,138,255,0.4)"
              strokeWidth="1"
              strokeDasharray="4 4"
            />
          )}

          {/* Equity line */}
          <path
            d={equityPath}
            fill="none"
            stroke={isUp ? "var(--green)" : "var(--red)"}
            strokeWidth="2"
          />

          {/* Latest dot */}
          {equityPoints.length > 0 && (() => {
            const pts = equityPoints;
            const W2 = W, H2 = H, pad = 4;
            const min = Math.min(...pts), max = Math.max(...pts);
            const range = max - min || 1;
            const xStep = (W2 - pad * 2) / (pts.length - 1);
            const x = pad + (pts.length - 1) * xStep;
            const y = pad + ((max - pts[pts.length - 1]) / range) * (H2 - pad * 2);
            return (
              <circle
                cx={x}
                cy={y}
                r="4"
                fill={isUp ? "var(--green)" : "var(--red)"}
              />
            );
          })()}
        </svg>
      )}

      {/* ── DD info ── */}
      {latest && (
        <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--text-muted)" }}>
          <span>
            Daily DD:{" "}
            <span className="num" style={{ color: latest.daily_dd > 2 ? "var(--red)" : "var(--text-secondary)" }}>
              {latest.daily_dd?.toFixed(2)}%
            </span>
          </span>
          <span>
            Total DD:{" "}
            <span className="num" style={{ color: latest.total_dd > 5 ? "var(--red)" : "var(--text-secondary)" }}>
              {latest.total_dd?.toFixed(2)}%
            </span>
          </span>
          <span style={{ marginLeft: "auto", fontSize: 10, fontFamily: "var(--font-mono)" }}>
            {history.length} pts
          </span>
        </div>
      )}
    </div>
  );
}
