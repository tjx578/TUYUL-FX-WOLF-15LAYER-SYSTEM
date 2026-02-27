"use client";

// ============================================================
// TUYUL FX — Micro Components v8.1 (Merged Edition)
//
// Best-of-both:
//   • v8.0 primitives  → M, L, Dot, Badge, VerdictBadge,
//                        Divider, Card, Bar, Ring, Toggle,
//                        Sel, NumInput, Section, Tabs, StreamBadge
//   • Repo enhancements → Framer Motion on Ring & StreamBadge,
//                         typed verdict palette, className escape
//                         hatch on every text primitive.
//
// Depends on: @/lib/tokens (CSS-var design system)
// ============================================================

import React, { useEffect } from "react";
import { motion, useSpring, useMotionValue, animate } from "framer-motion";
import { T, RADIUS, FONT_MONO, FONT_DISPLAY } from "@/lib/tokens";

// ── Monospace data text ───────────────────────────────────────
// Usage: <M c={T.emerald} s={13}>1.08540</M>
export function M({
  c, s = 11, w = 500, italic = false, className, children,
}: {
  c?: string; s?: number; w?: number; italic?: boolean;
  className?: string; children: React.ReactNode;
}) {
  return (
    <span
      className={className}
      style={{
        fontFamily: FONT_MONO,
        fontSize: s,
        color: c ?? T.t1,
        fontWeight: w,
        fontStyle: italic ? "italic" : "normal",
        letterSpacing: "-0.02em",
      }}
    >
      {children}
    </span>
  );
}

// ── Label / Section heading text ─────────────────────────────
// Usage: <L s={9} c={T.t3}>DRAWDOWN LIMIT</L>
export function L({
  c, s = 9, upper = true, w = 600, className, children,
}: {
  c?: string; s?: number; upper?: boolean; w?: number;
  className?: string; children: React.ReactNode;
}) {
  return (
    <span
      className={className}
      style={{
        fontFamily: FONT_DISPLAY,
        fontSize: s,
        color: c ?? T.t3,
        fontWeight: w,
        letterSpacing: upper ? "0.09em" : "0.02em",
        textTransform: upper ? "uppercase" : "none",
      }}
    >
      {children}
    </span>
  );
}

// ── Status dot ───────────────────────────────────────────────
// Usage: <Dot color={T.emerald} pulse />
export function Dot({
  color, pulse = false, size = 6,
}: {
  color: string; pulse?: boolean; size?: number;
}) {
  return (
    <span style={{
      display: "inline-block",
      width: size,
      height: size,
      borderRadius: "50%",
      backgroundColor: color,
      boxShadow: pulse ? `0 0 0 2px ${color}20, 0 0 8px ${color}50` : "none",
      animation: pulse ? "pulse 2s infinite" : "none",
      flexShrink: 0,
    }} />
  );
}

// ── Badge pill (generic) ─────────────────────────────────────
// Usage: <Badge color={T.amber}>WARNING</Badge>
export function Badge({
  children, color, size = 9, bg,
}: {
  children: React.ReactNode; color: string; size?: number; bg?: string;
}) {
  return (
    <span style={{
      padding: "1px 7px",
      borderRadius: RADIUS.full,
      fontSize: size,
      fontFamily: FONT_MONO,
      fontWeight: 600,
      color,
      backgroundColor: bg ?? `${color}18`,
      border: `1px solid ${color}28`,
      whiteSpace: "nowrap",
      letterSpacing: "0.03em",
      lineHeight: "18px",
    }}>
      {children}
    </span>
  );
}

// ── Verdict badge (typed, repo-enhanced) ─────────────────────
// Absorbs StatusBadge pattern — maps L12 verdict strings.
// Usage: <VerdictBadge type="execute">EXECUTE BUY</VerdictBadge>
const VERDICT_BADGE_STYLES: Record<
  "execute" | "hold" | "no-trade" | "abort",
  { color: string; bg: string; border: string }
> = {
  execute:   { color: T.emerald, bg: `${T.emerald}12`, border: `${T.emerald}28` },
  hold:      { color: T.amber,   bg: `${T.amber}12`,   border: `${T.amber}28`   },
  "no-trade":{ color: T.t4,      bg: `${T.t4}12`,      border: `${T.t4}20`      },
  abort:     { color: T.red,     bg: `${T.red}18`,      border: `${T.red}35`     },
};

