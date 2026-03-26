"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { RiskSnapshot } from "@/types";
import { subscribe } from "@/lib/realtime/multiplexer";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { mergeSingle } from "@/lib/realtime/merge";

interface UseLiveRiskResult {
  snapshot: RiskSnapshot | null;
  status: WsConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
}

/**
 * useLiveRisk
 *
 * Bootstrap: caller provides initial snapshot from REST (useRiskSnapshot / SWR).
 * Stream:    multiplexed /ws/live — RiskUpdated events.
 * Merge:     mergeSingle — stale guard by timestamp.
 * Stale:     10s no message → isStale = true.
 *
 * Race-safe: once WS delivers a RiskUpdated event, stale REST snapshots
 * are ignored to prevent older REST responses from overwriting newer WS data.
 */
export function useLiveRisk(
  initialSnapshot: RiskSnapshot | null = null,
  accountId?: string,
  enabled = true,
  onSeqGap?: () => void
): UseLiveRiskResult {
  const [snapshot, setSnapshot] = useState<RiskSnapshot | null>(initialSnapshot);
  const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
  const [isStale, setIsStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsActiveRef = useRef(false);

  // Sync initial snapshot
  useEffect(() => {
    if (initialSnapshot) setSnapshot(initialSnapshot);
  }, [initialSnapshot]);

  const resetStaleTimer = useCallback(() => {
    if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    setIsStale(false);
    staleTimerRef.current = setTimeout(() => {
      setIsStale(true);
      setStatus((s) => (s === "LIVE" ? "STALE" : s));
    }, STALE_THRESHOLDS_MS.risk);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    wsActiveRef.current = false;

    const unsub = subscribe({
      filter: (e) => e.type === "RiskUpdated",
      onEvent: (event) => {
        if (event.type === "RiskUpdated") {
          // Filter by accountId client-side if specified
          const payload = event.payload;
          if (accountId && payload && payload.account_id !== accountId) return;
          setSnapshot((prev) => mergeSingle(prev, payload));
          setLastUpdatedAt(Date.now());
          resetStaleTimer();
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
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, accountId, resetStaleTimer]);

  return { snapshot, status, isStale, lastUpdatedAt };
}
