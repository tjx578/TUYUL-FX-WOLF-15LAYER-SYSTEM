"use client";

// ============================================================
// TUYUL FX Wolf-15 — EquityChart (Draw Animation, Glow, Gradient)
// Step 8A: Line draw animation + gradient area + soft glow
//
// Uses Recharts (already installed) for AreaChart with:
//   • Animated draw on mount (animationDuration 1200ms)
//   • SVG linearGradient area fill
//   • CSS drop-shadow glow via wrapper
//   • Framer Motion fade-in entrance
//   • Institutional dark-theme tooltip
//
// Props:
//   labels      — x-axis labels (e.g. trade dates / timestamps)
//   dataPoints  — y-axis values (equity / balance values)
//   title       — optional section label
//   unit        — optional unit suffix shown in tooltip (e.g. "$")
// ============================================================

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  TooltipProps,
  XAxis,
  YAxis,
} from "recharts";
import { motion } from "framer-motion";
import { useId } from "react";

// ─── Props ────────────────────────────────────────────────
interface EquityChartProps {
  labels: string[];
  dataPoints: number[];
  title?: string;
  unit?: string;
}

// ─── Custom Tooltip ───────────────────────────────────────
function ChartTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const value = payload[0]?.value;
  return (
    <div
      style={{
        background: "#0B1623",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 8,
        padding: "8px 12px",
        fontFamily: "var(--font-mono, monospace)",
        fontSize: 12,
      }}
    >
      <div style={{ color: "rgba(255,255,255,0.45)", marginBottom: 4, fontSize: 10 }}>
        {label}
      </div>
      <div style={{ color: "#00F5A0", fontWeight: 600 }}>
        {typeof value === "number" ? value.toFixed(2) : value}
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────
export default function EquityChart({
  labels,
  dataPoints,
  title = "EQUITY CURVE",
  unit,
}: EquityChartProps) {
  const instanceId = useId();
  const gradientId = `equityGrad-${instanceId.replace(/:/g, "")}`;

  // Zip labels + values into recharts-friendly [{label, value}]
  const chartData = labels.map((label, i) => ({
    label,
    value: dataPoints[i] ?? 0,
  }));

  const hasData = chartData.length > 1;

  const first = dataPoints[0] ?? 0;
  const last = dataPoints[dataPoints.length - 1] ?? 0;
  const delta = first !== 0 ? ((last - first) / first) * 100 : 0;
  const isUp = delta >= 0;

  const lineColor = isUp ? "#00F5A0" : "#FF4D4F";
  const gradColorHi = isUp ? "rgba(0,245,160,0.4)" : "rgba(255,77,79,0.4)";
  const gradColorLo = isUp ? "rgba(0,245,160,0.02)" : "rgba(255,77,79,0.02)";
  const glowColor = isUp ? "rgba(0,245,160,0.25)" : "rgba(255,77,79,0.20)";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
      className="panel elevation-2"
      style={{
        padding: "20px 20px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {/* ── Header row ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {title}
        </span>

        {hasData && (
          <span
            className="num"
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: isUp ? "#00F5A0" : "#FF4D4F",
            }}
          >
            {isUp ? "+" : ""}{delta.toFixed(2)}%
          </span>
        )}
      </div>

      {/* ── Chart canvas with glow wrapper ── */}
      {hasData ? (
        <div
          style={{
            filter: `drop-shadow(0 0 20px ${glowColor})`,
          }}
        >
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart
              data={chartData}
              margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
            >
              <defs>
                {/* Unique gradient id so multiple charts on the page don't conflict */}
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={lineColor} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={lineColor} stopOpacity={0.02} />
                </linearGradient>
              </defs>

              <CartesianGrid
                strokeDasharray="3 3"
                stroke="rgba(255,255,255,0.05)"
                vertical={false}
              />

              <XAxis
                dataKey="label"
                tick={{
                  fill: "rgba(255,255,255,0.35)",
                  fontSize: 9,
                  fontFamily: "var(--font-mono)",
                }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />

              <YAxis
                tick={{
                  fill: "rgba(255,255,255,0.35)",
                  fontSize: 9,
                  fontFamily: "var(--font-mono)",
                }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(v) => (unit ? `${unit}${v}` : `${v}`)}
              />

              <Tooltip
                content={<ChartTooltip />}
                cursor={{ stroke: "rgba(255,255,255,0.08)", strokeWidth: 1 }}
              />

              <Area
                type="monotone"
                dataKey="value"
                stroke={lineColor}
                strokeWidth={2}
                fill={`url(#${gradientId})`}
                dot={false}
                activeDot={{
                  r: 4,
                  fill: lineColor,
                  stroke: "rgba(0,0,0,0.5)",
                  strokeWidth: 1,
                }}
                isAnimationActive
                animationBegin={0}
                animationDuration={1200}
                animationEasing="ease-out"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div
          style={{
            height: 220,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 11,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.08em",
          }}
        >
          NO DATA
        </div>
      )}
    </motion.div>
  );
}