export function VerdictBadge({
  type, children, size = 9,
}: {
  type: "execute" | "hold" | "no-trade" | "abort";
  children: React.ReactNode;
  size?: number;
}) {
  const s = VERDICT_BADGE_STYLES[type];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 9px",
      borderRadius: RADIUS.full,
      fontSize: size,
      fontFamily: FONT_MONO,
      fontWeight: 700,
      color: s.color,
      backgroundColor: s.bg,
      border: `1px solid ${s.border}`,
      letterSpacing: "0.07em",
      textTransform: "uppercase",
      lineHeight: "18px",
      whiteSpace: "nowrap",
    }}>
      {children}
    </span>
  );
}

// ── Divider ──────────────────────────────────────────────────
export function Divider({ my = 10, color }: { my?: number; color?: string }) {
  return (
    <div style={{
      height: 1,
      backgroundColor: color ?? T.b0,
      margin: `${my}px 0`,
    }} />
  );
}

// ── Card container ───────────────────────────────────────────
// Compact data-dense card — for gauges, signal rows, risk panels.
// For hero / page-level containers use <Panel> (glass-morphism).
export function Card({
  children, title, sub, icon, accentColor, pad = true, right, style = {}, className,
}: {
  children: React.ReactNode;
  title?: string;
  sub?: string;
  icon?: string;
  accentColor?: "ok" | "warn" | "danger" | string;
  pad?: boolean;
  right?: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}) {
  const bc =
    accentColor === "danger" ? T.bDanger :
    accentColor === "warn"   ? T.bWarn   :
    accentColor === "ok"     ? T.bAccent : T.b1;

  const topBorder =
    accentColor === "danger" ? `2px solid ${T.red}50`     :
    accentColor === "warn"   ? `2px solid ${T.amber}50`   :
    accentColor === "ok"     ? `2px solid ${T.emerald}50` :
    "2px solid transparent";

  return (
    <div
      className={`card-hover${className ? ` ${className}` : ""}`}
      style={{
        backgroundColor: T.bg2,
        borderRadius: RADIUS.lg,
        border: `1px solid ${bc}`,
        overflow: "hidden",
        borderTop: topBorder,
        ...style,
      }}
    >
      {title && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "9px 13px", borderBottom: `1px solid ${T.b0}`,
          backgroundColor: T.bg1,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            {icon && <span style={{ fontSize: 12, lineHeight: 1 }}>{icon}</span>}
            <div>
              <L s={9} c={T.t2}>{title}</L>
              {sub && (
                <div style={{
                  fontSize: 8, color: T.t4, marginTop: 1, fontFamily: FONT_MONO,
                }}>
                  {sub}
                </div>
              )}
            </div>
          </div>
          {right}
        </div>
      )}
      <div style={{ padding: pad ? "11px 13px" : 0 }}>{children}</div>
    </div>
  );
}

// ── Progress bar ─────────────────────────────────────────────
// Enhanced: CSS transition on bar width; warn/danger threshold markers.
export function Bar({
  value, max, color, warn = 0.6, danger = 0.85, label, h = 4, showGlow = true,
}: {
  value: number; max: number; color?: string;
  warn?: number; danger?: number; label?: string; h?: number; showGlow?: boolean;
}) {
  const pct = Math.min(value / max, 1);
  const c = pct >= danger ? T.red : pct >= warn ? T.amber : (color ?? T.emerald);
  const glowColor = showGlow && pct > warn ? `0 0 6px ${c}40` : "none";

  return (
    <div>
      {label && (
        <div style={{
          display: "flex", justifyContent: "space-between", marginBottom: 4,
          fontSize: 9, fontFamily: FONT_MONO,
        }}>
          <span style={{ color: T.t3 }}>{label}</span>
          <span style={{ color: c, fontWeight: 600 }}>
            {typeof value === "number" ? value.toFixed(1) : value} / {max}%
          </span>
        </div>
      )}
      <div style={{
        width: "100%", height: h, borderRadius: h,
        backgroundColor: T.b0, overflow: "hidden", position: "relative",
      }}>
        <div
          className="bar-track"
          style={{
            width: `${pct * 100}%`, height: "100%", borderRadius: h,
            background: `linear-gradient(90deg, ${c}70, ${c})`,
            boxShadow: glowColor,
            transition: "width 0.35s ease, background 0.35s ease, box-shadow 0.35s ease",
          }}
        />
        {/* Threshold markers */}
        <div style={{
          position: "absolute", left: `${warn * 100}%`, top: 0, bottom: 0,
          width: 1, backgroundColor: `${T.amber}30`,
        }} />
        <div style={{
          position: "absolute", left: `${danger * 100}%`, top: 0, bottom: 0,
          width: 1, backgroundColor: `${T.red}30`,
        }} />
      </div>
    </div>
  );
}

