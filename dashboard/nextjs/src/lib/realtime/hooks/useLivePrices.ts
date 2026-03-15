"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { PriceData } from "@/types";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { mergeMap } from "@/lib/realtime/merge";

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
 */
export function useLivePrices(enabled = true): UseLivePricesResult {
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

    const controls = connectLiveUpdates({
      path: "/ws/prices",
      onEvent: (event) => {
        if (event.type === "PriceUpdated" || event.type === "PricesSnapshot") {
          const payload = event.payload as Record<string, PriceData>;
          setPriceMap((prev) => mergeMap(prev, payload));
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
      onDegradation: () => {
        setStatus("DEGRADED");
      },
      onError: () => {
        setStatus("DEGRADED");
      },
    });

    return () => {
      controls.close();
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, resetStaleTimer]);

  return { priceMap, status, isStale, lastUpdatedAt };
}
