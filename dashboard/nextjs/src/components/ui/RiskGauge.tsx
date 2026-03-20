"use client";

// ============================================================
// TUYUL FX Wolf-15 — Animated SVG Gauge
// Framer Motion needle + spring arc + glow + pulse breach
// Path: components/ui/RiskGauge.tsx
// ============================================================

import { motion, useSpring, useMotionTemplate } from "framer-motion";
import { useEffect } from "react";

// ─── Arc geometry constants ────────────────────────────────
const CX = 100;
const CY = 108;
const R  = 78;

/** Semicircle arc length (π × R) */
const ARC_LEN = Math.PI * R; // ≈ 245.04

/** Percentage positions for tick marks */
const TICK_PCTS = [0, 25, 50, 75, 100];

// ─── Helpers ──────────────────────────────────────────────
/** Convert arc percentage to (x, y) on the arc circle */
function arcPoint(pct: number, radius: number) {
  // θ: 180° at pct=0 (left), 90° at pct=50 (top), 0° at pct=100 (right)
  const theta = Math.PI - (pct / 100) * Math.PI;
  return {
    x: CX + radius * Math.cos(theta),
    y: CY - radius * Math.sin(theta),
  };
}

function getSeverity(pct: number): "safe" | "warning" | "critical" {
  if (pct < 60)  return "safe";
  if (pct < 85)  return "warning";
  return "critical";
}

const SEVERITY_COLOR: Record<string, string> = {
  safe:     "var(--accent-emerald)",
  warning:  "var(--accent-amber)",
  critical: "var(--accent-red)",
};

// ─── Props ────────────────────────────────────────────────
export interface AnimatedGaugeProps {
  /** Current drawdown value (e.g. 1.2) */
  value: number;
  /** Maximum / limit value (e.g. 5) */
  max: number;
  /** Label shown above the gauge */
  label: string;
}

