"use client";

import { useEffect, useRef } from "react";
import { fetchLatestPipelineResult } from "@/services/pipelineService";
import { subscribe, getTransport } from "@/lib/realtime/multiplexer";
import { useAccountStore } from "@/store/useAccountStore";
import { usePreferencesStore } from "@/store/usePreferencesStore";
import { useSystemStore } from "@/store/useSystemStore";

interface UseLivePipelineOptions {
  symbol?: string;
  accountId?: string;
}

const POLL_INTERVAL_MS = 15_000; // 15s REST polling fallback when both WS+SSE are down
const POLL_FALLBACK_DELAY_MS = 30_000; // 30s before activating REST polling after stream loss

const toComplianceState = (governance?: string): string => {
  if (!governance || governance === "OK") return "COMPLIANCE_NORMAL";
  if (governance === "BLOCKED") return "COMPLIANCE_BLOCK";
  if (governance === "CAUTION" || governance === "DOWNGRADED") return "COMPLIANCE_CAUTION";
  return "COMPLIANCE_NORMAL";
};

export function useLivePipeline(options: UseLivePipelineOptions = {}) {
  const { setLatestPipelineResult, updateTrade } = useAccountStore();
  const setPreferences = usePreferencesStore((s) => s.setPreferences);
  const setComplianceState = useSystemStore((s) => s.setComplianceState);
  const setWsStatus = useSystemStore((s) => s.setWsStatus);
  const setSystem = useSystemStore((s) => s.setSystem);
  const setMode = useSystemStore((s) => s.setMode);

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollFallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    const doFetch = () => {
      fetchLatestPipelineResult(options.symbol, options.accountId)
        .then((result) => {
          if (mountedRef.current) {
            setLatestPipelineResult(result);
            setComplianceState(toComplianceState(result.governance_state));
          }
        })
        .catch((error) => {
          if (mountedRef.current) {
            setMode("DEGRADED");
            setSystem({
              mode: "DEGRADED",
              reason: error instanceof Error ? error.message : "Pipeline fetch failed",
            });
          }
        });
    };

    // Bootstrap: initial REST snapshot
    doFetch();

    const startPolling = () => {
      if (pollTimerRef.current) return; // already polling
      pollTimerRef.current = setInterval(doFetch, POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    const clearPollFallbackTimer = () => {
      if (pollFallbackTimerRef.current) {
        clearTimeout(pollFallbackTimerRef.current);
        pollFallbackTimerRef.current = null;
      }
    };

    // Schedule REST polling after 30s if streams (WS+SSE) remain down
    const schedulePollFallback = () => {
      if (pollFallbackTimerRef.current) return; // already scheduled
      pollFallbackTimerRef.current = setTimeout(() => {
        pollFallbackTimerRef.current = null;
        if (mountedRef.current) {
          const transport = getTransport();
          // Only start polling if no streaming transport is LIVE
          if (transport !== "WS" && transport !== "SSE") {
            setMode("POLLING");
            setSystem({
              mode: "POLLING",
              reason: "WebSocket and SSE unavailable. Using REST polling.",
            });
            startPolling();
          }
        }
      }, POLL_FALLBACK_DELAY_MS);
    };

    // Stream: live pipeline via multiplexed WS → SSE → polling chain
    const unsub = subscribe({
      filter: (e) =>
        e.type === "PipelineResultUpdated" ||
        e.type === "PipelineUpdated" ||
        e.type === "ExecutionStateUpdated" ||
        e.type === "PreferencesUpdated",
      onEvent: (event) => {
        if (!mountedRef.current) return;

        if (event.type === "PipelineResultUpdated" && event.payload) {
          setLatestPipelineResult(event.payload);
          setComplianceState(toComplianceState(event.payload.governance_state));
        }

        if (event.type === "PipelineUpdated" && event.payload) {
          const raw = event.payload as unknown as Record<string, unknown>;
          if ("symbol" in raw && "verdict" in raw) {
            setLatestPipelineResult(raw as unknown as Parameters<typeof setLatestPipelineResult>[0]);
            setComplianceState(toComplianceState(raw.governance_state as string | undefined));
          }
        }

        if (event.type === "ExecutionStateUpdated" && event.payload?.trade) {
          updateTrade(event.payload.trade);
        }

        if (event.type === "PreferencesUpdated" && event.payload) {
          setPreferences(event.payload);
        }
      },
      onStatusChange: (status) => {
        setWsStatus(status);

        if (status === "LIVE") {
          // Stream is active (WS or SSE) — stop polling, cancel fallback timer
          clearPollFallbackTimer();
          stopPolling();

          const transport = getTransport();
          if (transport === "SSE") {
            setMode("SSE");
          } else {
            setMode("NORMAL");
          }
        } else if (status === "DEGRADED" || status === "DISCONNECTED") {
          // Stream lost — schedule REST polling fallback after 30s
          // (multiplexer handles WS→SSE escalation internally at 30s)
          schedulePollFallback();
        }
      },
      onDegradation: (status) => {
        setSystem(status);

        // If degradation reports SSE mode, reflect that
        if (status.mode === "SSE") {
          setMode("SSE");
        }
      },
      onError: (error) => {
        setSystem({
          mode: "DEGRADED",
          reason: error instanceof Error ? error.message : "Live pipeline channel error",
        });
        schedulePollFallback();
      },
    });

    return () => {
      mountedRef.current = false;
      unsub();
      stopPolling();
      clearPollFallbackTimer();
    };
  }, [
    options.symbol,
    options.accountId,
    setLatestPipelineResult,
    updateTrade,
    setPreferences,
    setComplianceState,
    setMode,
    setSystem,
    setWsStatus,
  ]);
}
