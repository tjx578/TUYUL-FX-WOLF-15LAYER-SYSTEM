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
  enabled = true,
  onSeqGap?: () => void
): UseLiveSignalsResult {
  const [verdicts, setVerdicts] = useState<L12Verdict[]>(initialVerdicts);
  const [status, setStatus] = useState<WsConnectionStatus>("CONNECTING");
  const [isStale, setIsStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsDeliveredRef = useRef(false);

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

        // ── Backend-native verdict.update (normalised to VerdictUpdated) ──
        if (event.type === "VerdictUpdated") {
          wsDeliveredRef.current = true;
          const { pair, verdict } = event.payload as {
            pair: string;
            verdict: Record<string, unknown>;
          };
          const mapped: L12Verdict = {
            symbol: pair,
            verdict: (verdict.verdict as L12Verdict["verdict"]) ?? "HOLD",
            confidence: typeof verdict.confidence === "number" ? verdict.confidence : 0,
            gates: Array.isArray(verdict.gates) ? verdict.gates : [],
            timestamp: typeof verdict.timestamp === "number" ? verdict.timestamp : Date.now(),
            direction: verdict.direction as L12Verdict["direction"],
            entry_price: verdict.entry_price as number | undefined,
            stop_loss: verdict.stop_loss as number | undefined,
            take_profit_1: verdict.take_profit_1 as number | undefined,
            risk_reward_ratio: verdict.risk_reward_ratio as number | undefined,
            wolf_status: verdict.wolf_status as string | undefined,
            scores: verdict.scores as L12Verdict["scores"],
            expires_at: verdict.expires_at as number | undefined,
          };
          setVerdicts((prev) => {
            const idx = prev.findIndex((v) => v.symbol === pair);
            if (idx === -1) return [mapped, ...prev];
            const next = [...prev];
            next[idx] = mapped;
            return next;
          });
          setLastUpdatedAt(Date.now());
          resetStaleTimer();
        }

        // ── Backend verdict.snapshot (normalised to VerdictSnapshot) ──
        if (event.type === "VerdictSnapshot") {
          wsDeliveredRef.current = true;
          const { verdicts: verdictMap } = event.payload as {
            verdicts: Record<string, Record<string, unknown>>;
          };
          const mapped: L12Verdict[] = Object.entries(verdictMap).map(
            ([pair, v]) => ({
              symbol: pair,
              verdict: (v.verdict as L12Verdict["verdict"]) ?? "HOLD",
              confidence: typeof v.confidence === "number" ? v.confidence : 0,
              gates: Array.isArray(v.gates) ? v.gates : [],
              timestamp: typeof v.timestamp === "number" ? v.timestamp : Date.now(),
              direction: v.direction as L12Verdict["direction"],
              entry_price: v.entry_price as number | undefined,
              stop_loss: v.stop_loss as number | undefined,
              take_profit_1: v.take_profit_1 as number | undefined,
              risk_reward_ratio: v.risk_reward_ratio as number | undefined,
              wolf_status: v.wolf_status as string | undefined,
              scores: v.scores as L12Verdict["scores"],
              expires_at: v.expires_at as number | undefined,
            })
          );
          setVerdicts(mapped);
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
      onSeqGap: () => onSeqGap?.(),
      onError: () => setStatus("DEGRADED"),
    });

    return () => {
      controls.close();
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
  }, [enabled, resetStaleTimer]);

  return { verdicts, status, isStale, lastUpdatedAt };
}
