"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { DrawdownData } from "@/types";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";

interface UseLiveEquityResult {
    history: DrawdownData[];
    status: WsConnectionStatus;
    isStale: boolean;
    lastUpdatedAt: number | null;
}

/**
 * useLiveEquity
 *
 * Stream:  /ws/equity — equity.update events every 2s.
 * Accumulates DrawdownData points into a capped history array.
 * Stale:   10s no message → isStale = true.
 */
export function useLiveEquity(
    accountId?: string,
    maxPoints = 500,
    enabled = true,
    onSeqGap?: () => void
): UseLiveEquityResult {
    const [history, setHistory] = useState<DrawdownData[]>([]);
    const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
    const [isStale, setIsStale] = useState(false);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

    const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const maxPointsRef = useRef(maxPoints);
    maxPointsRef.current = maxPoints;

    const resetStaleTimer = useCallback(() => {
        if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        setIsStale(false);
        staleTimerRef.current = setTimeout(() => {
            setIsStale(true);
            setStatus((s) => (s === "LIVE" ? "STALE" : s));
        }, STALE_THRESHOLDS_MS.equity);
    }, []);

    useEffect(() => {
        if (!enabled) return;

        const path = accountId
            ? `/ws/equity?account_id=${accountId}`
            : "/ws/equity";

        const controls = connectLiveUpdates({
            path,
            onEvent: (event) => {
                const payload = event.payload as unknown as DrawdownData;
                if (payload) {
                    setHistory((prev) =>
                        [...prev, payload].slice(-maxPointsRef.current)
                    );
                    setLastUpdatedAt(Date.now());
                    resetStaleTimer();
                }
            },
            onStatusChange: (s) => {
                setStatus(s);
                if (s === "LIVE") resetStaleTimer();
                if (s === "DISCONNECTED" || s === "DEGRADED") {
                    if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
                }
            },
            onDegradation: () => setStatus("DEGRADED"),
            onSeqGap: () => onSeqGap?.(),
            onError: () => setStatus("DEGRADED"),
        });

        return () => {
            controls.close();
            if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        };
    }, [enabled, accountId, resetStaleTimer]);

    return { history, status, isStale, lastUpdatedAt };
}
