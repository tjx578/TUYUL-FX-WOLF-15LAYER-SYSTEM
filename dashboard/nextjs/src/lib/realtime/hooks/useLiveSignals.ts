"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { L12Verdict } from "@/types";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";

interface UseLiveSignalsResult {
  verdicts: L12Verdict[];
  status: WsConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
}

/**
 * useLiveSignals
 *
 * Bootstrap: caller provides initial verdicts from REST (useAllVerdicts / SWR).
 * Stream:    /ws/verdict and /ws/signals — PipelineResultUpdated + VerdictUpdated.
 * Merge:     replace list (backend sends full updated list on change).
 * Stale:     15s no message → isStale = true.
 */
export function useLiveSignals(
  initialVerdicts: L12Verdict[] = [],
  enabled = true
): UseLiveSignalsResult {
  const [verdicts, setVerdicts] = useState<L12Verdict[]>(initialVerdicts);
  const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
  const [isStale, setIsStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync initial snapshot from REST
  useEffect(() => {
    if (initialVerdicts.length > 0) setVerdicts(initialVerdicts);
  }, [initialVerdicts]);

  const resetStaleTimer = useCallback(() => {
    if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    setIsStale(false);
    staleTimerRef.current = setTimeout(() => {
      setIsStale(true);
      setStatus((s) => (s === "LIVE" ? "STALE" : s));
    }, STALE_THRESHOLDS_MS.verdicts);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    const controls = connectLiveUpdates({
      path: "/ws/verdict",
      onEvent: (event) => {
        if (event.type === "PipelineResultUpdated") {
          const payload = event.payload as unknown as L12Verdict;
          setVerdicts((prev) => {
            const idx = prev.findIndex((v) => v.symbol === payload.symbol);
            if (idx === -1) return [payload, ...prev];
            const next = [...prev];
            next[idx] = payload;
            return next;
          });
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

  return { verdicts, status, isStale, lastUpdatedAt };
}
