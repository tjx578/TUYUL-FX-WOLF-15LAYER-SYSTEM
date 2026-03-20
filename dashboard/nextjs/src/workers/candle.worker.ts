/**
 * TUYUL FX Wolf-15 — Candle Aggregation Web Worker
 *
 * Offloads tick-to-OHLC aggregation and timeframe resampling from the main
 * thread. Receives raw tick arrays or lower-timeframe candle arrays and
 * returns aggregated OHLC bars.
 *
 * Runs in a dedicated Web Worker — no DOM access, no shared state.
 */

import type {
    CandleRequest,
    CandleWorkerResponse,
    WorkerErrorResponse,
} from "./protocol";
import { aggregateTicks, resampleCandles } from "./candleCompute";

// ─── Message Handler ───────────────────────────────────────

const ctx = self as unknown as Worker;

ctx.onmessage = (e: MessageEvent<CandleRequest>) => {
    const msg = e.data;

    try {
        switch (msg.type) {
            case "aggregate_ticks": {
                const { symbol, ticks, intervalMs } = msg.payload;
                const candles = aggregateTicks(ticks, intervalMs);
                const response: CandleWorkerResponse = {
                    type: "aggregate_ticks",
                    id: msg.id,
                    symbol,
                    candles,
                };
                ctx.postMessage(response);
                break;
            }
            case "resample": {
                const { symbol, candles: sourceCandles, targetIntervalMs } =
                    msg.payload;
                const candles = resampleCandles(sourceCandles, targetIntervalMs);
                const response: CandleWorkerResponse = {
                    type: "resample",
                    id: msg.id,
                    symbol,
                    candles,
                };
                ctx.postMessage(response);
                break;
            }
            default: {
                const errResp: WorkerErrorResponse = {
                    type: "error",
                    id: (msg as CandleRequest).id ?? "unknown",
                    error: `Unknown message type: ${(msg as CandleRequest).type}`,
                };
                ctx.postMessage(errResp);
            }
        }
    } catch (err) {
        const errResp: WorkerErrorResponse = {
            type: "error",
            id: msg.id ?? "unknown",
            error: err instanceof Error ? err.message : String(err),
        };
        ctx.postMessage(errResp);
    }
};
