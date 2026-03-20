/**
 * TUYUL FX Wolf-15 — Indicator Worker Hook
 *
 * React hook that creates and manages the indicator computation Web Worker.
 * Auto-terminates when the component unmounts.
 *
 * Usage:
 *   const { computeSma, computeRsi, computeMacd } = useIndicatorWorker();
 *   const sma = await computeSma(closes, 20);
 */

"use client";

import { useEffect, useRef, useCallback } from "react";
import { createWorkerManager, type WorkerManager } from "./workerManager";
import type {
    BollingerResult,
    EmaResult,
    IndicatorRequest,
    IndicatorResponse,
    IndicatorResultPayload,
    MacdResult,
    RsiResult,
    SmaResult,
} from "@/workers/protocol";

let idCounter = 0;
function nextId(): string {
    return `ind-${++idCounter}-${Date.now()}`;
}

export function useIndicatorWorker() {
    const mgrRef = useRef<WorkerManager<IndicatorRequest, IndicatorResponse> | null>(null);

    function getManager() {
        if (!mgrRef.current || !mgrRef.current.alive) {
            mgrRef.current = createWorkerManager<IndicatorRequest, IndicatorResponse>(
                () => new Worker(new URL("../../workers/indicator.worker.ts", import.meta.url))
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

    const compute = useCallback(
        (req: Omit<IndicatorRequest, "id">): Promise<IndicatorResultPayload> => {
            return getManager()
                .request({ ...req, id: nextId() } as IndicatorRequest)
                .then((r) => r.result);
        },
        []
    );

    const computeSma = useCallback(
        (closes: number[], period = 20): Promise<SmaResult> =>
            compute({ type: "compute", indicator: "sma", payload: { closes, period } }) as Promise<SmaResult>,
        [compute]
    );

    const computeEma = useCallback(
        (closes: number[], period = 20): Promise<EmaResult> =>
            compute({ type: "compute", indicator: "ema", payload: { closes, period } }) as Promise<EmaResult>,
        [compute]
    );

    const computeRsi = useCallback(
        (closes: number[], period = 14): Promise<RsiResult> =>
            compute({ type: "compute", indicator: "rsi", payload: { closes, period } }) as Promise<RsiResult>,
        [compute]
    );

    const computeMacd = useCallback(
        (
            closes: number[],
            fastPeriod = 12,
            slowPeriod = 26,
            signalPeriod = 9
        ): Promise<MacdResult> =>
            compute({
                type: "compute",
                indicator: "macd",
                payload: { closes, fastPeriod, slowPeriod, signalPeriod },
            }) as Promise<MacdResult>,
        [compute]
    );

    const computeBollinger = useCallback(
        (closes: number[], period = 20, stdDev = 2): Promise<BollingerResult> =>
            compute({
                type: "compute",
                indicator: "bollinger",
                payload: { closes, period, stdDev },
            }) as Promise<BollingerResult>,
        [compute]
    );

    return { compute, computeSma, computeEma, computeRsi, computeMacd, computeBollinger };
}
