"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { PriceData } from "@/types";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { mergeMap } from "@/lib/realtime/merge";
import { createRafBatcher } from "@/lib/realtime/rafBatcher";

interface UseLivePricesResult {
  priceMap: Record<string, PriceData>;
  status: WsConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
}

/**
 * useLivePrices
 *
 * Bootstrap: REST snapshot via SWR (provided externally or inline fetch).
 * Stream:    /ws/prices — Record<string, PriceData> deltas.
 * Merge:     mergeMap — WS delta keys override snapshot keys.
 * Stale:     3s no message → isStale = true.
 *
 * @param enabled - Whether to connect to the price stream.
 * @param rafBatch - Enable RAF batching for ultra-high symbol counts (50+).
 *                   When true, price updates are collapsed to one setState per frame.
 */
export function useLivePrices(enabled = true, rafBatch = false, onSeqGap?: () => void): UseLivePricesResult {
  const [priceMap, setPriceMap] = useState<Record<string, PriceData>>({});
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
    }, STALE_THRESHOLDS_MS.prices);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    // Optional RAF batcher for ultra-high symbol counts
    const batcher = rafBatch
      ? createRafBatcher<PriceData>({
        onFlush: (batch) => {
          setPriceMap((prev) => mergeMap(prev, batch));
          setLastUpdatedAt(Date.now());
          resetStaleTimer();
        },
      })
      : null;

    const controls = connectLiveUpdates({
      path: "/ws/prices",
      onEvent: (event) => {
        if (event.type === "PriceUpdated" || event.type === "PricesSnapshot") {
          const payload = event.payload as Record<string, PriceData>;

          if (batcher) {
            // RAF-batched: queue each symbol separately for last-write-wins collapse
            for (const [symbol, data] of Object.entries(payload)) {
              batcher.push(symbol, data);
            }
          } else {
            // Direct dispatch (default path for low symbol counts)
            setPriceMap((prev) => mergeMap(prev, payload));
            setLastUpdatedAt(Date.now());
            resetStaleTimer();
          }
        }
      },
      onStatusChange: (s) => {
        setStatus(s);
        if (s === "LIVE") resetStaleTimer();
        if (s === "DISCONNECTED" || s === "DEGRADED") {
          if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
        }
      },
      onDegradation: () => {
        setStatus("DEGRADED");
      },
      onSeqGap: () => onSeqGap?.(),
      onError: () => {
        setStatus("DEGRADED");
      },
    });

    return () => {
      controls.close();
      batcher?.dispose();
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, rafBatch, resetStaleTimer]);

  return { priceMap, status, isStale, lastUpdatedAt };
}