// ── SVG Ring Gauge (Framer Motion enhanced) ──────────────────
// Simple score/progress ring — for complex animated needles use <RiskGauge>.
// Enhancement: Framer Motion spring on stroke-dashoffset for smooth fill.
export function Ring({
  value, max, size = 72, sw = 5, color, glow = true, children,
}: {
  value: number; max: number; size?: number; sw?: number;
  color: string; glow?: boolean; children?: React.ReactNode;
}) {
  const r = (size - sw) / 2;
  const circ = 2 * Math.PI * r;
  const targetOff = circ * (1 - Math.min(value / max, 1));

  // Spring-animated dashoffset (from repo's RiskGauge pattern)
  const dashOffset = useSpring(circ, { stiffness: 60, damping: 18 });
  useEffect(() => { dashOffset.set(targetOff); }, [targetOff, dashOffset]);

  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        {/* Track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={T.b0} strokeWidth={sw}
        />
        {/* Animated fill */}
        <motion.circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={color}
          strokeWidth={sw}
          strokeLinecap="round"
          strokeDasharray={circ}
          style={{
            strokeDashoffset: dashOffset,
            filter: glow ? `drop-shadow(0 0 4px ${color}60)` : "none",
          }}
        />
      </svg>
      {/* Center slot */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}>
        {children}
      </div>
    </div>
  );
}

// ── Toggle switch ────────────────────────────────────────────
export function Toggle({
  value, onChange, label, small,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  label?: string;
  small?: boolean;
}) {
  const trackW = small ? 30 : 36;
  const trackH = small ? 15 : 18;
  const knobSz = small ? 11 : 14;
  const knobOn = small ? 17 : 20;

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 8, padding: small ? 0 : "3px 0",
    }}>
      {label && (
        <span style={{ fontSize: 11, color: T.t2, fontFamily: FONT_MONO }}>{label}</span>
      )}
      <button
        onClick={() => onChange(!value)}
        aria-pressed={value}
        style={{
          width: trackW, height: trackH,
          borderRadius: RADIUS.full, border: "none", cursor: "pointer",
          backgroundColor: value ? `${T.emerald}28` : T.b1,
          position: "relative", flexShrink: 0,
          transition: "background 0.2s",
        }}
      >
        <div style={{
          width: knobSz, height: knobSz,
          borderRadius: "50%",
          backgroundColor: value ? T.emerald : T.t4,
          position: "absolute", top: (trackH - knobSz) / 2,
          left: value ? knobOn : 2,
          transition: "left 0.2s, background 0.2s",
          boxShadow: value ? `0 0 5px ${T.emerald}60` : "none",
        }} />
      </button>
    </div>
  );
}

// ── Select ───────────────────────────────────────────────────
export function Sel({
  value, options, onChange, label, w,
}: {
  value: string | number;
  options: (string | { value: string | number; label: string })[];
  onChange: (v: string) => void;
  label?: string;
  w?: string | number;
}) {
  return (
    <div>
      {label && (
        <div style={{
          fontSize: 9, color: T.t3, marginBottom: 3,
          fontFamily: FONT_DISPLAY, fontWeight: 600,
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>
          {label}
        </div>
      )}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: w ?? "100%", padding: "5px 8px", borderRadius: RADIUS.sm,
          border: `1px solid ${T.b1}`, backgroundColor: T.bg3, color: T.t1,
          fontSize: 10, cursor: "pointer", fontFamily: FONT_MONO,
          outline: "none",
        }}
      >
        {options.map((o) => {
          const val = typeof o === "string" ? o : o.value;
          const lbl = typeof o === "string" ? o : o.label;
          return <option key={val} value={val}>{lbl}</option>;
        })}
      </select>
    </div>
  );
}

