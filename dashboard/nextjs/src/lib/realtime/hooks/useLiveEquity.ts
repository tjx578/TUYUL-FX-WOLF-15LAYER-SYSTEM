"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { DrawdownData } from "@/types";
import { subscribe } from "@/lib/realtime/multiplexer";
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
 * Stream:  multiplexed /ws/live — EquityUpdated events every 2s.
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

        const unsub = subscribe({
            filter: (e) => e.type === "EquityUpdated",
            onEvent: (event) => {
                const raw = event.payload as Record<string, unknown>;
                if (!raw) return;
                // Filter by accountId client-side if specified
                if (accountId && raw.account_id !== accountId) return;
                const payload = raw as unknown as DrawdownData;
                setHistory((prev) =>
                    [...prev, payload].slice(-maxPointsRef.current)
                );
                setLastUpdatedAt(Date.now());
                resetStaleTimer();
            },
            onStatusChange: (s) => {
                setStatus(s);
                if (s === "LIVE") resetStaleTimer();
                if (s === "DISCONNECTED") {
                    if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
                }
            },
            onDegradation: () => {
                setStatus((prev) => (prev === "LIVE" ? "DEGRADED" : prev));
            },
            onSeqGap: () => onSeqGap?.(),
            onError: () => setStatus("DEGRADED"),
        });

        return () => {
            unsub();
            if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        };
    }, [enabled, accountId, resetStaleTimer]);

    return { history, status, isStale, lastUpdatedAt };
}
