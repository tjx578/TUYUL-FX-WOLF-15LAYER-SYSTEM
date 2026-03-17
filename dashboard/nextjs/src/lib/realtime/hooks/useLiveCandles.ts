"use client";

/**
 * TUYUL FX Wolf-15 — useLiveCandles
 *
 * Consumes CandleSnapshot + CandleForming WebSocket events via the
 * multiplexer, then offloads resampling to the candle Web Worker when
 * the user switches timeframes.
 *
 * Data flow:
 *   WS CandleSnapshot → history state (per symbol)
 *   WS CandleForming  → forming candle state (per symbol, last-write-wins)
 *   User changes TF   → resampleCandles via Web Worker (off main thread)
 *
 * Usage:
 *   const { candles, forming, resample, status } = useLiveCandles("EURUSD");
 */

import { useEffect, useRef, useState, useCallback } from "react";
import type { CandleData } from "@/types";
import { subscribe } from "@/lib/realtime/multiplexer";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { useCandleWorker } from "@/lib/workers";
import type { OHLC } from "@/workers/protocol";

interface UseLiveCandlesResult {
    /** Completed candle history for the symbol. */
    candles: CandleData[];
    /** Currently forming (partial) candle, if any. */
    forming: CandleData | null;
    /** Resample candle history to a different timeframe (runs in Web Worker). */
    resample: (targetIntervalMs: number) => Promise<CandleData[]>;
    status: WsConnectionStatus;
    isStale: boolean;
}

const MAX_CANDLE_HISTORY = 1000;

function ohlcToCandle(o: OHLC, symbol: string, timeframe: string): CandleData {
    return {
        symbol,
        timeframe,
        open: o.open,
        high: o.high,
        low: o.low,
        close: o.close,
        volume: o.volume,
        timestamp: o.timestamp,
    };
}

export function useLiveCandles(symbol: string | undefined): UseLiveCandlesResult {
    const [candles, setCandles] = useState<CandleData[]>([]);
    const [forming, setForming] = useState<CandleData | null>(null);
    const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
    const [isStale, setIsStale] = useState(false);
    const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const { resampleCandles } = useCandleWorker();

    const resetStaleTimer = useCallback(() => {
        if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        setIsStale(false);
        staleTimerRef.current = setTimeout(() => {
            setIsStale(true);
            setStatus((s) => (s === "LIVE" ? "STALE" : s));
        }, STALE_THRESHOLDS_MS.candles ?? 15_000);
    }, []);

    useEffect(() => {
        if (!symbol) return;

        const unsub = subscribe({
            filter: (e) =>
                (e.type === "CandleSnapshot" || e.type === "CandleForming") &&
                (e.payload as Record<string, unknown>).symbol === symbol,
            onEvent: (event) => {
                if (event.type === "CandleSnapshot") {
                    const payload = event.payload as { candles?: CandleData[] };
                    if (payload.candles) {
                        setCandles(payload.candles.slice(-MAX_CANDLE_HISTORY));
                    }
                    resetStaleTimer();
                } else if (event.type === "CandleForming") {
                    setForming(event.payload as unknown as CandleData);
                    resetStaleTimer();
                }
            },
            onStatusChange: (s) => {
                setStatus(s);
                if (s === "LIVE") resetStaleTimer();
            },
        });

        return () => {
            unsub();
            if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        };
    }, [symbol, resetStaleTimer]);

    const resample = useCallback(
        async (targetIntervalMs: number): Promise<CandleData[]> => {
            if (candles.length === 0 || !symbol) return [];
            const ohlcInput: OHLC[] = candles.map((c) => ({
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
                volume: c.volume ?? 0,
                timestamp: c.timestamp,
            }));
            const resampled = await resampleCandles(symbol, ohlcInput, targetIntervalMs);
            const tf = `${targetIntervalMs / 60_000}m`;
            return resampled.map((o) => ohlcToCandle(o, symbol, tf));
        },
        [candles, symbol, resampleCandles]
    );

    return { candles, forming, resample, status, isStale };
}