// ── Number Input ─────────────────────────────────────────────
export function NumInput({
  value, onChange, label, suffix, min, max, step = 1, w,
}: {
  value: number; onChange: (v: number) => void;
  label?: string; suffix?: string;
  min?: number; max?: number; step?: number; w?: number;
}) {
  return (
    <div>
      {label && (
        <div style={{
          fontSize: 9, color: T.t3, marginBottom: 3,
          fontFamily: FONT_DISPLAY, fontWeight: 600,
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>
          {label}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <input
          type="number"
          value={value}
          min={min} max={max} step={step}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          style={{
            width: w ?? 78, padding: "5px 7px", borderRadius: RADIUS.sm,
            border: `1px solid ${T.b1}`, backgroundColor: T.bg3,
            color: T.t1, fontSize: 11, textAlign: "right",
            fontFamily: FONT_MONO, outline: "none",
          }}
        />
        {suffix && (
          <span style={{
            fontSize: 9, color: T.t3, fontFamily: FONT_MONO,
          }}>
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Section header ───────────────────────────────────────────
export function Section({
  title, children, right,
}: {
  title?: string; children: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      {title && (
        <div style={{
          display: "flex", alignItems: "center",
          justifyContent: "space-between", marginBottom: 8,
        }}>
          <L s={9}>{title}</L>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

// ── Tabs ─────────────────────────────────────────────────────
// Rendered as pill-tab bar. Active tab gets bg3 / text-primary highlight.
export function Tabs({
  tabs, active, onChange, compact,
}: {
  tabs: { id: string; label: string; icon?: string }[];
  active: string;
  onChange: (id: string) => void;
  compact?: boolean;
}) {
  return (
    <div style={{
      display: "flex", gap: 2, padding: 2,
      backgroundColor: T.bg1, borderRadius: RADIUS.sm,
      marginBottom: compact ? 8 : 12,
    }}>
      {tabs.map((t) => (
        <button
          key={t.id}
          className="tab-btn"
          onClick={() => onChange(t.id)}
          aria-selected={active === t.id}
          style={{
            flex: 1,
            padding: compact ? "5px 6px" : "6px 8px",
            borderRadius: RADIUS.xs,
            border: "none",
            cursor: "pointer",
            backgroundColor: active === t.id ? T.bg3 : "transparent",
            color: active === t.id ? T.t1 : T.t3,
            fontSize: compact ? 8 : 9,
            fontWeight: 600,
            fontFamily: FONT_DISPLAY,
            transition: "all 0.15s",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          }}
        >
          {t.icon && <span style={{ marginRight: 3 }}>{t.icon}</span>}
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ── WebSocket stream badge (Framer Motion enhanced) ──────────
// Shows live WS connection status. Framer Motion fade-in on status change.
const STREAM_CFG: Record<string, { c: string; label: string }> = {
  connected:      { c: T.emerald, label: "LIVE"  },
  authenticating: { c: T.amber,   label: "AUTH"  },
  reconnecting:   { c: T.amber,   label: "RECONN"},
  disconnected:   { c: T.t4,      label: "OFF"   },
  error:          { c: T.red,     label: "ERR"   },
};

export function StreamBadge({ status }: { status: string }) {
  const s = STREAM_CFG[status] ?? STREAM_CFG.disconnected;
  return (
    <motion.div
      key={status}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2 }}
      style={{
        display: "flex", alignItems: "center", gap: 4,
        padding: "2px 7px", borderRadius: RADIUS.sm,
        border: `1px solid ${s.c}22`,
        backgroundColor: `${s.c}0A`,
      }}
    >
      <Dot color={s.c} pulse={status === "connected"} size={4} />
      <L s={7} c={s.c}>{s.label}</L>
    </motion.div>
  );
}

// ── Stat row  ────────────────────────────────────────────────
// Quick key-value row used inside Card/Section.
// Usage: <Stat label="WIN RATE" value="67.4%" color={T.emerald} />
export function Stat({
  label, value, color, sub,
}: {
  label: string; value: React.ReactNode;
  color?: string; sub?: string;
}) {
  return (
    <div style={{
      display: "flex", alignItems: "baseline",
      justifyContent: "space-between",
      padding: "4px 0",
    }}>
      <L s={9} c={T.t3}>{label}</L>
      <div style={{ textAlign: "right" }}>
        <M s={12} c={color ?? T.t1} w={600}>{value}</M>
        {sub && (
          <div style={{ fontSize: 9, color: T.t4, fontFamily: FONT_MONO }}>{sub}</div>
        )}
      </div>
    </div>
  );
}

// ── Kv grid (2-col key/value table) ─────────────────────────
// Renders an array of {label, value, color} entries in a compact grid.
export function KvGrid({
  rows, cols = 2,
}: {
  rows: { label: string; value: React.ReactNode; color?: string }[];
  cols?: 1 | 2 | 3;
}) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(${cols}, 1fr)`,
      gap: "6px 12px",
    }}>
      {rows.map((r, i) => (
        <div key={i}>
          <L s={8} c={T.t4}>{r.label}</L>
          <div style={{ marginTop: 2 }}>
            <M s={11} c={r.color ?? T.t1} w={600}>{r.value}</M>
          </div>
        </div>
      ))}
    </div>
  );
}
