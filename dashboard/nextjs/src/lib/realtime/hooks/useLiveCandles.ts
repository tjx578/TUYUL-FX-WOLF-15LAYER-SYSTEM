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

type TimeframeKey = "M1" | "M5" | "M15" | "H1";

const TIMEFRAME_TO_INTERVAL_MS: Record<TimeframeKey, number> = {
    M1: 60_000,
    M5: 5 * 60_000,
    M15: 15 * 60_000,
    H1: 60 * 60_000,
};

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

export function useLiveCandles(
    symbol: string | undefined,
    timeframe: TimeframeKey = "M1"
): UseLiveCandlesResult {
    const [rawCandles, setRawCandles] = useState<CandleData[]>([]);
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
                        setRawCandles(payload.candles.slice(-MAX_CANDLE_HISTORY));
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

    useEffect(() => {
        let cancelled = false;

        if (!symbol || rawCandles.length === 0) {
            setCandles([]);
            return;
        }

        const targetIntervalMs = TIMEFRAME_TO_INTERVAL_MS[timeframe] ?? TIMEFRAME_TO_INTERVAL_MS.M1;
        if (targetIntervalMs === TIMEFRAME_TO_INTERVAL_MS.M1) {
            setCandles(rawCandles);
            return;
        }

        const ohlcInput: OHLC[] = rawCandles.map((c) => ({
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
            volume: c.volume ?? 0,
            timestamp: c.timestamp,
        }));

        void resampleCandles(symbol, ohlcInput, targetIntervalMs)
            .then((resampled) => {
                if (cancelled) return;
                setCandles(resampled.map((o) => ohlcToCandle(o, symbol, timeframe)));
            })
            .catch(() => {
                if (cancelled) return;
                setCandles(rawCandles);
            });

        return () => {
            cancelled = true;
        };
    }, [rawCandles, symbol, timeframe, resampleCandles]);

    const resample = useCallback(
        async (targetIntervalMs: number): Promise<CandleData[]> => {
            if (rawCandles.length === 0 || !symbol) return [];
            const ohlcInput: OHLC[] = rawCandles.map((c) => ({
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
        [rawCandles, symbol, resampleCandles]
    );

    return { candles, forming: timeframe === "M1" ? forming : null, resample, status, isStale };
}
