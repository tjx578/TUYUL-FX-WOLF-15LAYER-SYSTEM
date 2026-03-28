/**
 * Unit tests for lib/formatters.ts — SSR-safe deterministic formatters.
 *
 * All formatters must produce identical output on server and client.
 * Tests use fixed UTC timestamps to avoid TZ flakiness.
 */

import { describe, it, expect } from "vitest";
import {
    formatDate,
    formatDateTime,
    formatNumber,
    formatCurrency,
    formatPercent,
    formatPips,
    formatAge,
} from "@/lib/formatters";

// ══════════════════════════════════════════════════════════════
//  formatDate
// ══════════════════════════════════════════════════════════════

describe("formatDate", () => {
    it("formats a Date object as UTC datetime string by default", () => {
        expect(formatDate(new Date("2024-01-15T10:30:00Z"))).toBe("2024-01-15 10:30 UTC");
    });

    it("formats a numeric timestamp", () => {
        const ts = new Date("2024-01-15T10:30:00Z").getTime();
        expect(formatDate(ts)).toBe("2024-01-15 10:30 UTC");
    });

    it("formats a string ISO timestamp", () => {
        expect(formatDate("2024-01-15T10:30:00Z")).toBe("2024-01-15 10:30 UTC");
    });

    it("pads single-digit month and day with zeroes", () => {
        expect(formatDate(new Date("2024-03-05T00:00:00Z"), { showTime: false })).toBe("2024-03-05");
        expect(formatDate(new Date("2024-01-09T09:09:00Z"), { showTime: false })).toBe("2024-01-09");
    });

    it("returns date only when showTime is false", () => {
        expect(formatDate(new Date("2024-06-20T14:00:00Z"), { showTime: false })).toBe("2024-06-20");
    });

    it("includes seconds when showSeconds is true", () => {
        expect(formatDate(new Date("2024-01-15T10:30:45Z"), { showSeconds: true })).toBe("2024-01-15 10:30:45 UTC");
    });

    it("returns — for null", () => {
        expect(formatDate(null)).toBe("—");
    });

    it("returns — for undefined", () => {
        expect(formatDate(undefined)).toBe("—");
    });

    it("returns — for invalid date string", () => {
        expect(formatDate("not-a-date")).toBe("—");
    });

    it("does not shift timezone — uses UTC hours/minutes", () => {
        // Midnight UTC must show 00:00, not a shifted local hour
        expect(formatDate(new Date("2024-06-01T00:00:00Z"))).toBe("2024-06-01 00:00 UTC");
    });
});

// ══════════════════════════════════════════════════════════════
//  formatDateTime
// ══════════════════════════════════════════════════════════════

describe("formatDateTime", () => {
    it("includes full datetime with seconds (UTC)", () => {
        expect(formatDateTime(new Date("2024-01-15T10:30:45Z"))).toBe("2024-01-15 10:30:45 UTC");
    });

    it("returns — for null", () => {
        expect(formatDateTime(null)).toBe("—");
    });

    it("pads seconds with zero", () => {
        expect(formatDateTime(new Date("2024-01-15T10:30:05Z"))).toBe("2024-01-15 10:30:05 UTC");
    });
});

// ══════════════════════════════════════════════════════════════
//  formatNumber
// ══════════════════════════════════════════════════════════════

describe("formatNumber", () => {
    it("formats with 2 decimal places by default", () => {
        expect(formatNumber(1234.5)).toBe("1,234.50");
    });

    it("formats with 0 decimal places", () => {
        expect(formatNumber(1234.5, 0)).toBe("1,235");
    });

    it("adds thousand separators for large numbers", () => {
        expect(formatNumber(1234567.89)).toBe("1,234,567.89");
    });

    it("formats zero", () => {
        expect(formatNumber(0)).toBe("0.00");
    });

    it("formats negative numbers", () => {
        expect(formatNumber(-1234.56)).toBe("-1,234.56");
    });

    it("parses string input", () => {
        expect(formatNumber("999.50", 1)).toBe("999.5");
    });

    it("returns — for null", () => {
        expect(formatNumber(null)).toBe("—");
    });

    it("returns — for undefined", () => {
        expect(formatNumber(undefined)).toBe("—");
    });

    it("returns — for NaN string", () => {
        expect(formatNumber("abc")).toBe("—");
    });

    it("uses custom fallback", () => {
        expect(formatNumber(null, 2, { fallback: "N/A" })).toBe("N/A");
    });

    it("formats with 5 decimal places (forex pips precision)", () => {
        expect(formatNumber(1.23456, 5)).toBe("1.23456");
    });
});

