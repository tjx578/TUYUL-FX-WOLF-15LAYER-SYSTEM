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
 *
 * Race-safe: once WS delivers data, stale REST snapshots are ignored to prevent
 * older REST responses from overwriting newer WS deltas.
 */
export function useLiveTrades(
  initialTrades: Trade[] = [],
  enabled = true,
  onSeqGap?: () => void
): UseLiveTradesResult {
  const [trades, setTrades] = useState<Trade[]>(initialTrades);
  const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
  const [isStale, setIsStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Track whether WS has delivered data — prevents stale REST from overwriting
  const wsActiveRef = useRef(false);

  // Sync initial snapshot when SWR resolves, but only if WS hasn't pushed newer data
  useEffect(() => {
    if (initialTrades.length > 0 && !wsActiveRef.current) {
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
    // Reset WS tracking on fresh connection cycle
    wsActiveRef.current = false;

    const controls = connectLiveUpdates({
      path: "/ws/trades",
      onEvent: (event) => {
        if (event.type === "ExecutionStateUpdated") {
          wsActiveRef.current = true;
          setTrades((prev) =>
            mergeList(prev, event.payload.trade as unknown as Trade, (t) => t.trade_id)
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
          // Allow REST to sync again after disconnect
          wsActiveRef.current = false;
        }
      },
      onDegradation: () => setStatus("DEGRADED"),
      onSeqGap: () => {
        // On gap, allow REST to re-sync since we may have missed data
        wsActiveRef.current = false;
        onSeqGap?.();
      },
      onError: () => setStatus("DEGRADED"),
    });

    return () => {
      controls.close();
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, resetStaleTimer]);

  return { trades, status, isStale, lastUpdatedAt };
}