// ─── Component ────────────────────────────────────────────
export default function AnimatedGauge({ value, max, label }: AnimatedGaugeProps) {
  const percentage = max > 0 ? Math.min((value / max) * 100, 100) : 0;

  // Needle angle: -90° (left) → 0° (top) → +90° (right)
  const targetNeedle = (percentage / 100) * 180 - 90;

  // Arc dashoffset: fully hidden = ARC_LEN, fully shown = 0
  const targetDash = ARC_LEN - (percentage / 100) * ARC_LEN;

  const severity  = getSeverity(percentage);
  const color     = SEVERITY_COLOR[severity];
  const isCritical = severity === "critical";

  // Spring motion values
  const needleSpring = useSpring(-90, { stiffness: 80, damping: 15 });
  const dashSpring   = useSpring(ARC_LEN, { stiffness: 60, damping: 18 });

  // Animated SVG transform string for the needle group
  const needleTransform = useMotionTemplate`rotate(${needleSpring}, ${CX}, ${CY})`;

  useEffect(() => {
    needleSpring.set(targetNeedle);
    dashSpring.set(targetDash);
  }, [targetNeedle, targetDash, needleSpring, dashSpring]);

  // Unique filter id per label to avoid conflicts when multiple gauges render
  const filterId = `glow-${label.replace(/\W+/g, "-")}`;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 0,
        userSelect: "none",
      }}
    >
      {/* ── Label ── */}
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.20em",
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 2,
          fontFamily: "var(--font-mono, 'Space Mono', monospace)",
        }}
      >
        {label}
      </div>

      {/* ── SVG Canvas ── */}
      <svg
        viewBox="0 0 200 132"
        style={{ width: 200, overflow: "visible" }}
        aria-label={`${label}: ${value.toFixed(2)}% of ${max}%`}
      >
        <defs>
          {/* Shared glow filter */}
          <filter id={filterId} x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="3.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* ── Background track arc ── */}
        <path
          d={`M 22 ${CY} A ${R} ${R} 0 0 1 178 ${CY}`}
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="9"
          strokeLinecap="round"
          fill="none"
        />

        {/* ── Tick marks ── */}
        {TICK_PCTS.map((pct) => {
          const inner = arcPoint(pct, R - 12);
          const outer = arcPoint(pct, R + 4);
          const isMajor = pct === 0 || pct === 50 || pct === 100;
          return (
            <line
              key={pct}
              x1={inner.x} y1={inner.y}
              x2={outer.x} y2={outer.y}
              stroke={isMajor ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.10)"}
              strokeWidth={isMajor ? 1.5 : 1}
              strokeLinecap="round"
            />
          );
        })}

        {/* ── Active arc — animated via spring dashoffset ── */}
        <motion.path
          d={`M 22 ${CY} A ${R} ${R} 0 0 1 178 ${CY}`}
          stroke={color}
          strokeWidth="9"
          strokeLinecap="round"
          fill="none"
          strokeDasharray={ARC_LEN}
          strokeDashoffset={dashSpring}
          style={{ filter: `drop-shadow(0 0 10px ${color})` }}
        />

        {/* ── Breach pulse ring (critical only) ── */}
        {isCritical && (
          <motion.path
            d={`M 22 ${CY} A ${R} ${R} 0 0 1 178 ${CY}`}
            stroke={color}
            strokeWidth="9"
            strokeLinecap="round"
            fill="none"
            strokeDasharray={ARC_LEN}
            strokeDashoffset={dashSpring}
            animate={{ opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
            style={{ filter: `drop-shadow(0 0 22px ${color})` }}
          />
        )}

        {/* ── Needle ── */}
        {/* Outer glow shadow */}
        <motion.g transform={needleTransform}>
          <line
            x1={CX} y1={CY + 6}
            x2={CX} y2={CY - 66}
            stroke={color}
            strokeWidth="5"
            strokeLinecap="round"
            opacity="0.18"
          />
        </motion.g>

        {/* Needle body */}
        <motion.g transform={needleTransform}>
          <line
            x1={CX} y1={CY + 6}
            x2={CX} y2={CY - 66}
            stroke={color}
            strokeWidth="2"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 7px ${color})` }}
          />
          {/* Fine tip */}
          <line
            x1={CX} y1={CY - 66}
            x2={CX} y2={CY - 74}
            stroke={color}
            strokeWidth="1"
            strokeLinecap="round"
            opacity="0.55"
          />
        </motion.g>

        {/* ── Center pivot ── */}
        <motion.circle
          cx={CX} cy={CY} r="6"
          fill={color}
          style={{ filter: `drop-shadow(0 0 10px ${color})` }}
          animate={isCritical ? { r: [6, 8, 6] } : { r: 6 }}
          transition={isCritical ? { duration: 1.4, repeat: Infinity, ease: "easeInOut" } : {}}
        />
        {/* Inner dark dot */}
        <circle cx={CX} cy={CY} r="2.5" fill="var(--bg-base, #080b10)" />

        {/* ── Value readout ── */}
        <text
          x={CX} y={CY - 19}
          textAnchor="middle"
          fill={color}
          fontSize="14"
          fontWeight="700"
          fontFamily="var(--font-mono, 'Space Mono', monospace)"
          style={{ filter: `drop-shadow(0 0 8px ${color})` }}
        >
          {value.toFixed(2)}%
        </text>
        <text
          x={CX} y={CY - 6}
          textAnchor="middle"
          fill="rgba(255,255,255,0.28)"
          fontSize="8"
          fontFamily="var(--font-mono, 'Space Mono', monospace)"
          letterSpacing="1"
        >
          / {max}%
        </text>

        {/* ── Severity label ── */}
        <text
          x={CX} y={CY + 24}
          textAnchor="middle"
          fill={color}
          fontSize="7.5"
          fontWeight="700"
          fontFamily="var(--font-mono, 'Space Mono', monospace)"
          letterSpacing="2"
          opacity="0.80"
        >
          {severity.toUpperCase()}
        </text>
      </svg>
    </div>
  );
}
