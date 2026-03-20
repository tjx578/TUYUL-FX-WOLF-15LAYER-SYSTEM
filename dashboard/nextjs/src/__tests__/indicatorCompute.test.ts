/**
 * TUYUL FX Wolf-15 — Indicator Compute Tests
 *
 * Tests the pure computation functions used by the indicator Web Worker.
 */

import { describe, it, expect } from "vitest";
import {
    computeSma,
    computeEma,
    computeRsi,
    computeMacd,
    computeBollinger,
} from "@/workers/indicatorCompute";

// Helper: generate a linearly increasing series
function linearCloses(n: number, start = 100, step = 1): number[] {
    return Array.from({ length: n }, (_, i) => start + i * step);
}

// Helper: known data for RSI validation
const RSI_DATA = [
    44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
    46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
    46.22, 45.64,
];

describe("computeSma", () => {
    it("returns all null for insufficient data", () => {
        const result = computeSma([1, 2], 5);
        expect(result).toEqual([null, null]);
    });

    it("computes SMA(3) correctly", () => {
        const closes = [1, 2, 3, 4, 5];
        const sma = computeSma(closes, 3);
        expect(sma[0]).toBeNull();
        expect(sma[1]).toBeNull();
        expect(sma[2]).toBeCloseTo(2); // (1+2+3)/3
        expect(sma[3]).toBeCloseTo(3); // (2+3+4)/3
        expect(sma[4]).toBeCloseTo(4); // (3+4+5)/3
    });

    it("output length matches input length", () => {
        const closes = linearCloses(50);
        const sma = computeSma(closes, 10);
        expect(sma).toHaveLength(50);
    });

    it("first non-null at index period-1", () => {
        const closes = linearCloses(20);
        const sma = computeSma(closes, 5);
        expect(sma[3]).toBeNull();
        expect(sma[4]).not.toBeNull();
    });
});

describe("computeEma", () => {
    it("returns all null for insufficient data", () => {
        const result = computeEma([1, 2], 5);
        expect(result).toEqual([null, null]);
    });

    it("seed is SMA of first period values", () => {
        const closes = [2, 4, 6, 8, 10];
        const ema = computeEma(closes, 3);
        // Seed = (2+4+6)/3 = 4
        expect(ema[2]).toBeCloseTo(4);
    });

    it("reacts faster than SMA to price changes", () => {
        // In a rising market, EMA should be above SMA due to recent-value weighting
        const closes = linearCloses(30);
        const sma = computeSma(closes, 10);
        const ema = computeEma(closes, 10);
        const lastIdx = closes.length - 1;
        // EMA should track closer to current price in a trend
        expect(ema[lastIdx]! >= sma[lastIdx]! - 0.01).toBe(true);
    });

    it("output length matches input length", () => {
        const closes = linearCloses(50);
        const ema = computeEma(closes, 14);
        expect(ema).toHaveLength(50);
    });
});

describe("computeRsi", () => {
    it("returns all null for insufficient data", () => {
        const result = computeRsi([44, 44.34], 14);
        expect(result).toEqual([null, null]);
    });

    it("computes RSI(14) consistent with Wilder formula", () => {
        const rsi = computeRsi(RSI_DATA, 14);
        // First RSI value at index 14
        expect(rsi[13]).toBeNull();
        expect(rsi[14]).not.toBeNull();
        // RSI should be in 0-100 range
        for (const v of rsi) {
            if (v !== null) {
                expect(v).toBeGreaterThanOrEqual(0);
                expect(v).toBeLessThanOrEqual(100);
            }
        }
    });

    it("RSI = 100 for always-rising series", () => {
        const closes = linearCloses(20, 100, 1);
        const rsi = computeRsi(closes, 14);
        // All gains, no losses → RSI should be 100
        const last = rsi[rsi.length - 1];
        expect(last).toBe(100);
    });

    it("RSI < 50 for declining series", () => {
        const closes = linearCloses(20, 200, -1);
        const rsi = computeRsi(closes, 14);
        const last = rsi[rsi.length - 1];
        expect(last).not.toBeNull();
        expect(last!).toBeLessThan(50);
    });
});

describe("computeMacd", () => {
    it("returns all nulls for insufficient data", () => {
        const result = computeMacd([1, 2, 3], 12, 26, 9);
        expect(result.macdLine.every((v) => v === null)).toBe(true);
        expect(result.signalLine.every((v) => v === null)).toBe(true);
        expect(result.histogram.every((v) => v === null)).toBe(true);
    });

    it("computes MACD for sufficient data", () => {
        const closes = linearCloses(60, 100, 0.5);
        const result = computeMacd(closes, 12, 26, 9);
        expect(result.indicator).toBe("macd");
        // MACD line should have values after slow period
        const macdNonNull = result.macdLine.filter((v) => v !== null);
        expect(macdNonNull.length).toBeGreaterThan(0);
    });

    it("histogram = macd - signal where both exist", () => {
        const closes = linearCloses(60, 100, 0.5);
        const result = computeMacd(closes, 12, 26, 9);
        for (let i = 0; i < closes.length; i++) {
            if (result.macdLine[i] !== null && result.signalLine[i] !== null) {
                expect(result.histogram[i]).toBeCloseTo(
                    result.macdLine[i]! - result.signalLine[i]!,
                    10
                );
            }
        }
    });

    it("output arrays match input length", () => {
        const closes = linearCloses(60);
        const result = computeMacd(closes, 12, 26, 9);
        expect(result.macdLine).toHaveLength(60);
        expect(result.signalLine).toHaveLength(60);
        expect(result.histogram).toHaveLength(60);
    });
});

describe("computeBollinger", () => {
    it("returns all nulls for insufficient data", () => {
        const result = computeBollinger([1, 2], 20, 2);
        expect(result.upper.every((v) => v === null)).toBe(true);
        expect(result.middle.every((v) => v === null)).toBe(true);
        expect(result.lower.every((v) => v === null)).toBe(true);
    });

    it("middle band equals SMA", () => {
        const closes = linearCloses(30);
        const bb = computeBollinger(closes, 20, 2);
        const sma = computeSma(closes, 20);
        for (let i = 0; i < closes.length; i++) {
            if (bb.middle[i] !== null) {
                expect(bb.middle[i]).toBeCloseTo(sma[i]!, 10);
            }
        }
    });

    it("upper > middle > lower where values exist", () => {
        // Use data with some variance
        const closes = [100, 102, 98, 103, 97, 105, 96, 104, 99, 101,
            100, 102, 98, 103, 97, 105, 96, 104, 99, 101];
        const bb = computeBollinger(closes, 10, 2);
        for (let i = 0; i < closes.length; i++) {
            if (bb.upper[i] !== null && bb.middle[i] !== null && bb.lower[i] !== null) {
                expect(bb.upper[i]!).toBeGreaterThan(bb.middle[i]!);
                expect(bb.middle[i]!).toBeGreaterThan(bb.lower[i]!);
            }
        }
    });

    it("bands are tighter for constant series", () => {
        const constant = new Array(30).fill(100);
        const bb = computeBollinger(constant, 20, 2);
        // StdDev = 0 → upper = middle = lower = 100
        for (let i = 19; i < 30; i++) {
            expect(bb.upper[i]).toBeCloseTo(100);
            expect(bb.middle[i]).toBeCloseTo(100);
            expect(bb.lower[i]).toBeCloseTo(100);
        }
    });
});
