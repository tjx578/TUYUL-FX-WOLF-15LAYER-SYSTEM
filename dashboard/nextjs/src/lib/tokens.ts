// ============================================================
// TUYUL FX Wolf-15 — Design Token System
// Single source of truth bridging CSS variables → typed constants.
// All primitives (micro.tsx, etc.) should import from here.
// ============================================================

// ── Text colors ─────────────────────────────────────────────
// ── Background layers ────────────────────────────────────────
// ── Border colors ────────────────────────────────────────────
// ── Semantic palette ─────────────────────────────────────────

export const T = {
  // Text (t0 = hero / max-brightness, t1–t4 descend in opacity)
  t0: "var(--text-bright)",
  t1: "var(--text-primary)",
  t2: "var(--text-secondary)",
  t3: "var(--text-tertiary)",
  t4: "var(--text-muted)",

  // Backgrounds (darkest → lightest surface)
  bg0: "var(--bg-base)",
  bg1: "var(--bg-base)",
  bg2: "var(--bg-panel)",
  bg3: "var(--bg-elevated)",

  // Borders
  b0: "var(--border-subtle)",
  b1: "var(--border-default)",
  bDanger: "var(--border-danger)",
  bWarn: "var(--border-warn)",
  bAccent: "var(--border-accent)",

  // Semantic colors
  red: "var(--accent-red)",
  amber: "var(--accent-amber)",
  emerald: "var(--accent-emerald)",
  cyan: "var(--accent-cyan)",
  teal: "var(--accent-teal)",
  blue: "var(--accent-blue)",
  gold: "var(--accent-gold)",
  purple: "var(--accent-purple)",
  violet: "var(--accent-violet)",

  // Glow fill surfaces (~7% opacity — for subtle background tints)
  emeraldGlow: "var(--glow-surface-green)",
  amberGlow: "var(--glow-surface-amber)",
  redGlow: "var(--glow-surface-red)",
  cyanGlow: "var(--glow-surface-cyan)",
  goldGlow: "var(--glow-surface-gold)",

  // Dim border tints (~20% opacity)
  emeraldDim: "var(--border-dim-green)",
  amberDim: "var(--border-dim-amber)",
  redDim: "var(--border-dim-red)",
  cyanDim: "var(--border-dim-cyan)",
  goldDim: "var(--border-dim-gold)",

  // Verdict palette
  execute: "var(--accent-emerald)",
  hold: "var(--accent-amber)",
  abort: "var(--accent-red)",
  noTrade: "var(--text-muted)",
} as const;

// ── Border radius scale ──────────────────────────────────────
export const RADIUS = {
  xs: 4,
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
  full: 9999,
} as const;

// ── Typography ───────────────────────────────────────────────
export const FONT_MONO = "var(--font-mono,    'JetBrains Mono', 'Fira Code', ui-monospace, monospace)";
export const FONT_DISPLAY = "var(--font-display, 'Inter', 'DM Sans', system-ui, sans-serif)";

// ── Z-index scale ────────────────────────────────────────────
export const Z = {
  base: 0,
  card: 10,
  overlay: 40,
  modal: 50,
  toast: 60,
} as const;

// ── Shadow helpers ───────────────────────────────────────────
export const SHADOW = {
  sm: "0 2px 8px rgba(0,0,0,0.40)",
  md: "0 4px 20px rgba(0,0,0,0.50)",
  lg: "0 8px 40px rgba(0,0,0,0.65)",
} as const;

// ── Transition presets ───────────────────────────────────────
export const TRANSITION = {
  fast: "all 0.12s ease",
  normal: "all 0.20s ease",
  slow: "all 0.35s ease",
} as const;

// ── Wolf-15 Pipeline Zone Colors ─────────────────────────────
// Each of the 15-layer zones has a distinct accent for the zone bar.
// ── Prop Firm Configuration ─────────────────────────────────
export interface PropFirmConfig {
  dailyDD: number;
  maxDD: number;
  newsBlock: number;  // minutes each side of news event
  targets: Record<string, number>;
}

export const PROP_FIRMS: Record<string, PropFirmConfig> = {
  FTMO: {
    dailyDD: 5, maxDD: 10, newsBlock: 30,
    targets: { Challenge: 10, Verification: 5, Funded: 0 },
  },
  MFF: {
    dailyDD: 5, maxDD: 8, newsBlock: 0,
    targets: { "Phase 1": 8, "Phase 2": 5, Funded: 0 },
  },
  "The5%ers": {
    dailyDD: 0, maxDD: 6, newsBlock: 0,
    targets: { Growth: 6, Funded: 0 },
  },
  E8: {
    dailyDD: 5, maxDD: 8, newsBlock: 0,
    targets: { E8: 8, Funded: 0 },
  },
};

// ── Role Configuration ────────────────────────────────────────
export const ROLE_CONFIG: Record<string, { label: string; color?: string }> = {
  trader: { label: "TRADER", color: "var(--accent-emerald, #00F5A0)" },
  risk: { label: "RISK MGR", color: "var(--accent-amber,   #FFB100)" },
  viewer: { label: "VIEWER", color: "var(--text-tertiary)" },
  monitor: { label: "MONITOR", color: "var(--accent-cyan,    #22D3EE)" },
};

// ── Cockpit inline CSS (keyframes not already in globals.css) ─
// Usage: <style>{GLOBAL_CSS}</style> in cockpit/page
export const GLOBAL_CSS = `
  @keyframes kill-pulse {
    0%, 100% { border-color: rgba(255,77,79,0.30); }
    50%       { border-color: rgba(255,77,79,0.70);
                box-shadow:    0 0 24px rgba(255,77,79,0.22); }
  }
  .kill-banner { animation: kill-pulse 2.5s ease-in-out infinite; }
  .layer-row:hover { background: var(--bg-elevated) !important; }
  .card-hover:hover { border-color: rgba(255,255,255,0.14) !important; }
`;

export const ZONE_COLORS: Record<string, string> = {
  COG: "var(--accent-cyan,    #22D3EE)",   // Cognitive layers  (L1–L2)
  ANA: "var(--accent-emerald, #00F5A0)",   // Analysis layers   (L3–L4, L7–L9)
  META: "var(--accent-amber,   #FFB100)",   // Meta layers       (L5–L6)
  EXEC: "var(--accent-purple,  #A78BFA)",   // Execution layers  (L10–L11)
  VER: "var(--accent-gold,    #F5C842)",   // Verdict layer     (L12)
  POST: "var(--text-tertiary,  #9CA3AF)",   // Post-trade layers (L13–L15)
};
