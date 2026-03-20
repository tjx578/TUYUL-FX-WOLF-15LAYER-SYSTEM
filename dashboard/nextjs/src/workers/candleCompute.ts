/**
 * TUYUL FX Wolf-15 — Candle Aggregation (pure functions)
 *
 * Extracted from candle.worker.ts so these can be:
 *   1. Imported by the Web Worker (off-thread)
 *   2. Tested directly in Vitest (no Worker instantiation needed)
 *   3. Used as fallback on browsers without Web Worker support
 */

import type { OHLC, TickData } from "./protocol";

/**
 * Aggregate raw ticks into OHLC candles at a given interval.
 * Gap-fills missing intervals with close-carried candles.
 */
export function aggregateTicks(ticks: TickData[], intervalMs: number): OHLC[] {
    if (ticks.length === 0) return [];

    const sorted = [...ticks].sort((a, b) => a.timestamp - b.timestamp);

    const candles: OHLC[] = [];
    let bucketStart = Math.floor(sorted[0].timestamp / intervalMs) * intervalMs;
    let open = sorted[0].price;
    let high = sorted[0].price;
    let low = sorted[0].price;
    let close = sorted[0].price;
    let volume = sorted[0].volume ?? 0;

    for (let i = 1; i < sorted.length; i++) {
        const tick = sorted[i];
        const tickBucket = Math.floor(tick.timestamp / intervalMs) * intervalMs;

        if (tickBucket !== bucketStart) {
            candles.push({ open, high, low, close, volume, timestamp: bucketStart });

            // Fill gaps with close-carried candles
            let gapStart = bucketStart + intervalMs;
            while (gapStart < tickBucket) {
                candles.push({
                    open: close,
                    high: close,
                    low: close,
                    close,
                    volume: 0,
                    timestamp: gapStart,
                });
                gapStart += intervalMs;
            }

            bucketStart = tickBucket;
            open = tick.price;
            high = tick.price;
            low = tick.price;
            close = tick.price;
            volume = tick.volume ?? 0;
        } else {
            if (tick.price > high) high = tick.price;
            if (tick.price < low) low = tick.price;
            close = tick.price;
            volume += tick.volume ?? 0;
        }
    }

    candles.push({ open, high, low, close, volume, timestamp: bucketStart });
    return candles;
}

/**
 * Resample lower-timeframe candles into a higher-timeframe.
 * E.g. M1 → M5, M5 → M15, etc.
 */
export function resampleCandles(candles: OHLC[], targetIntervalMs: number): OHLC[] {
    if (candles.length === 0) return [];

    const sorted = [...candles].sort((a, b) => a.timestamp - b.timestamp);
    const result: OHLC[] = [];

    let bucketStart =
        Math.floor(sorted[0].timestamp / targetIntervalMs) * targetIntervalMs;
    let open = sorted[0].open;
    let high = sorted[0].high;
    let low = sorted[0].low;
    let close = sorted[0].close;
    let volume = sorted[0].volume;

    for (let i = 1; i < sorted.length; i++) {
        const c = sorted[i];
        const cBucket =
            Math.floor(c.timestamp / targetIntervalMs) * targetIntervalMs;

        if (cBucket !== bucketStart) {
            result.push({ open, high, low, close, volume, timestamp: bucketStart });
            bucketStart = cBucket;
            open = c.open;
            high = c.high;
            low = c.low;
            close = c.close;
            volume = c.volume;
        } else {
            if (c.high > high) high = c.high;
            if (c.low < low) low = c.low;
            close = c.close;
            volume += c.volume;
        }
    }

    result.push({ open, high, low, close, volume, timestamp: bucketStart });
    return result;
}
