"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { AlertEvent } from "@/types";
import { subscribe } from "@/lib/realtime/multiplexer";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";

interface UseLiveAlertsResult {
    alerts: AlertEvent[];
    status: WsConnectionStatus;
    isStale: boolean;
    lastUpdatedAt: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === "object";
}

function isAlertEvent(value: unknown): value is AlertEvent {
    if (!isRecord(value)) return false;
    return (
        typeof value.alert_id !== "string" ||
        typeof value.type !== "string" ||
        typeof value.severity !== "string" ||
        typeof value.message !== "string" ||
        typeof value.timestamp !== "string"
    ) === false;
}

/**
 * useLiveAlerts
 *
 * Stream:  multiplexed /ws/live — alert event broadcasts.
 * Accumulates AlertEvents in reverse-chronological order (newest first), capped at 50.
 * Stale:   30s no message → isStale = true (alerts are event-driven, not periodic).
 */
export function useLiveAlerts(enabled = true, onSeqGap?: () => void): UseLiveAlertsResult {
    const [alerts, setAlerts] = useState<AlertEvent[]>([]);
    const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
    const [isStale, setIsStale] = useState(false);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

    const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const resetStaleTimer = useCallback(() => {
        if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        setIsStale(false);
        staleTimerRef.current = setTimeout(() => {
            setIsStale(true);
            setStatus((s) => (s === "LIVE" ? "STALE" : s));
        }, STALE_THRESHOLDS_MS.alerts);
    }, []);

    useEffect(() => {
        if (!enabled) return;

        const unsub = subscribe({
            // Alert events — accept any event type that looks like an alert
            // (backend may use various event types for alerts)
            onEvent: (event) => {
                const payload: unknown = event.payload;
                if (!isAlertEvent(payload)) return;
                setAlerts((prev) => [payload, ...prev].slice(0, 50));
                setLastUpdatedAt(Date.now());
                resetStaleTimer();
            },
            filter: (e) => {
                const t = e.type;
                return t === "AlertCreated" || t === "AlertUpdated" || t === "SystemStatusUpdated";
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
    }, [enabled, resetStaleTimer]);

    return { alerts, status, isStale, lastUpdatedAt };
}
