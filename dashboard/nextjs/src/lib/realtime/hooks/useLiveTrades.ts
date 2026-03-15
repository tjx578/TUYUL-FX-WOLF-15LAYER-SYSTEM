"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { Trade } from "@/types";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { mergeList } from "@/lib/realtime/merge";

interface UseLiveTradesResult {
  trades: Trade[];
  status: WsConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
}

/**
 * useLiveTrades
 *
 * Bootstrap: caller provides initial trades from REST (via useActiveTrades / SWR).
 * Stream:    /ws/trades — individual Trade delta events.
 * Merge:     mergeList — upserts by trade.id.
 * Stale:     8s no message → isStale = true.
 */
export function useLiveTrades(
  initialTrades: Trade[] = [],
  enabled = true
): UseLiveTradesResult {
  const [trades, setTrades] = useState<Trade[]>(initialTrades);
  const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
  const [isStale, setIsStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync initial snapshot when SWR resolves
  useEffect(() => {
    if (initialTrades.length > 0) {
      setTrades(initialTrades);
    }
  }, [initialTrades]);

  const resetStaleTimer = useCallback(() => {
    if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    setIsStale(false);
    staleTimerRef.current = setTimeout(() => {
      setIsStale(true);
      setStatus((s) => (s === "LIVE" ? "STALE" : s));
    }, STALE_THRESHOLDS_MS.trades);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    const controls = connectLiveUpdates({
      path: "/ws/trades",
      onEvent: (event) => {
        if (event.type === "ExecutionStateUpdated") {
          setTrades((prev) =>
            mergeList(prev, event.payload.trade as unknown as Trade)
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
      onError: () => setStatus("DEGRADED"),
    });

    return () => {
      controls.close();
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, resetStaleTimer]);

  return { trades, status, isStale, lastUpdatedAt };
}
