"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { L12Verdict } from "@/types";
import { subscribe } from "@/lib/realtime/multiplexer";
import type { WsConnectionStatus } from "@/lib/realtime/connectionState";
import { STALE_THRESHOLDS_MS } from "@/lib/realtime/connectionState";
import { useSystemStore } from "@/store/useSystemStore";

interface UseLiveSignalsResult {
  verdicts: L12Verdict[];
  status: WsConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object";
}

function isL12Verdict(value: unknown): value is L12Verdict {
  if (!isRecord(value)) return false;
  return (
    typeof value.symbol === "string" &&
    typeof value.verdict === "string" &&
    typeof value.confidence === "number" &&
    Array.isArray(value.gates) &&
    typeof value.timestamp === "number"
  );
}

function getVerdictUpdatedPayload(
  payload: unknown
): { pair: string; verdict: Record<string, unknown> } | null {
  if (!isRecord(payload)) return null;
  if (typeof payload.pair !== "string" || !isRecord(payload.verdict)) return null;
  return { pair: payload.pair, verdict: payload.verdict };
}

function getVerdictSnapshotPayload(
  payload: unknown
): { verdicts: Record<string, Record<string, unknown>> } | null {
  if (!isRecord(payload) || !isRecord(payload.verdicts)) return null;
  const entries = Object.entries(payload.verdicts);
  const verdicts: Record<string, Record<string, unknown>> = {};
  for (const [pair, value] of entries) {
    if (!isRecord(value)) return null;
    verdicts[pair] = value;
  }
  return { verdicts };
}

/**
 * useLiveSignals
 *
 * Bootstrap: caller provides initial verdicts from REST (useAllVerdicts / SWR).
 * Stream:    multiplexed /ws/live — PipelineResultUpdated + VerdictUpdated events.
 * Merge:     replace list (backend sends full updated list on change).
 * Stale:     90s no message → isStale = true (STALE_THRESHOLDS_MS.verdicts).
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

    const unsub = subscribe({
      filter: (e) =>
        e.type === "PipelineResultUpdated" ||
        e.type === "VerdictUpdated" ||
        e.type === "VerdictSnapshot" ||
        e.type === "SignalUpdated",
      onEvent: (event) => {
        if (event.type === "PipelineResultUpdated" && event.payload) {
          if (!isL12Verdict(event.payload)) return;
          const payload = event.payload;
          setVerdicts((prev) => {
            const idx = prev.findIndex((v) => v.symbol === payload.symbol);
            // Timestamp guard: reject WS update older than current state
            if (idx !== -1 && payload.timestamp <= prev[idx].timestamp) return prev;
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
          const updatedPayload = getVerdictUpdatedPayload(event.payload);
          if (!updatedPayload) return;
          const { pair, verdict } = updatedPayload;
          const incomingTs = typeof verdict.timestamp === "number" ? verdict.timestamp : Date.now();
          const mapped: L12Verdict = {
            symbol: pair,
            verdict: (verdict.verdict as L12Verdict["verdict"]) ?? "HOLD",
            confidence: typeof verdict.confidence === "number" ? verdict.confidence : 0,
            gates: Array.isArray(verdict.gates) ? verdict.gates : [],
            timestamp: incomingTs,
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
            // Timestamp guard: reject WS update older than current state
            if (idx !== -1 && incomingTs <= prev[idx].timestamp) return prev;
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
          const snapshotPayload = getVerdictSnapshotPayload(event.payload);
          if (!snapshotPayload) return;
          const verdictMap = snapshotPayload.verdicts;
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
          // Snapshot replaces all — use latest timestamps per symbol
          setVerdicts((prev) => {
            const merged = new Map(prev.map((v) => [v.symbol, v]));
            for (const incoming of mapped) {
              const existing = merged.get(incoming.symbol);
              if (!existing || incoming.timestamp >= existing.timestamp) {
                merged.set(incoming.symbol, incoming);
              }
            }
            return Array.from(merged.values());
          });
          setLastUpdatedAt(Date.now());
          resetStaleTimer();
        }
      },
      onStatusChange: (s) => {
        setStatus(s);
        useSystemStore.getState().setSignalWsStatus(s);
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

  return { verdicts, status, isStale, lastUpdatedAt };
}
