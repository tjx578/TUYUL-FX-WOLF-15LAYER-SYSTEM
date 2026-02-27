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
  // Text
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
  bDanger: "var(--border-danger, rgba(255,77,79,0.35))",
  bWarn:   "var(--border-warn,   rgba(255,177,0,0.35))",
  bAccent: "var(--border-accent, rgba(0,245,160,0.35))",

  // Semantic colors (raw hex-compatible references)
  red:     "var(--accent-red,     #FF4D4F)",
  amber:   "var(--accent-amber,   #FFB100)",
  emerald: "var(--accent-emerald, #00F5A0)",
  cyan:    "var(--accent-cyan,    #22D3EE)",
  blue:    "var(--accent-blue,    #3B82F6)",

  // Extended palette
  gold:      "var(--accent-gold,    #F5C842)",
  purple:    "var(--accent-purple,  #A78BFA)",
  violet:    "var(--accent-violet,  #8B5CF6)",

  // Glow surface backgrounds (color @ ~5–8% opacity)
  emeraldGlow: "rgba(0,245,160,0.07)",
  amberGlow:   "rgba(255,177,0,0.07)",
  redGlow:     "rgba(255,77,79,0.07)",
  cyanGlow:    "rgba(34,211,238,0.07)",
  goldGlow:    "rgba(245,200,66,0.07)",

  // Dim border variants (~20% opacity)
  emeraldDim: "rgba(0,245,160,0.20)",
  amberDim:   "rgba(255,177,0,0.20)",
  redDim:     "rgba(255,77,79,0.20)",
  cyanDim:    "rgba(34,211,238,0.20)",
  goldDim:    "rgba(245,200,66,0.20)",

  // Verdict palette
  execute: "var(--accent-emerald, #00F5A0)",
  hold:    "var(--accent-amber,   #FFB100)",
  abort:   "var(--accent-red,     #FF4D4F)",
  noTrade: "var(--text-muted,     #6B7280)",
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
export const FONT_MONO    = "var(--font-mono,    'JetBrains Mono', 'Fira Code', ui-monospace, monospace)";
export const FONT_DISPLAY = "var(--font-display, 'Inter', 'DM Sans', system-ui, sans-serif)";

// ── Z-index scale ────────────────────────────────────────────
export const Z = {
  base:    0,
  card:    10,
  overlay: 40,
  modal:   50,
  toast:   60,
} as const;

// ── Shadow helpers ───────────────────────────────────────────
export const SHADOW = {
  sm:  "0 2px 8px rgba(0,0,0,0.40)",
  md:  "0 4px 20px rgba(0,0,0,0.50)",
  lg:  "0 8px 40px rgba(0,0,0,0.65)",
} as const;

// ── Transition presets ───────────────────────────────────────
export const TRANSITION = {
  fast:   "all 0.12s ease",
  normal: "all 0.20s ease",
  slow:   "all 0.35s ease",
} as const;

// ── Wolf-15 Pipeline Zone Colors ─────────────────────────────
// Each of the 15-layer zones has a distinct accent for the zone bar.
export const ZONE_COLORS: Record<string, string> = {
  COG:  "var(--accent-cyan,    #22D3EE)",   // Cognitive layers  (L1–L2)
  ANA:  "var(--accent-emerald, #00F5A0)",   // Analysis layers   (L3–L4, L7–L9)
  META: "var(--accent-amber,   #FFB100)",   // Meta layers       (L5–L6)
  EXEC: "var(--accent-purple,  #A78BFA)",   // Execution layers  (L10–L11)
  VER:  "var(--accent-gold,    #F5C842)",   // Verdict layer     (L12)
  POST: "var(--text-tertiary,  #9CA3AF)",   // Post-trade layers (L13–L15)
};
