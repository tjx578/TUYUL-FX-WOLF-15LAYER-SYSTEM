/**
 * TUYUL FX Wolf-15 — Technical Indicator Computations (pure functions)
 *
 * Extracted from indicator.worker.ts so these can be:
 *   1. Imported by the Web Worker (off-thread)
 *   2. Tested directly in Vitest
 *   3. Used as fallback if Web Workers are unavailable
 */

import type { BollingerResult, MacdResult } from "./protocol";

export function computeSma(closes: number[], period: number): (number | null)[] {
    const result: (number | null)[] = new Array(closes.length).fill(null);
    if (closes.length < period) return result;

    let sum = 0;
    for (let i = 0; i < period; i++) sum += closes[i];
    result[period - 1] = sum / period;

    for (let i = period; i < closes.length; i++) {
        sum += closes[i] - closes[i - period];
        result[i] = sum / period;
    }
    return result;
}

export function computeEma(closes: number[], period: number): (number | null)[] {
    const result: (number | null)[] = new Array(closes.length).fill(null);
    if (closes.length < period) return result;

    let sum = 0;
    for (let i = 0; i < period; i++) sum += closes[i];
    let ema = sum / period;
    result[period - 1] = ema;

    const k = 2 / (period + 1);
    for (let i = period; i < closes.length; i++) {
        ema = closes[i] * k + ema * (1 - k);
        result[i] = ema;
    }
    return result;
}

export function computeRsi(closes: number[], period: number): (number | null)[] {
    const result: (number | null)[] = new Array(closes.length).fill(null);
    if (closes.length < period + 1) return result;

    let gainSum = 0;
    let lossSum = 0;

    for (let i = 1; i <= period; i++) {
        const change = closes[i] - closes[i - 1];
        if (change > 0) gainSum += change;
        else lossSum += Math.abs(change);
    }

    let avgGain = gainSum / period;
    let avgLoss = lossSum / period;

    result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

    for (let i = period + 1; i < closes.length; i++) {
        const change = closes[i] - closes[i - 1];
        const gain = change > 0 ? change : 0;
        const loss = change < 0 ? Math.abs(change) : 0;

        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;

        result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
    return result;
}

export function computeMacd(
    closes: number[],
    fastPeriod: number,
    slowPeriod: number,
    signalPeriod: number
): MacdResult {
    const len = closes.length;
    const macdLine: (number | null)[] = new Array(len).fill(null);
    const signalLine: (number | null)[] = new Array(len).fill(null);
    const histogram: (number | null)[] = new Array(len).fill(null);

    const fastEma = computeEma(closes, fastPeriod);
    const slowEma = computeEma(closes, slowPeriod);

    const macdValues: number[] = [];
    for (let i = 0; i < len; i++) {
        if (fastEma[i] !== null && slowEma[i] !== null) {
            const val = fastEma[i]! - slowEma[i]!;
            macdLine[i] = val;
            macdValues.push(val);
        }
    }

    if (macdValues.length >= signalPeriod) {
        const signalEma = computeEma(macdValues, signalPeriod);
        const macdStartIdx = len - macdValues.length;

        for (let i = 0; i < macdValues.length; i++) {
            if (signalEma[i] !== null) {
                signalLine[macdStartIdx + i] = signalEma[i];
                histogram[macdStartIdx + i] = macdValues[i] - signalEma[i]!;
            }
        }
    }

    return { indicator: "macd", macdLine, signalLine, histogram };
}

export function computeBollinger(
    closes: number[],
    period: number,
    stdDev: number
): BollingerResult {
    const len = closes.length;
    const upper: (number | null)[] = new Array(len).fill(null);
    const middle: (number | null)[] = new Array(len).fill(null);
    const lower: (number | null)[] = new Array(len).fill(null);

    if (closes.length < period) return { indicator: "bollinger", upper, middle, lower };

    for (let i = period - 1; i < len; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += closes[j];
        const mean = sum / period;

        let sqSum = 0;
        for (let j = i - period + 1; j <= i; j++) {
            const diff = closes[j] - mean;
            sqSum += diff * diff;
        }
        const sd = Math.sqrt(sqSum / period);

        middle[i] = mean;
        upper[i] = mean + stdDev * sd;
        lower[i] = mean - stdDev * sd;
    }

    return { indicator: "bollinger", upper, middle, lower };
}
