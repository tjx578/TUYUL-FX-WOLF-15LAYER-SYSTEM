/**
 * News Domain Model Tests — PR-010
 *
 * Validates the domain constants extracted during PR-008 (news cutover).
 */
import { describe, expect, it } from "vitest";
import {
    IMPACT_STYLES,
    IMPACT_FILTERS,
    CURRENCY_OPTIONS,
} from "@/features/news/model/news.types";
import type { ImpactLevel, ImpactStyle } from "@/features/news/model/news.types";

describe("IMPACT_STYLES", () => {
    it("has entries for HIGH, MEDIUM, LOW", () => {
        const keys = Object.keys(IMPACT_STYLES) as ImpactLevel[];
        expect(keys).toEqual(expect.arrayContaining(["HIGH", "MEDIUM", "LOW"]));
        expect(keys).toHaveLength(3);
    });

    it("each style has bg, color, cls properties", () => {
        for (const level of ["HIGH", "MEDIUM", "LOW"] as ImpactLevel[]) {
            const style: ImpactStyle = IMPACT_STYLES[level];
            expect(style).toHaveProperty("bg");
            expect(style).toHaveProperty("color");
            expect(style).toHaveProperty("cls");
            expect(typeof style.bg).toBe("string");
            expect(typeof style.color).toBe("string");
            expect(typeof style.cls).toBe("string");
        }
    });

    it("HIGH uses red theme", () => {
        expect(IMPACT_STYLES.HIGH.cls).toBe("badge-red");
    });

    it("MEDIUM uses yellow theme", () => {
        expect(IMPACT_STYLES.MEDIUM.cls).toBe("badge-yellow");
    });

    it("LOW uses blue theme", () => {
        expect(IMPACT_STYLES.LOW.cls).toBe("badge-blue");
    });
});

describe("IMPACT_FILTERS", () => {
    it("starts with ALL and includes all impact levels", () => {
        expect(IMPACT_FILTERS).toEqual(["ALL", "HIGH", "MEDIUM", "LOW"]);
    });
});

describe("CURRENCY_OPTIONS", () => {
    it("starts with ALL", () => {
        expect(CURRENCY_OPTIONS[0]).toBe("ALL");
    });

    it("contains the 8 major currencies", () => {
        const currencies = CURRENCY_OPTIONS.slice(1);
        expect(currencies).toEqual(["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]);
    });

    it("has 9 entries total", () => {
        expect(CURRENCY_OPTIONS).toHaveLength(9);
    });
});
