/**
 * Risk Domain Model Tests — PR-010
 *
 * Validates the DD_MULTIPLIER_RULES extracted during PR-009 (risk cutover).
 */
import { describe, expect, it } from "vitest";
import { DD_MULTIPLIER_RULES } from "@/features/risk/model/risk.types";
import type { DdMultiplierRule } from "@/features/risk/model/risk.types";

describe("DD_MULTIPLIER_RULES", () => {
    it("has exactly 4 tiers", () => {
        expect(DD_MULTIPLIER_RULES).toHaveLength(4);
    });

    it("each rule has range, mult, effect, and color", () => {
        for (const rule of DD_MULTIPLIER_RULES) {
            expect(rule).toHaveProperty("range");
            expect(rule).toHaveProperty("mult");
            expect(rule).toHaveProperty("effect");
            expect(rule).toHaveProperty("color");
            expect(typeof rule.range).toBe("string");
            expect(typeof rule.mult).toBe("string");
            expect(typeof rule.effect).toBe("string");
            expect(typeof rule.color).toBe("string");
        }
    });

    it("tiers escalate from full to emergency", () => {
        const effects = DD_MULTIPLIER_RULES.map((r: DdMultiplierRule) => r.effect);
        expect(effects).toEqual(["Full risk", "Reduced", "Half size", "Emergency"]);
    });

    it("multipliers decrease from 1.00x to 0.25x", () => {
        const mults = DD_MULTIPLIER_RULES.map((r) => r.mult);
        expect(mults).toEqual(["1.00x", "0.75x", "0.50x", "0.25x"]);
    });

    it("danger tier uses red color", () => {
        const emergency = DD_MULTIPLIER_RULES[3];
        expect(emergency.color).toContain("red");
    });

    it("safe tier uses green color", () => {
        const safe = DD_MULTIPLIER_RULES[0];
        expect(safe.color).toContain("green");
    });
});
