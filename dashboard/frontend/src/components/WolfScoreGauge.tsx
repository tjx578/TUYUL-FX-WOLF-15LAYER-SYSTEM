"use client";

/**
 * WolfScoreGauge — Wolf 30-Point Discipline Score Visualization
 *
 * Visual gauge component showing:
 * - Animated circular ring with score percentage
 * - Grade classification (ALPHA/PACK/SCOUT/HOLD)
 * - Section breakdown: F7 + T13 + FTA4 + Exec6
 * - Color-coded severity with glow effects
 *
 * Props:
 *   score: WolfScoreData (from L4 pipeline output)
 *   size?: "sm" | "md" | "lg" (default: "md")
 *   animate?: boolean (default: true)
 */

import React, { useEffect, useState, useMemo } from "react";

// ── Types ───────────────────────────────────────────────────────

export interface WolfSectionScore {
  label: string;
  score: number;
  max: number;
  items: { id: string; label: string; passed: boolean }[];
}

export interface WolfScoreData {
  total: number;
  max: number;
  sections: {
    fundamental: WolfSectionScore;
    technical: WolfSectionScore;
    alignment: WolfSectionScore;
    execution: WolfSectionScore;
  };
  grade: "ALPHA" | "PACK" | "SCOUT" | "HOLD";
  timestamp?: string;
}

interface WolfScoreGaugeProps {
  score: WolfScoreData;
  size?: "sm" | "md" | "lg";
  animate?: boolean;
}

// ── Constants ───────────────────────────────────────────────────

const GRADE_CONFIG = {
  ALPHA: { color: "#d4af37", glow: "#d4af3744", label: "ALPHA WOLF", minPct: 90 },
  PACK: { color: "#10b981", glow: "#10b98144", label: "PACK READY", minPct: 75 },
  SCOUT: { color: "#f59e0b", glow: "#f59e0b44", label: "SCOUT MODE", minPct: 60 },
  HOLD: { color: "#ef4444", glow: "#ef444444", label: "HOLD / NO TRADE", minPct: 0 },
} as const;

const SIZE_CONFIG = {
  sm: { ring: 100, stroke: 6, fontSize: 28, subSize: 10 },
  md: { ring: 160, stroke: 8, fontSize: 44, subSize: 12 },
  lg: { ring: 220, stroke: 10, fontSize: 56, subSize: 14 },
} as const;

const SECTION_COLORS = {
  fundamental: "#3b82f6",
  technical: "#a855f7",
  alignment: "#f59e0b",
  execution: "#10b981",
} as const;

// ── Component ───────────────────────────────────────────────────

export function WolfScoreGauge({
  score,
  size = "md",
  animate = true,
}: WolfScoreGaugeProps): React.ReactElement {
  const [animatedPct, setAnimatedPct] = useState(0);
  const cfg = SIZE_CONFIG[size];
  const pct = (score.total / score.max) * 100;
  const gradeInfo = GRADE_CONFIG[score.grade];

  // Animated fill
  useEffect(() => {
    if (!animate) {
      setAnimatedPct(pct);
      return;
    }
    const duration = 1200;
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimatedPct(pct * eased);
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [pct, animate]);

  // SVG ring calculations
  const radius = (cfg.ring - cfg.stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - animatedPct / 100);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: size === "sm" ? 8 : 16,
      }}
    >
      {/* Ring gauge */}
      <div style={{ position: "relative", width: cfg.ring, height: cfg.ring }}>
        <svg
          width={cfg.ring}
          height={cfg.ring}
          style={{ transform: "rotate(-90deg)" }}
        >
          {/* Background ring */}
          <circle
            cx={cfg.ring / 2}
            cy={cfg.ring / 2}
            r={radius}
            fill="none"
            stroke="#1a1a1a"
            strokeWidth={cfg.stroke}
          />
          {/* Score ring */}
          <circle
            cx={cfg.ring / 2}
            cy={cfg.ring / 2}
            r={radius}
            fill="none"
            stroke={gradeInfo.color}
            strokeWidth={cfg.stroke}
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            style={{
              transition: animate ? "none" : "stroke-dashoffset 0.8s ease",
              filter: `drop-shadow(0 0 6px ${gradeInfo.glow})`,
            }}
          />
        </svg>

        {/* Center text */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span
            style={{
              fontSize: cfg.fontSize,
              fontWeight: 800,
              color: gradeInfo.color,
              lineHeight: 1,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {score.total}
          </span>
          <span style={{ fontSize: cfg.subSize, color: "#555" }}>
            /{score.max}
          </span>
        </div>
      </div>

      {/* Grade badge */}
      <div
        style={{
          padding: "4px 12px",
          borderRadius: 6,
          background: `${gradeInfo.color}15`,
          border: `1px solid ${gradeInfo.color}33`,
        }}
      >
        <span
          style={{
            fontSize: cfg.subSize,
            fontWeight: 700,
            color: gradeInfo.color,
            letterSpacing: 1,
          }}
        >
          {gradeInfo.label}
        </span>
      </div>

      {/* Section breakdown */}
      {size !== "sm" && (
        <div style={{ display: "flex", gap: size === "lg" ? 20 : 12 }}>
          {(
            Object.entries(score.sections) as [
              keyof typeof SECTION_COLORS,
              WolfSectionScore,
            ][]
          ).map(([key, section]) => (
            <div key={key} style={{ textAlign: "center" }}>
              <div
                style={{
                  fontSize: 9,
                  color: "#555",
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                {section.label}
              </div>
              <div
                style={{
                  fontSize: size === "lg" ? 20 : 16,
                  fontWeight: 700,
                  color: SECTION_COLORS[key],
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {section.score}
                <span style={{ fontSize: 10, color: "#444" }}>
                  /{section.max}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default WolfScoreGauge;
