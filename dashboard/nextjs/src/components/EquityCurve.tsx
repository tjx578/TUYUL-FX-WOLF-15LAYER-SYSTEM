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

  const equityPoints = history.map((p: { equity: any; }) => p.equity);
  const balancePoints = history.map((p: { balance: any; }) => p.balance);

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

  // gradient ids are unique per account to avoid conflicts
  const gradId = `eq-area-${accountId ?? "default"}`;
  const glowId = `eq-glow-${accountId ?? "default"}`;
  const lineColor = isUp ? "#00F5A0" : "#FF4D4F";
  const areaTop   = isUp ? "rgba(0,245,160,0.40)" : "rgba(255,61,87,0.35)";
  const areaBot   = isUp ? "rgba(0,245,160,0.02)" : "rgba(255,61,87,0.02)";

  return (
    <div className="card elevation-1" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)" }}>
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
            {isUp ? "+" : ""}{equityChange.toFixed(2)}%
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
        // wrapper div carries the drop-shadow so the SVG itself stays crisp
        <div className="equity-chart-wrap">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            style={{
              width: "100%",
              height: H,
              background: "var(--bg-panel)",
              borderRadius: 4,
              display: "block",
            }}
            preserveAspectRatio="none"
          >
            <defs>
              {/* Area gradient: opaque top → transparent bottom */}
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor={areaTop} />
                <stop offset="100%" stopColor={areaBot} />
              </linearGradient>
              {/* SVG blur filter for line glow */}
              <filter id={glowId} x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Subtle horizontal grid lines */}
            {[0.25, 0.5, 0.75].map((frac) => (
              <line
                key={frac}
                x1={0} y1={H * frac}
                x2={W} y2={H * frac}
                stroke="rgba(255,255,255,0.05)"
                strokeWidth="1"
              />
            ))}

            {/* Area fill with gradient */}
            <path d={equityArea} fill={`url(#${gradId})`} />

            {/* Balance line (secondary) */}
            {showBalance && balancePoints.length > 1 && (
              <path
                d={buildPath(balancePoints, W, H)}
                fill="none"
                stroke="rgba(68,138,255,0.35)"
                strokeWidth="1"
                strokeDasharray="4 4"
              />
            )}

            {/* Equity line (with glow filter) */}
            <path
              d={equityPath}
              fill="none"
              stroke={lineColor}
              strokeWidth="2"
              filter={`url(#${glowId})`}
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
                  fill={lineColor}
                  style={{ filter: `drop-shadow(0 0 6px ${lineColor})` }}
                />
              );
            })()}
          </svg>
        </div>
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
