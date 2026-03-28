/**
 * Regression tests for lib/tokens.ts (DEBT-07 fix).
 *
 * Ensures all T.* color values are CSS var() references,
 * not hardcoded rgba/hex values. A CSS var failure shows up
 * as transparent/invisible in the browser; a wrong hardcoded
 * value bypasses the design system and breaks theming.
 */

import { describe, it, expect } from "vitest";
import { T, RADIUS, Z } from "@/lib/tokens";

// ══════════════════════════════════════════════════════════════
//  T.* — all color values must be CSS var() references
// ══════════════════════════════════════════════════════════════

describe("T — design token object", () => {
    const colorKeys = Object.keys(T) as (keyof typeof T)[];

    it("all keys are defined (not null/undefined)", () => {
        for (const key of colorKeys) {
            expect(T[key], `T.${key} should be defined`).toBeTruthy();
        }
    });

    it("all color values start with var(--) (no hardcoded rgba/hex)", () => {
    const hardcodedPattern = /^(rgba?|#[0-9a-f]{3,8})/i;
    for (const key of colorKeys) {
        const value = T[key];
        expect(
            hardcodedPattern.test(value),
            `T.${key} = "${value}" is a hardcoded color — must use var(--...)`
        ).toBe(false);
    }
});

it("all color values reference a known CSS variable namespace", () => {
    for (const key of colorKeys) {
        const value = T[key];
        expect(
            value.startsWith("var(--"),
            `T.${key} = "${value}" must start with var(--`
        ).toBe(true);
    }
});

it("text scale t0–t4 reference --text-* vars", () => {
    expect(T.t0).toContain("--text-");
    expect(T.t1).toContain("--text-");
    expect(T.t2).toContain("--text-");
    expect(T.t3).toContain("--text-");
    expect(T.t4).toContain("--text-");
});

it("background scale bg0–bg3 reference --bg-* vars", () => {
    expect(T.bg0).toContain("--bg-");
    expect(T.bg1).toContain("--bg-");
    expect(T.bg2).toContain("--bg-");
    expect(T.bg3).toContain("--bg-");
});

it("semantic colors reference --accent-* vars", () => {
    expect(T.red).toContain("--accent-");
    expect(T.amber).toContain("--accent-");
    expect(T.emerald).toContain("--accent-");
    expect(T.cyan).toContain("--accent-");
    expect(T.gold).toContain("--accent-");
});

it("verdict palette maps to semantic vars", () => {
    expect(T.execute).toBe(T.emerald);
    expect(T.abort).toBe(T.red);
    expect(T.hold).toBe(T.amber);
});

it("glow surface values reference --glow-surface-* vars", () => {
    expect(T.emeraldGlow).toContain("--glow-surface-");
    expect(T.redGlow).toContain("--glow-surface-");
    expect(T.amberGlow).toContain("--glow-surface-");
    expect(T.cyanGlow).toContain("--glow-surface-");
    expect(T.goldGlow).toContain("--glow-surface-");
});

it("dim border tints reference --border-dim-* vars", () => {
    expect(T.emeraldDim).toContain("--border-dim-");
    expect(T.redDim).toContain("--border-dim-");
    expect(T.amberDim).toContain("--border-dim-");
    expect(T.cyanDim).toContain("--border-dim-");
    expect(T.goldDim).toContain("--border-dim-");
});
});

// ══════════════════════════════════════════════════════════════
//  RADIUS — pixel values as numbers
// ══════════════════════════════════════════════════════════════

describe("RADIUS", () => {
    it("all values are positive numbers", () => {
        for (const [key, val] of Object.entries(RADIUS)) {
            expect(typeof val, `RADIUS.${key}`).toBe("number");
            expect(val, `RADIUS.${key}`).toBeGreaterThan(0);
        }
    });

    it("scale is ordered xs < sm < md < lg < xl", () => {
        expect(RADIUS.xs).toBeLessThan(RADIUS.sm);
        expect(RADIUS.sm).toBeLessThan(RADIUS.md);
        expect(RADIUS.md).toBeLessThan(RADIUS.lg);
        expect(RADIUS.lg).toBeLessThan(RADIUS.xl);
    });
});

// ══════════════════════════════════════════════════════════════
//  Z — z-index scale
// ══════════════════════════════════════════════════════════════

describe("Z", () => {
    it("modal is above all other layers", () => {
        expect(Z.modal).toBeGreaterThan(Z.overlay);
        expect(Z.modal).toBeGreaterThan(Z.card);
    });

    it("toast is the highest layer", () => {
        expect(Z.toast).toBeGreaterThan(Z.modal);
    });
});
