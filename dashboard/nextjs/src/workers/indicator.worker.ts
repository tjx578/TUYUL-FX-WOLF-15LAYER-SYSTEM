/**
 * TUYUL FX Wolf-15 — Technical Indicator Web Worker
 *
 * Offloads indicator computation (SMA, EMA, RSI, MACD, Bollinger Bands) from
 * the main thread. Receives close-price arrays and returns computed indicator
 * series aligned to the input length (null-padded for warmup periods).
 *
 * Runs in a dedicated Web Worker — no DOM access, no shared state.
 */

import type {
    IndicatorRequest,
    IndicatorResponse,
    IndicatorResultPayload,
    WorkerErrorResponse,
} from "./protocol";
import {
    computeSma,
    computeEma,
    computeRsi,
    computeMacd,
    computeBollinger,
} from "./indicatorCompute";

// ─── Message Handler ───────────────────────────────────────

const ctx = self as unknown as Worker;

ctx.onmessage = (e: MessageEvent<IndicatorRequest>) => {
    const msg = e.data;

    try {
        if (msg.type !== "compute") {
            const errResp: WorkerErrorResponse = {
                type: "error",
                id: msg.id ?? "unknown",
                error: `Unknown message type: ${msg.type}`,
            };
            ctx.postMessage(errResp);
            return;
        }

        const { closes, period = 14 } = msg.payload;
        let result: IndicatorResultPayload;

        switch (msg.indicator) {
            case "sma":
                result = { indicator: "sma", values: computeSma(closes, period) };
                break;
            case "ema":
                result = { indicator: "ema", values: computeEma(closes, period) };
                break;
            case "rsi":
                result = { indicator: "rsi", values: computeRsi(closes, period) };
                break;
            case "macd":
                result = computeMacd(
                    closes,
                    msg.payload.fastPeriod ?? 12,
                    msg.payload.slowPeriod ?? 26,
                    msg.payload.signalPeriod ?? 9,
                );
                break;
            case "bollinger":
                result = computeBollinger(closes, period, msg.payload.stdDev ?? 2);
                break;
            default: {
                const errResp: WorkerErrorResponse = {
                    type: "error",
                    id: msg.id,
                    error: `Unknown indicator: ${msg.indicator}`,
                };
                ctx.postMessage(errResp);
                return;
            }
        }

        const response: IndicatorResponse = {
            type: "compute",
            id: msg.id,
            result,
        };
        ctx.postMessage(response);
    } catch (err) {
        const errResp: WorkerErrorResponse = {
            type: "error",
            id: msg.id ?? "unknown",
            error: err instanceof Error ? err.message : String(err),
        };
        ctx.postMessage(errResp);
    }
};
