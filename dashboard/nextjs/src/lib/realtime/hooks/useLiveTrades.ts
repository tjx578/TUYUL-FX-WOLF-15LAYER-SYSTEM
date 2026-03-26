"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { Trade } from "@/types";
import { subscribe } from "@/lib/realtime/multiplexer";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { mergeList } from "@/lib/realtime/merge";
import { createRafListBatcher } from "@/lib/realtime/rafBatcher";

interface UseLiveTradesResult {
  trades: Trade[];
  status: WsConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object";
}

function isTrade(value: unknown): value is Trade {
  if (!isRecord(value)) return false;
  return (
    typeof value.trade_id === "string" &&
    typeof value.account_id === "string" &&
    typeof value.signal_id === "string" &&
    typeof value.pair === "string" &&
    typeof value.direction === "string" &&
    typeof value.status === "string" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

/**
 * useLiveTrades
 *
 * Bootstrap: caller provides initial trades from REST (via useActiveTrades / SWR).
 * Stream:    multiplexed /ws/live — ExecutionStateUpdated events.
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
  const wsActiveRef = useRef(false);

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
    wsActiveRef.current = false;

    // RAF batcher: collapses multiple ExecutionStateUpdated events within the
    // same animation frame (~16ms) into a single setState call, preventing
    // a re-render per WS message during burst sequences.
    const batcher = createRafListBatcher<Trade>({
      getKey: (t) => t.trade_id,
      onFlush: (items) => {
        setTrades((prev) => {
          let next = prev;
          for (const item of items) {
            next = mergeList(next, item, (t) => t.trade_id);
          }
          return next;
        });
        setLastUpdatedAt(Date.now());
        resetStaleTimer();
      },
    });

    const unsub = subscribe({
      filter: (e) => e.type === "ExecutionStateUpdated" || e.type === "TradeUpdated" || e.type === "TradeSnapshot",
      onEvent: (event) => {
        if (event.type === "ExecutionStateUpdated") {
          if (!isRecord(event.payload) || !isTrade(event.payload.trade)) return;
          batcher.push(event.payload.trade);
        }
      },
      onStatusChange: (s) => {
        setStatus(s);
        if (s === "LIVE") resetStaleTimer();
        if (s === "DISCONNECTED") {
          if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
          wsActiveRef.current = false;
        }
      },
      onDegradation: () => {
        setStatus((prev) => (prev === "LIVE" ? "DEGRADED" : prev));
      },
      onSeqGap: () => {
        onSeqGap?.();
      },
      onError: () => setStatus("DEGRADED"),
    });

    return () => {
      unsub();
      batcher.dispose();
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, resetStaleTimer]);

  return { trades, status, isStale, lastUpdatedAt };
}
