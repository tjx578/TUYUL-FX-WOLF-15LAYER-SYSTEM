"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { RiskSnapshot } from "@/types";
import { connectLiveUpdates } from "@/lib/realtime/realtimeClient";
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
 * Stream:    /ws/risk — full RiskSnapshot replacement every 1s.
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
  // Track whether WS has delivered data — prevents stale REST from overwriting
  const wsActiveRef = useRef(false);

  // Sync initial snapshot from REST, but only if WS hasn't pushed newer data
  useEffect(() => {
    if (initialSnapshot && !wsActiveRef.current) {
      setSnapshot(initialSnapshot);
    }
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
    // Reset WS tracking on fresh connection cycle
    wsActiveRef.current = false;

    const path = accountId ? `/ws/risk?account_id=${accountId}` : "/ws/risk";

    const controls = connectLiveUpdates({
      path,
      onEvent: (event) => {
        if (event.type === "RiskUpdated") {
          wsActiveRef.current = true;
          setSnapshot((prev) =>
            mergeSingle(prev, event.payload as unknown as RiskSnapshot)
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
  }, [enabled, accountId, resetStaleTimer]);

  return { snapshot, status, isStale, lastUpdatedAt };
}
