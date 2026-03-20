/**
 * TUYUL FX Wolf-15 — Candle Compute Tests
 *
 * Tests the pure computation functions used by the candle Web Worker.
 */

import { describe, it, expect } from "vitest";
import { aggregateTicks, resampleCandles } from "@/workers/candleCompute";
import type { OHLC, TickData } from "@/workers/protocol";

describe("aggregateTicks", () => {
    it("returns empty for no ticks", () => {
        expect(aggregateTicks([], 60_000)).toEqual([]);
    });

    it("aggregates ticks into a single candle when all in same bucket", () => {
        const ticks: TickData[] = [
            { symbol: "EURUSD", price: 1.1000, timestamp: 0 },
            { symbol: "EURUSD", price: 1.1020, timestamp: 10_000 },
            { symbol: "EURUSD", price: 1.0980, timestamp: 20_000 },
            { symbol: "EURUSD", price: 1.1010, timestamp: 30_000 },
        ];
        const candles = aggregateTicks(ticks, 60_000);
        expect(candles).toHaveLength(1);
        expect(candles[0]).toEqual({
            open: 1.1000,
            high: 1.1020,
            low: 1.0980,
            close: 1.1010,
            volume: 0,
            timestamp: 0,
        });
    });

    it("splits ticks across multiple candle buckets", () => {
        const ticks: TickData[] = [
            { symbol: "EURUSD", price: 1.1000, timestamp: 0 },
            { symbol: "EURUSD", price: 1.1010, timestamp: 30_000 },
            { symbol: "EURUSD", price: 1.1020, timestamp: 60_000 },
            { symbol: "EURUSD", price: 1.1030, timestamp: 90_000 },
        ];
        const candles = aggregateTicks(ticks, 60_000);
        expect(candles).toHaveLength(2);
        expect(candles[0].timestamp).toBe(0);
        expect(candles[0].close).toBe(1.1010);
        expect(candles[1].timestamp).toBe(60_000);
        expect(candles[1].open).toBe(1.1020);
    });

    it("gap-fills missing intervals with close-carried candles", () => {
        const ticks: TickData[] = [
            { symbol: "EURUSD", price: 1.1000, timestamp: 0 },
            { symbol: "EURUSD", price: 1.1050, timestamp: 180_000 }, // 3 minutes later
        ];
        const candles = aggregateTicks(ticks, 60_000);
        // Bucket 0, gap at 60k, gap at 120k, bucket at 180k
        expect(candles).toHaveLength(4);
        expect(candles[0].timestamp).toBe(0);
        expect(candles[1].timestamp).toBe(60_000);
        expect(candles[1].open).toBe(1.1000); // close-carried
        expect(candles[1].volume).toBe(0);
        expect(candles[2].timestamp).toBe(120_000);
        expect(candles[3].timestamp).toBe(180_000);
        expect(candles[3].open).toBe(1.1050);
    });

    it("handles unsorted ticks correctly", () => {
        const ticks: TickData[] = [
            { symbol: "EURUSD", price: 1.1010, timestamp: 30_000 },
            { symbol: "EURUSD", price: 1.1000, timestamp: 0 },
            { symbol: "EURUSD", price: 1.1020, timestamp: 60_000 },
        ];
        const candles = aggregateTicks(ticks, 60_000);
        expect(candles).toHaveLength(2);
        expect(candles[0].open).toBe(1.1000);
        expect(candles[0].close).toBe(1.1010);
    });

    it("accumulates volume", () => {
        const ticks: TickData[] = [
            { symbol: "EURUSD", price: 1.1, volume: 100, timestamp: 0 },
            { symbol: "EURUSD", price: 1.2, volume: 200, timestamp: 10_000 },
            { symbol: "EURUSD", price: 1.3, volume: 50, timestamp: 20_000 },
        ];
        const candles = aggregateTicks(ticks, 60_000);
        expect(candles[0].volume).toBe(350);
    });

    it("handles single tick", () => {
        const ticks: TickData[] = [
            { symbol: "EURUSD", price: 1.1000, timestamp: 5000 },
        ];
        const candles = aggregateTicks(ticks, 60_000);
        expect(candles).toHaveLength(1);
        expect(candles[0].open).toBe(1.1000);
        expect(candles[0].close).toBe(1.1000);
        expect(candles[0].high).toBe(1.1000);
        expect(candles[0].low).toBe(1.1000);
    });
});

describe("resampleCandles", () => {
    it("returns empty for no candles", () => {
        expect(resampleCandles([], 300_000)).toEqual([]);
    });

    it("merges M1 candles into M5", () => {
        const m1: OHLC[] = [
            { open: 1.10, high: 1.12, low: 1.09, close: 1.11, volume: 100, timestamp: 0 },
            { open: 1.11, high: 1.13, low: 1.10, close: 1.12, volume: 100, timestamp: 60_000 },
            { open: 1.12, high: 1.14, low: 1.11, close: 1.13, volume: 100, timestamp: 120_000 },
            { open: 1.13, high: 1.15, low: 1.12, close: 1.14, volume: 100, timestamp: 180_000 },
            { open: 1.14, high: 1.16, low: 1.13, close: 1.15, volume: 100, timestamp: 240_000 },
        ];
        const m5 = resampleCandles(m1, 300_000);
        expect(m5).toHaveLength(1);
        expect(m5[0].open).toBe(1.10);
        expect(m5[0].high).toBe(1.16);
        expect(m5[0].low).toBe(1.09);
        expect(m5[0].close).toBe(1.15);
        expect(m5[0].volume).toBe(500);
    });

    it("produces multiple resampled candles", () => {
        const m1: OHLC[] = [];
        for (let i = 0; i < 10; i++) {
            m1.push({
                open: 1.10 + i * 0.01,
                high: 1.10 + i * 0.01 + 0.005,
                low: 1.10 + i * 0.01 - 0.005,
                close: 1.10 + i * 0.01 + 0.002,
                volume: 100,
                timestamp: i * 60_000,
            });
        }
        const m5 = resampleCandles(m1, 300_000);
        expect(m5).toHaveLength(2);
        expect(m5[0].timestamp).toBe(0);
        expect(m5[1].timestamp).toBe(300_000);
    });

    it("handles single candle", () => {
        const candles: OHLC[] = [
            { open: 1.10, high: 1.12, low: 1.09, close: 1.11, volume: 50, timestamp: 0 },
        ];
        const resampled = resampleCandles(candles, 300_000);
        expect(resampled).toHaveLength(1);
        expect(resampled[0]).toEqual(candles[0]);
    });
});