// ══════════════════════════════════════════════════════════════
//  formatCurrency
// ══════════════════════════════════════════════════════════════

describe("formatCurrency", () => {
    it("formats positive value with $ prefix and commas", () => {
        expect(formatCurrency(1234.56)).toBe("$1,234.56");
    });

    it("formats negative value — sign precedes currency symbol", () => {
        expect(formatCurrency(-500)).toBe("-$500.00");
    });

    it("uses custom currency symbol", () => {
        expect(formatCurrency(100, { currency: "€" })).toBe("€100.00");
    });

    it("respects decimals option", () => {
        expect(formatCurrency(100, { decimals: 0 })).toBe("$100");
    });

    it("parses string input", () => {
        expect(formatCurrency("750.25")).toBe("$750.25");
    });

    it("returns — for null", () => {
        expect(formatCurrency(null)).toBe("—");
    });

    it("returns — for NaN", () => {
        expect(formatCurrency("nope")).toBe("—");
    });

    it("uses custom fallback", () => {
        expect(formatCurrency(null, { fallback: "N/A" })).toBe("N/A");
    });

    it("formats zero correctly", () => {
        expect(formatCurrency(0)).toBe("$0.00");
    });
});

// ══════════════════════════════════════════════════════════════
//  formatPercent
// ══════════════════════════════════════════════════════════════

describe("formatPercent", () => {
    it("formats positive value with + sign", () => {
        expect(formatPercent(5.5)).toBe("+5.5%");
    });

    it("formats negative value with - sign", () => {
        expect(formatPercent(-2.3)).toBe("-2.3%");
    });

    it("formats zero with + sign", () => {
        expect(formatPercent(0)).toBe("+0.0%");
    });

    it("respects decimals parameter", () => {
        expect(formatPercent(1.2345, 2)).toBe("+1.23%");
    });

    it("returns — for null", () => {
        expect(formatPercent(null)).toBe("—");
    });

    it("returns — for NaN string", () => {
        expect(formatPercent("bad")).toBe("—");
    });

    it("uses custom fallback", () => {
        expect(formatPercent(null, 1, { fallback: "N/A" })).toBe("N/A");
    });
});

// ══════════════════════════════════════════════════════════════
//  formatPips
// ══════════════════════════════════════════════════════════════

describe("formatPips", () => {
    it("formats a positive pip value", () => {
        expect(formatPips(12.5)).toBe("12.5 pips");
    });

    it("formats a negative pip value", () => {
        expect(formatPips(-5)).toBe("-5.0 pips");
    });

    it("formats zero", () => {
        expect(formatPips(0)).toBe("0.0 pips");
    });

    it("parses string input and rounds to 1 decimal", () => {
        expect(formatPips("8.75")).toBe("8.8 pips");
    });

    it("returns — for null", () => {
        expect(formatPips(null)).toBe("—");
    });

    it("returns — for NaN string", () => {
        expect(formatPips("x")).toBe("—");
    });
});

// ══════════════════════════════════════════════════════════════
//  formatAge
// ══════════════════════════════════════════════════════════════

describe("formatAge", () => {
    it("formats sub-60s age in seconds", () => {
        expect(formatAge(3500)).toBe("3s");
        expect(formatAge(59000)).toBe("59s");
        expect(formatAge(1000)).toBe("1s");
    });

    it("formats minutes and seconds", () => {
        expect(formatAge(125000)).toBe("2m 5s");
        expect(formatAge(90000)).toBe("1m 30s");
    });

    it("omits seconds when s=0", () => {
        expect(formatAge(120000)).toBe("2m");
        expect(formatAge(300000)).toBe("5m");
    });

    it("formats hours and minutes", () => {
        expect(formatAge(3660000)).toBe("1h 1m");
    });

    it("omits minutes when min=0", () => {
        expect(formatAge(7200000)).toBe("2h");
    });

    it("returns 0s for zero", () => {
        expect(formatAge(0)).toBe("0s");
    });

    it("returns 0s for negative (e.g. clock skew)", () => {
        expect(formatAge(-5000)).toBe("0s");
    });
});
