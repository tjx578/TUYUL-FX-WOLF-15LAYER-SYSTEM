/**
 * TUYUL FX Wolf-15 — Candle Worker Hook
 *
 * React hook that creates and manages the candle aggregation Web Worker.
 * Auto-terminates when the component unmounts.
 *
 * Usage:
 *   const { aggregateTicks, resampleCandles } = useCandleWorker();
 *   const candles = await aggregateTicks("EURUSD", ticks, 60_000);
 */

"use client";

import { useEffect, useRef, useCallback } from "react";
import { createWorkerManager, type WorkerManager } from "./workerManager";
import type {
    CandleRequest,
    CandleWorkerResponse,
    OHLC,
    TickData,
} from "@/workers/protocol";

let idCounter = 0;
function nextId(): string {
    return `candle-${++idCounter}-${Date.now()}`;
}

export function useCandleWorker() {
    const mgrRef = useRef<WorkerManager<CandleRequest, CandleWorkerResponse> | null>(null);

    // Lazily create on first access, so SSR never instantiates
    function getManager() {
        if (!mgrRef.current || !mgrRef.current.alive) {
            mgrRef.current = createWorkerManager<CandleRequest, CandleWorkerResponse>(
                () => new Worker(new URL("../../workers/candle.worker.ts", import.meta.url))
            );
        }
        return mgrRef.current;
    }

    useEffect(() => {
        return () => {
            mgrRef.current?.terminate();
            mgrRef.current = null;
        };
    }, []);

    const aggregateTicks = useCallback(
        (symbol: string, ticks: TickData[], intervalMs: number): Promise<OHLC[]> => {
            return getManager()
                .request({
                    type: "aggregate_ticks",
                    id: nextId(),
                    payload: { symbol, ticks, intervalMs },
                })
                .then((r) => r.candles);
        },
        []
    );

    const resampleCandles = useCallback(
        (symbol: string, candles: OHLC[], targetIntervalMs: number): Promise<OHLC[]> => {
            return getManager()
                .request({
                    type: "resample",
                    id: nextId(),
                    payload: { symbol, candles, targetIntervalMs },
                })
                .then((r) => r.candles);
        },
        []
    );

    return { aggregateTicks, resampleCandles };
}
